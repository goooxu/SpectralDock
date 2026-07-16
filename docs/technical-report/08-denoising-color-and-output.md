# 08　降噪、色调映射与输出

路径积分器输出的是浮点线性 HDR 辐亮度，而显示器和 PNG 通常使用有限范围的 sRGB 8 bit 数值。从前者到后者必须经过一条明确的颜色管线：

~~~text
sRGB 图像纹理解码
  → 在线性 RGB 中计算路径贡献
  → 可选 direct / indirect 保色相贡献钳位
  → spp 平均
  ├→ 可选线性 RGB PFM（钳位后、不降噪、不曝光）
  └→ 可选 OptiX HDR 降噪
  → 2^EV 曝光
  → 逐通道 ACES 风格拟合曲线
  → 精确分段 sRGB 编码
  → 四舍五入到设备端 RGBA8
  → D2H 回传到主机内存
  → libpng 写入 PNG
~~~

![从图像纹理到线性路径积分再到 PNG 的颜色管线](figures/color-pipeline.svg)

*图 7：非线性的显示变换全部位于样本平均之后。贡献钳位发生在平均之前且可能引入偏差；降噪与色调映射改变最终图像，但不是渲染方程中的光传输。*

## 1. 为什么必须在线性空间计算

物理光贡献可以相加。例如两盏同样的灯照到一点，线性辐亮度应变为两倍。sRGB 像素值为了适应显示和人眼感知，已经做过非线性编码，不能直接相加或平均。

标记为 sRGB 的纹理在设备采样后，对 RGB 每个通道执行

$$
c_{\text{linear}}=
\begin{cases}
c_{\text{sRGB}}/12.92,
&c_{\text{sRGB}}\le0.04045,\\
\left(\dfrac{c_{\text{sRGB}}+0.055}{1.055}\right)^{2.4},
&c_{\text{sRGB}}>0.04045.
\end{cases}
$$

alpha 通道不代表亮度，不做 sRGB 解码。标记为 `linear` 的图像与 Python API 传入的 `base_color`、`emission` 常量也直接作为线性数值使用。

Radiance Pavilion 明确以 `color_space="srgb"` 注册 Sparky atlas，并让 `ScreenFace`、`ScreenChest`、`ScreenPalm` 三个 `usemtl` 槽共享由它创建的 typed texture/material handles。MTL 的 `map_Kd` 不会自动加载纹理或决定色彩空间，`Kd`、`illum` 和槽名也不会推断 BSDF；这些选择全部留在 Python 程序。即使槽名是 `EmitYellow`，该示例仍显式绑定 Lambertian，因此它不是 emitter，HDR 环境继续是唯一光源。

