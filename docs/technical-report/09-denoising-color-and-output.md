# 09　降噪、HDR 映射与 AVIF 输出

路径积分器产生浮点、线性 Rec.709 RGB 辐亮度。SpectralDock 不把它压成
SDR：每次渲染固定写出带完整色彩标识的 HDR AVIF。当前颜色管线是：

~~~text
8 bit AVIF 纹理 → 在线性 RGB 中采样与积分 → direct/indirect 贡献钳位
  → spp 平均 → 可选 OptiX HDR Denoiser → float RGB D2H
  → 2^EV 曝光 → 线性 Rec.709 到 Rec.2020
  → 保色相 max-RGB soft shoulder（203 nit diffuse white，1000 nit peak）
  → SMPTE ST 2084 PQ → BT.2020 NCL YUV → 10 bit 4:4:4 full range
  → libavif/AOM AV1 lossless → 单帧 HDR AVIF（CICP 9/16/9）
~~~

![从 AVIF 纹理到线性路径积分再到 HDR AVIF 的颜色管线](figures/color-pipeline.svg)

*图 7：贡献钳位发生在样本平均之前；降噪与显示映射发生在平均之后。输出
AVIF 保留 PQ HDR 显示范围，但它仍是经过曝光、肩部映射和 10 bit 量化的展示
编码，不等同于未处理的积分器浮点缓冲。*

## 1. AVIF 纹理与线性积分

颜色纹理和材质数据图都使用单帧 8 bit AVIF。颜色纹理由 Python API 标记为
`srgb`；normal、metallic-roughness 和 alpha 等数据图标记为 `linear`。后者还
必须满足 YUV 4:4:4 full range、BT.709 primaries、linear transfer、identity
matrix 和非预乘 alpha 的严格输入契约。Radiance RGBE `.hdr` 仅保留为线性环境
贴图输入。

标记为 sRGB 的纹理由 CUDA texture hardware 在 filtering **之前**完成 transfer
conversion，再在线性空间双线性过滤：

$$
c_{\mathrm{linear}}=
\begin{cases}
c_{\mathrm{sRGB}}/12.92,&c_{\mathrm{sRGB}}\le0.04045,\\
\left((c_{\mathrm{sRGB}}+0.055)/1.055\right)^{2.4},&\text{otherwise}.
\end{cases}
$$

<!-- source-snippet id="output-texture-srgb-decode" path="src/optix_renderer.cpp" anchor="td.sRGB" -->
```cpp
  cudaTextureDesc td{};
  td.addressMode[0] = texture_address_mode(source.wrap_u);
  td.addressMode[1] = texture_address_mode(source.wrap_v);
  td.filterMode = cudaFilterModeLinear;
  td.readMode = read_mode;
  td.sRGB = source.type == TextureType::Image && source.srgb ? 1 : 0;
  td.normalizedCoords = 1;
  check_cuda(cudaCreateTextureObject(&h.object, &rd, &td, nullptr),
             "cudaCreateTextureObject");
```

alpha 不做 sRGB 解码。所有 BSDF、吞吐量、直接光、路径累积与 spp 平均继续在
线性 RGB 中完成；色彩空间来自 typed texture 属性，着色器不根据文件名或 MTL
槽名猜测。

## 2. 首命中引导层与 HDR Denoiser

raygen 除 beauty 外还累计首个有效交点的 albedo 与 normal guide。mapped mesh
先按 primitive index 选择材质；normal map 因而和实际 BSDF 使用同一有效着色
法线。光滑 dielectric/water 使用几何法线作为 guide，避免插值法线扭曲界面。