所有 BSDF、吞吐量、直接光、路径累积和 spp 平均都在线性 RGB 中进行。启用时，firefly 控制会在每份完整路径贡献加入样本 radiance 之前按最大 RGB 通道做统一比例缩放；它仍在线性空间中，但已经改变估计量，详见[第 4 章第 6 节](04-monte-carlo-path-tracing.md#6-firefly-与两级贡献钳位)。

一个实现限制是：CUDA texture object 先对 8 bit sRGB 码值做双线性过滤，`sample_texture` 在 `tex2D` 返回后才手工解码。因此路径计算使用的是解码后的线性值，但 sRGB 纹理的**插值本身**并非在线性空间完成，和“先逐 texel 解码再过滤”的严格结果略有差异。

<!-- source-snippet id="output-texture-srgb-decode" path="src/device_programs.cu" anchor="texture.flags & spectraldock::kTextureSrgb" -->
```cpp
  const float u = fminf(fmaxf(uv.x, 0.0f), 1.0f);
  const float v = 1.0f - fminf(fmaxf(uv.y, 0.0f), 1.0f);
  float4 value =
      tex2D<float4>(static_cast<cudaTextureObject_t>(texture.object), u, v);
  if ((texture.flags & spectraldock::kTextureSrgb) != 0u) {
    value.x = srgb_channel_to_linear(value.x);
    value.y = srgb_channel_to_linear(value.y);
    value.z = srgb_channel_to_linear(value.z);
  }
  return value;
}
```

代码顺序直接揭示这个限制：`tex2D` 先完成过滤，之后才检查 `kTextureSrgb` 并逐个解码 `value.x/y/z`；`value.w` 从未送入解码函数，因此 alpha 保持 `tex2D` 返回的过滤后值。

## 2. 首命中引导层

raygen 除 beauty 外，还输出两种降噪引导信息。每条样本路径只在第一个有效交点写入：

- **albedo**：首命中处纹理调制后的 `base_color`；
- **normal**：首命中法线在相机基 $(\mathbf u,\mathbf v,\mathbf w)$ 上的三个投影。

每像素先对 spp 份引导值求平均，法线平均后再归一化。未命中背景的样本不写引导，因此它们对平均值贡献零。

这些缓冲区帮助降噪器区分“随机亮度波动”和真实的材质/几何边缘。mapped mesh 的 closest-hit 先用 primitive index 从共享材质 ID buffer 选择 `MaterialData`，再由同一代码写 albedo guide；因此同一 GAS 内的材质槽边界自然进入引导层，不需要为每个槽复制 GAS 或增加 SBT records。它们不是独立渲染通道：albedo 对金属或发光材质也只是当前实现提供的特征，不应解释成严格的漫反射反照率分解。

<!-- source-snippet id="output-first-hit-guides" path="src/device_programs.cu" anchor="if (guide_written == 0)" -->
```cpp
      const MaterialData material = params.materials[hit.material_index];
      const float3 base_color = material_color(material, hit.uv);
      if (guide_written == 0) {
        albedo_sum = add(albedo_sum, base_color);
        const float3 camera_normal =
            f3(dot3(hit.normal, params.camera.u),
               dot3(hit.normal, params.camera.v),
               dot3(hit.normal, params.camera.w));
        normal_sum = add(normal_sum, camera_normal);
        guide_written = 1;
      }
```

`guide_written` 把写入限定在首个有效交点；albedo 直接累加纹理调制后的 `base_color`，normal 的三个分量分别是世界法线与相机基 $\mathbf u$、$\mathbf v$、$\mathbf w$ 的点积。外层样本循环结束后，这两个和与 beauty 一样除以 spp。

## 3. OptiX HDR 降噪

降噪是 `render_optix` 中的可选分支。默认先让 `final_beauty` 指向路径追踪产生的 `beauty`；只有 `Renderer.render(denoise=True)` 时才调用 [`run_denoiser`](../../src/optix_renderer.cpp)，并把 `final_beauty` 改为降噪输出。因此两条路径的分歧只在是否经过 OptiX Denoiser，后面共享同一套曝光和显示变换。若启用了贡献钳位，raygen 写入的 `beauty` 已经是钳位后样本的平均值，Denoiser 不会看到被钳掉的长尾。

`run_denoiser` 按以下顺序完成一次完整的 HDR 降噪：

| 阶段 | 实现 | 数据含义 |
|---|---|---|
| 1. 创建 | 设置 `guideAlbedo` 和 `guideNormal`，以 `OPTIX_DENOISER_MODEL_KIND_HDR` 调用 `optixDenoiserCreate` | 明确模型处理 HDR beauty，并启用两种引导层 |
| 2. 查询资源 | `optixDenoiserComputeMemoryResources` | 根据当前宽高获得 state 和 scratch 大小 |
| 3. 分配缓冲 | 创建 `denoiser_state`、`scratch`、`intensity` 和独立 `output` | state/scratch 是工作区，intensity 是 HDR 尺度，output 避免覆盖原始 beauty |
| 4. 初始化 | `optixDenoiserSetup` | 在同一 CUDA stream 上用 state 和 scratch 准备降噪器 |
| 5. 强度估计 | 把 beauty 描述为 `OptixImage2D`，调用 `optixDenoiserComputeIntensity` | 从线性 HDR beauty 计算自适应强度尺度 |
| 6. 组装输入 | 绑定 albedo/normal guide，设置 beauty input 和 output layer | 引导层保护材质和几何边缘 |
| 7. 执行 | `hdrIntensity` 指向 intensity，`blendFactor = 0`，调用 `optixDenoiserInvoke` | 完全采用降噪结果，不与原图混合 |
| 8. 完成 | `cudaStreamSynchronize` 后返回 output | 确保返回的设备缓冲已可供后处理读取 |

这些 API 操作都在曝光和显示变换之前完成，因而输入输出仍是线性 HDR。state、scratch、intensity 和输出缓冲都由 RAII 对象管理；`OptixState` 在本次 `render_optix` 结束时销毁 denoiser。

降噪器利用空间结构和训练得到的先验预测低噪图像。它能显著改善低 spp 结果，但可能平滑细节、改变亮点或产生重建伪影。它不增加 Monte Carlo 样本，也不属于无偏积分器的一部分。

<!-- source-snippet id="output-denoiser-guide-wiring" path="src/optix_renderer.cpp" anchor="guide.albedo = image_2d" -->
```cpp
  OptixDenoiserGuideLayer guide{};
  guide.albedo = image_2d(albedo, width, height);
  guide.normal = normal_image_2d(normal, width, height);
  OptixDenoiserLayer layer{};
  layer.input = beauty_image;
  layer.output = image_2d(output, width, height);
  OptixDenoiserParams parameters{};
  parameters.hdrIntensity = intensity.pointer();
  parameters.blendFactor = 0.0f;
  check_optix(optixDenoiserInvoke(
                  state.denoiser, stream, &parameters,
                  denoiser_state.pointer(), denoiser_state.size(),
                  &guide, &layer, 1, 0, 0,
                  scratch.pointer(), scratch.size()),
              "optixDenoiserInvoke");
  check_cuda(cudaStreamSynchronize(stream),
             "cudaStreamSynchronize(denoiser)");
  return output;
}
```

`guide.albedo` 和 `guide.normal` 把上一节生成的缓冲区接入 denoiser；`layer.input/output` 分开原始 beauty 与重建结果，`hdrIntensity` 提供 HDR 强度尺度，`blendFactor = 0` 对应“完全采用降噪结果”。紧随 invoke 的 stream 同步是这个可选阶段的明确完成边界。

## 4. 从 HDR beauty 到主机 PNG 的边界

OptiX 的职责在线性 HDR beauty 处结束。`render_optix` 用 `final_beauty` 统一后续输入：未开降噪时它指向 raygen 写入的 `beauty`，开启时则指向 `run_denoiser` 返回的 `denoised`。随后的边界是：

~~~text
clamped/linear beauty ─┐
                       ├→ final_beauty → 普通 CUDA postprocess kernel → 设备端 uchar4
denoised ──────────────┘                                           ↓ D2H + stream sync
                                                    RenderResult::rgba
                                                              ↓ Python binding/libpng
                                                           PNG 文件
~~~

`spectraldockLaunchPostprocess` 是用 `<<<...>>>` 启动的普通 CUDA kernel，不是 OptiX program。它在同一 stream 上读取 `final_beauty`，完成曝光、ACES 风格曲线、sRGB 编码和 RGBA8 量化。之后 `DeviceBuffer::download` 把设备端 RGBA8 复制到主机端局部 `rgba`，`cudaStreamSynchronize(stream)` 形成 GPU 工作的完成边界，再把缓冲移动到 `RenderResult::rgba`。

`render_optix` 本身不写 PNG；它返回主机端 `RenderResult`。`_native.render_to_files` 随后调用 `write_png_rgba8`，由 libpng 把这份 RGBA8 数组编码到 Python 程序明确指定的路径。因此 Denoiser 是 OptiX 可选阶段，颜色变换是纯 CUDA 计算，D2H 之后的 PNG 编码则是 CPU 工作。

## 5. 线性 PFM 分支

PNG 是始终存在的展示输出；`Renderer.render(linear_output=Path("FILE.pfm"))` 可增加测量输出。它直接从 raygen 已按 spp 平均的 `beauty` 下载 RGB，不读取 `final_beauty`，所以即使同时启用 Denoiser，PFM 也仍保存**降噪前**数值。曝光、ACES 风格曲线、sRGB 编码和 8 bit 量化同样不作用于 PFM。

PFM 位于贡献钳位之后：Python 程序若使用非零 `clamp_direct`/`clamp_indirect`，PFM 保存的是这个有偏估计。它能排除 Denoiser 和显示变换，却不能自动恢复被钳位的长尾。均值、方差、MSE 或能量对照必须调用 `render(denoise=False, clamp_direct=0, clamp_indirect=0, linear_output=...)`。

PFM 头为 `PF`，负 scale `-1.0` 声明 little-endian float32，像素行按格式要求从底到顶保存。它不携带完整色彩空间元数据、层、压缩或任意通道，因此这里把它当作小型确定性实验接口，而不是 OpenEXR 的替代品。

<!-- source-snippet id="output-linear-pfm" path="src/image_io.cpp" anchor="std::ofstream output" -->
```cpp
  std::ofstream output(path, std::ios::binary);
  if (!output)
    throw std::runtime_error("cannot open PFM for writing: " + path.string());
  output << "PF\n" << width << ' ' << height << "\n-1.0\n";

  const std::size_t row_values = static_cast<std::size_t>(width) * channels;
  std::vector<std::uint8_t> row(row_values * sizeof(float));
  for (std::uint32_t source_y = height; source_y-- > 0;) {
    const float* source = pixels.data() +
                          static_cast<std::size_t>(source_y) * row_values;
```

`source_y` 从 `height - 1` 递减到 0，把主机中 top-to-bottom 的 `linear_rgb` 转成 PFM 的 bottom-to-top 行序；后续循环把每个 IEEE-754 float 的四个字节显式写成小端顺序，因此不依赖主机本身的端序。

## 6. EV 曝光

对原始或降噪后的线性值 $c$，先乘

$$
x=\max(0,c)\,2^{EV}.
$$

因此 EV +1 把线性值乘 2，EV −1 除以 2。曝光只改变怎样把已有 HDR 数值映射到显示范围，不会补回场景中缺失的照明或更长路径。

若输入通道不是有限数，后处理将其替换为 0；负值也在色调曲线入口钳到 0。

## 7. ACES 风格拟合曲线

线性 HDR 可能远大于 1，直接截断会让高光全部变成纯白。SpectralDock 逐通道使用

$$
T(x)=\mathrm{clamp}\left(
\frac{x(2.51x+0.03)}{x(2.43x+0.59)+0.14},
0,1
\right).
$$

它在暗部近似保留差异，同时把很亮的数值平滑压缩到 1 附近。

这应准确称为 **ACES-inspired fitted curve（ACES 风格拟合曲线）**，而不是完整 ACES 色彩管理流程。实现没有 ACES 色彩空间转换、完整 RRT/ODT、显示设备选择或色域映射；逐 RGB 通道独立压缩还可能改变饱和高光的色相。

<!-- source-snippet id="output-aces-fitted" path="src/postprocess.cu" anchor="float aces_fitted(float value)" -->
```cpp
static __forceinline__ __device__ float aces_fitted(float value) {
  const float x = fmaxf(value, 0.0f);
  return fminf(fmaxf((x * (2.51f * x + 0.03f)) /
                         (x * (2.43f * x + 0.59f) + 0.14f),
                     0.0f),
               1.0f);
}
```

`aces_fitted` 逐项实现本节的有理拟合曲线；入口和出口的两次钳制分别处理负值与显示范围上限。

## 8. sRGB 输出编码

色调映射后的线性显示值 $T\in[0,1]$ 再编码为 sRGB：

$$
c_{\text{sRGB}}=
\begin{cases}
12.92T,&T\le0.0031308,\\
1.055T^{1/2.4}-0.055,&T>0.0031308.
\end{cases}
$$

这不是简单的“gamma 2.2”；暗部是线性段，亮部指数也是 $1/2.4$。输入纹理解码与输出编码使用对应的精确分段函数。

最后四舍五入并钳制：

$$
b=\mathrm{clamp}
\left(\left\lfloor255c_{\text{sRGB}}+0.5\right\rfloor,0,255\right).
$$

<!-- source-snippet id="output-srgb-and-quantize" path="src/postprocess.cu" anchor="float linear_to_srgb(float value)" -->
```cpp
static __forceinline__ __device__ float linear_to_srgb(float value) {
  const float x = fminf(fmaxf(value, 0.0f), 1.0f);
  return x <= 0.0031308f ? 12.92f * x
                         : 1.055f * powf(x, 1.0f / 2.4f) - 0.055f;
}

static __forceinline__ __device__ unsigned char to_byte(float value) {
  return static_cast<unsigned char>(
      fminf(fmaxf(floorf(value * 255.0f + 0.5f), 0.0f), 255.0f));
}
```

`linear_to_srgb` 的阈值和两个分支与公式一致；`to_byte` 中的 `floorf(value * 255 + 0.5)` 实现四舍五入，外层钳制保证结果落在 8 bit 范围。

RGB 三个通道写入 `uchar4`，alpha 固定为 255。主机把 RGBA8 缓冲区写成 PNG；最终 PNG 不再保留色调映射前的 HDR 数值，需要定量分析时应显式请求上一节的 PFM。

<!-- source-snippet id="output-postprocess-kernel" path="src/postprocess.cu" anchor="const float multiplier = exp2f(exposure);" -->
```cpp
__global__ void postprocess_kernel(const float4* linear_beauty,
                                   uchar4* output,
                                   std::uint32_t pixel_count,
                                   float exposure) {
  const std::uint32_t index =
      blockIdx.x * static_cast<std::uint32_t>(blockDim.x) + threadIdx.x;
  if (index >= pixel_count) {
    return;
  }
  const float4 source = linear_beauty[index];
  const float multiplier = exp2f(exposure);
  float r = isfinite(source.x) ? source.x * multiplier : 0.0f;
  float g = isfinite(source.y) ? source.y * multiplier : 0.0f;
  float b = isfinite(source.z) ? source.z * multiplier : 0.0f;
  r = linear_to_srgb(aces_fitted(r));
  g = linear_to_srgb(aces_fitted(g));
  b = linear_to_srgb(aces_fitted(b));
  output[index] = make_uchar4(to_byte(r), to_byte(g), to_byte(b), 255u);
}
```

这里可以读出完整数据流：`exp2f(exposure)` 实现 $2^{EV}$，非有限输入先归零，RGB 依次经过 `aces_fitted`、`linear_to_srgb`、`to_byte`，最后与常量 alpha 255 一起写入 `uchar4`。显示变换都发生在已平均（并可能已降噪）的 `linear_beauty` 上。

## 9. 一个数值例子

假设一个线性通道值为 $c=2$，曝光 EV = −1：

1. 曝光后 $x=2\times2^{-1}=1$；
2. 拟合曲线给出
   $$
   T(1)=\frac{2.54}{3.16}\approx0.804;
   $$
3. sRGB 编码约为
   $$
   1.055(0.804)^{1/2.4}-0.055\approx0.908;
   $$
4. 8 bit 值约为 $\mathrm{round}(0.908\times255)=232$。

这个例子也说明“线性值 2”并非溢出。HDR 阶段允许保存它，直到最后决定如何显示。

## 10. 对应实现

- 输入纹理解码：[`sample_texture`、`srgb_channel_to_linear`](../../src/device_programs.cu)
- spp 平均和首命中 guide：[`__raygen__pathtrace`](../../src/device_programs.cu)
- 可选 HDR 降噪：[`run_denoiser`](../../src/optix_renderer.cpp)
- raw/denoised 选择、CUDA 后处理与 D2H：[`render_optix`](../../src/optix_renderer.cpp)
- 曝光、拟合曲线、sRGB 和量化：[`src/postprocess.cu`](../../src/postprocess.cu)
- 主机 PNG 编码：[`write_png_rgba8`](../../src/image_io.cpp)
- 钳位后、降噪前的线性 PFM：[`write_pfm_rgb32f`](../../src/image_io.cpp)

下一章将把“噪声、偏差、模型限制、性能计时和软件测试”分开，说明怎样判断渲染结果是否可信。

[上一章：OptiX/GPU 实现](07-optix-gpu-implementation.md) · [返回目录](README.md) · [下一章：边界、性能与验证](09-limitations-performance-and-validation.md)