<!-- source-snippet id="output-first-hit-guides" path="src/device_programs.cu" anchor="if (guide_written == 0)" -->
```cpp
      const MaterialData material = resolved_material(
          params.materials[hit.material_index], hit.uv);
      const float3 base_color = material_color(material, hit.uv);
      const float3 wo = neg(ray_direction);
      if (guide_written == 0) {
        albedo_sum = add(albedo_sum, base_color);
        const bool smooth_dielectric =
            (material.type == spectraldock::kMaterialDielectric ||
             material.type == spectraldock::kMaterialWater) &&
            material.roughness <= 0.0f;
        const float3 guide_normal = smooth_dielectric
            ? hit.geometric_normal : hit.normal;
        const float3 camera_normal =
            f3(dot3(guide_normal, params.camera.u),
               dot3(guide_normal, params.camera.v),
               dot3(guide_normal, params.camera.w));
        normal_sum = add(normal_sum, camera_normal);
        guide_written = 1;
      }
```

`Renderer.render(denoise=True)` 使用 `OPTIX_DENOISER_MODEL_KIND_HDR`。Denoiser
读取线性 HDR beauty、albedo 与 normal，在曝光和 HDR 映射之前运行。它能降低
低 spp 噪声，但不是无偏积分器的一部分，也不会恢复已被贡献钳位删除的长尾。

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

## 3. GPU/主机边界

OptiX 路径结束后，`render_optix` 把原始或降噪后的 float RGB beauty 下载到主机。
渲染器不再启动独立的 SDR 后处理 kernel，也没有公共线性文件分支。测试若需
比较未映射样本，只能使用显式的进程内测试捕获；该数据不会写入 stats sidecar，
也不是持久输出格式。

主机函数 `write_hdr_avif_rgb32f` 完成曝光、色域转换、亮度映射、PQ、YUV 与
编码。这样 AVIF 元数据和由它描述的像素来自同一处实现，并且不依赖主机字节序
或某个 GPU 型号。

## 4. 固定 HDR AVIF profile

输出 image 固定为 10 bit YUV 4:4:4 full range。CICP `9/16/9` 分别表示
BT.2020 primaries、SMPTE ST 2084 transfer 与 BT.2020 non-constant-luminance
matrix；不接受调用方覆盖。每帧还写 `maxCLL` 和 `maxPALL`。

<!-- source-snippet id="output-hdr-avif-profile" path="src/image_io.cpp" anchor="AVIF_TRANSFER_CHARACTERISTICS_SMPTE2084" -->
```cpp
  ImagePtr image(avifImageCreate(width, height, 10,
                                 AVIF_PIXEL_FORMAT_YUV444));
  if (!image) throw std::runtime_error("cannot create HDR AVIF image");
  image->colorPrimaries = AVIF_COLOR_PRIMARIES_BT2020;
  image->transferCharacteristics =
      AVIF_TRANSFER_CHARACTERISTICS_SMPTE2084;
  image->matrixCoefficients = AVIF_MATRIX_COEFFICIENTS_BT2020_NCL;
  image->yuvRange = AVIF_RANGE_FULL;
  avifResult result = avifImageAllocatePlanes(image.get(), AVIF_PLANES_YUV);
```

AOM encoder 固定使用 lossless quality。这里的“lossless”是指 PQ/YUV 10 bit
样本形成之后的 AV1 编码无损；从 float beauty 到 10 bit 本身仍发生量化。

<!-- source-snippet id="output-avif-lossless-encoder" path="src/image_io.cpp" anchor="encoder->quality = AVIF_QUALITY_LOSSLESS" -->
```cpp
  encoder->codecChoice = AVIF_CODEC_CHOICE_AOM;
  encoder->maxThreads = encoder_thread_count();
  encoder->speed = 6;
  encoder->quality = AVIF_QUALITY_LOSSLESS;
  encoder->qualityAlpha = AVIF_QUALITY_LOSSLESS;
  encoder->autoTiling = AVIF_TRUE;
  return encoder;
}
```

## 5. 曝光、色域和保色相 soft shoulder

输入中的负数、NaN 与无穷先归零；其余通道乘 $2^{EV}$。随后用固定线性矩阵
把 Rec.709/sRGB primaries 转成 Rec.2020 primaries。令转换后的
$m=\max(R,G,B)$，目标最大亮度为

$$
L(m)=
\begin{cases}
203m,&0\le m\le1,\\
203+797\left(1-\exp\left[-\dfrac{203(m-1)}{797}\right]\right),&m>1.
\end{cases}
$$

三个通道统一乘 $L(m)/m$，所以高光压缩不会因逐通道曲线而改变 RGB 比例。
线性值 1 对应 203 nit diffuse white；更亮的输入以连续斜率进入 shoulder，并
渐近到 1000 nit peak。

<!-- source-snippet id="output-rec2020-soft-shoulder" path="src/image_io.cpp" anchor="const double mapped =" -->
```cpp
      const double maximum = std::max({r, g, b});
      if (maximum > 0.0) {
        const double mapped =
            maximum <= 1.0
                ? kDiffuseWhiteNits * maximum
                : kDiffuseWhiteNits +
                      (kPeakNits - kDiffuseWhiteNits) *
                          (1.0 - std::exp(-kDiffuseWhiteNits *
                                          (maximum - 1.0) /
                                          (kPeakNits - kDiffuseWhiteNits)));
        const double scale = mapped / maximum;
        r *= scale;
        g *= scale;
        b *= scale;
      }
      r = std::clamp(r, 0.0, kPeakNits);
      g = std::clamp(g, 0.0, kPeakNits);
      b = std::clamp(b, 0.0, kPeakNits);
```

例如灰色线性值 $m=1$ 映射到 203 nit；$m=2$ 约映射到
$203+797(1-e^{-203/797})\approx382$ nit，而不是直接截成白色。

## 6. PQ、BT.2020 NCL 与量化

对每个以 nit 表示的 Rec.2020 通道，ST 2084 使用

$$
E=\left(\frac{c_1+c_2(L/10000)^{m_1}}
{1+c_3(L/10000)^{m_1}}\right)^{m_2},
$$

其中 $m_1=2610/16384$、$m_2=2523/32$、$c_1=3424/4096$、
$c_2=2413/128$、$c_3=2392/128$。PQ component signals 再按 BT.2020 NCL
转成 full-range YUV，并四舍五入到 $0\ldots1023$。

<!-- source-snippet id="output-pq-yuv-quantization" path="src/image_io.cpp" anchor="const double luma =" -->
```cpp
      const double rp = pq_encode(r);
      const double gp = pq_encode(g);
      const double bp = pq_encode(b);
      const double luma = 0.2627 * rp + 0.6780 * gp + 0.0593 * bp;
      const double chroma_blue = (bp - luma) / 1.8814;
      const double chroma_red = (rp - luma) / 1.4746;
      y_plane[x] = quantize_10bit(luma);
      u_plane[x] = quantize_chroma_10bit(chroma_blue);
      v_plane[x] = quantize_chroma_10bit(chroma_red);
```

4:4:4 为每个像素保存一份 Y、Cb、Cr，不做色度子采样。full range 则让 AV1
码值范围与上述量化公式一致。AVIF 解码器仍可选择内部输出像素布局，但必须从
文件中的 CICP 恢复正确的 Rec.2020/PQ 语义。

## 7. 对应实现

- 输入 AVIF 解码、profile 验证和 HDR AVIF 编码：
  [`src/image_io.cpp`](../../src/image_io.cpp)
- 输入纹理的硬件 sRGB 解码与过滤配置：
  [`make_texture`](../../src/optix_renderer.cpp)
- spp 平均和首命中 guide：
  [`__raygen__pathtrace`](../../src/device_programs.cu)
- 可选 HDR 降噪与 float beauty 回传：
  [`render_optix`](../../src/optix_renderer.cpp)

下一章把表面路径扩展到只吸收并自发光的程序化体积；全局限制、性能和验证
在第 13 章统一收束。

[上一章：OptiX/GPU 实现](08-optix-gpu-implementation.md) · [返回目录](README.md) · [下一章：程序化体积火焰](10-procedural-volumetric-flame.md)
