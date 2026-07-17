# 13　边界、性能与验证

一张看起来合理的图不一定数学正确；一张带噪声的图也不一定错误。评估路径追踪器时，应先区分误差来自哪里，再讨论性能和测试。

## 1. 四类不同问题

| 类别 | 含义 | SpectralDock 中的例子 | 增加 spp 能否解决 |
|---|---|---|---|
| 随机方差 | 有限样本围绕目标波动 | 小灯、太阳瓣、尖锐高光的噪点 | 能缓解，约按 $1/\sqrt N$ |
| 数值偏差 | 算法求解了近似目标 | `max_depth` 截断、非零贡献钳位 | 不能 |
| 模型误差 | 数学模型省略现实机制 | RGB、flame 无散射、无色散 | 不能 |
| 实现缺陷 | 代码没有实现既定公式 | PDF 漏掉选灯概率、方向写反 | 不能，必须修代码 |

降噪和色调映射属于另一层：**重建与显示变换**。它们可以改变观感，却不会增加积分器已经采集的路径信息。

## 2. 当前积分器的重要边界

### 光传输

- 以稳态表面光传输为主，没有通用雾、烟或散射参与介质、次表面散射与传播时间；特化的 flame 只做吸收—自发光，water 只做均匀 RGB 吸收；
- 使用线性 RGB，不模拟波长、色散、衍射或偏振；
- `max_depth` 会截断最后一个已处理表面事件之后的继续路径；最后一个事件自身的显式直接光仍完整估计；
- `Renderer.integrator()` 默认以 direct 64 / indirect 16 保色相钳位独立路径贡献，能控制 firefly 但会引入偏差；无偏参考必须把两者都设为 0；
- Radiance HDR 环境有显式重要性采样；constant、sky 渐变和太阳瓣仍没有；
- 纹理 emitter 和 mesh emitter 不能进入 NEE 灯列表；
- 有限灯在普通空气顶点按发光功率代理选择，粗糙水面确定性地各取一份全局分布和均匀索引样本，介质内其他顶点用均匀索引；所有球外连续 BSDF 顶点对 sphere 使用可见立体角，球内/近球回退仍采整个球面；point/directional 逐灯求值，最多 32 盏，shadow-ray 成本线性增长。

### 材质

- `metal` 是纯 GGX 镜面微表面瓣；`pbr` 提供 base-color、packed
  metallic-roughness 与 tangent-space normal map 的标准混合工作流；
- `metal`、`pbr` 与粗糙 `dielectric`/`water` 都使用 Heitz GGX VNDF；这降低掠射角拒绝方差，但仍是单次散射微表面模型，不含多重散射补偿；
- `dielectric` 的 `roughness = 0` 是 delta 界面，非零时是 Walter 单次散射 GGX 反射/透射；无 `water_surface` 的光滑兼容路径固定空气外部介质、使用 Schlick 且没有嵌套与体吸收，含水路径使用精确 Fresnel、严格介质栈与 RGB Beer；
- 连续 Lambert/PBR/GGX 使用有效着色法线 $\mathbf n_s^{\mathrm{eff}}$ 建立波瓣并以 `AbsDot` 融合余弦；定向几何法线 $\mathbf n_g$ 负责真实侧别、介质栈、光滑 delta Fresnel/Snell 和所有表面射线偏移；
- 不实现 shading-normal adjoint correction，所以极端倾斜顶点法线下不保证严格互易性或能量守恒；
- 粗糙 water 为了降低反射方差，把 BSDF 反射分支概率设为 $\max(F,0.5)$；物理 BSDF 仍使用精确 Fresnel $F$，路径权重和 MIS PDF 用实际分支概率补偿，所以这是无偏采样改变而不是更改材质能量；
- legacy 材质只强制 `base_color` 非负而不强制上界，能量合理性部分依赖输入；PBR `base_color`、`metallic` 和 `roughness` factor 则强制在 $[0,1]$；
- 直接光连接只表示当前顶点的一次散射；粗糙介电可在当前界面 NEE 到反射或透射侧，但下一层透明边界会阻断连接。光滑首水面只做一次有界 Fresnel 分裂，不实现 MNEE、双向路径追踪或光滑多界面焦散，详见[第 11 章](11-runtime-analytic-water.md)。

### 几何与颜色

- cylinder 没有端盖；`parabola` 是由 AABB 裁剪的抛物柱面；
- alpha 是二值 cutoff，不是连续透明或折射；
- 所有表面 radiance/shadow ray 都按 primitive-aware 的 `SurfaceHit.position_error` 沿 $\mathbf n_g$ 做尺度自适应偏移并向外舍入；解析/custom primitive 在 conservative fallback 上加入可评估曲面的 residual，但尚不保证严格封闭所有近切求交的条件数放大；固定世界空间 `water_solver_epsilon` 只用于水面 endpoint crossing probe 与无法分辨的近切 enter/exit 对，极端缩放的波面参数仍不在当前验收范围内；
- 色调映射是逐通道 ACES 风格拟合曲线，不是完整 ACES；
- 8 bit PNG 不保存 HDR 缓冲区；可选 PFM 保存贡献钳位之后、未降噪和未显示映射的线性 RGB 样本均值，没有 OpenEXR 的元数据、任意通道和压缩能力。只有 clamp 0/0 的 PFM 才适合无偏均值验证。
- 图像纹理只有 base-level 双线性过滤，没有 mipmap、ray differential 或
  各向异性过滤；PBR normal map 只支持 triangle mesh，不支持解析几何。

发光材质命中后立即终止路径，不会同时反射；HDR 环境是纬经贴图，不是光度学天空，也不包含大气散射模型。

这些是明确的设计边界。未来扩展时，应先判断新功能属于渲染方程、采样策略、几何查询还是显示变换。

## 3. 性能指标测量什么

[`RenderStats`](../../include/spectraldock/optix_renderer.h) 把一次渲染拆成几个指标。

<!-- source-snippet id="validation-cuda-event-timer" path="src/optix_renderer.cpp" anchor="cudaEventElapsedTime" -->
```cpp
class Event {
 public:
  Event() { check_cuda(cudaEventCreate(&value_), "cudaEventCreate"); }
  ~Event() { if (value_) cudaEventDestroy(value_); }
  void record(cudaStream_t stream) {
    check_cuda(cudaEventRecord(value_, stream), "cudaEventRecord");
  }
  void wait() { check_cuda(cudaEventSynchronize(value_), "cudaEventSynchronize"); }
  double elapsed(const Event& start) const {
    float ms = 0.0f;
    check_cuda(cudaEventElapsedTime(&ms, start.value_, value_),
               "cudaEventElapsedTime");
    return ms;
  }
```

各 GPU 分项都复用这个 CUDA event 包装：`record` 把时间点放进指定 stream，`wait` 等待结束事件，`cudaEventElapsedTime` 返回两个事件之间的毫秒数。因此它测量的是 GPU stream 区间，不是主机 `std::chrono` 墙钟。

### `timings_ms.bvh_build`

从开始上传/构建被引用 mesh 和每对象 primitive GAS，到 IAS 构建及满足条件时的压缩完成。它包含相关 mesh 设备上传、GAS/IAS 构建及紧凑尺寸更小时的压缩，不包含此前的纹理解码/上传和 pipeline 创建。

### `timings_ms.render`

只围绕一次 `optixLaunch` 的 CUDA event 时间，包含 raygen 路径循环、全部 radiance/shadow trace 和着色。基准表中的 **Path trace** 就是这个值。

### `timings_ms.denoise`

启用降噪时，围绕 denoiser setup、强度计算、invoke 与同步的 CUDA event 时间；关闭时为 0。

### `timings_ms.total`

在 `render_optix()` 完成 settings 与像素数检查后开始，到返回前记录。它包括 CUDA/OptiX 初始化、pipeline、纹理解码与上传、加速结构、SBT/缓冲区、路径追踪、可选降噪、后处理、RGBA/射线计数回传和设备信息查询。

它**不包括**调用前的 Python SceneBuilder 构造与 OBJ 解析，也不包括调用后的 PNG、可选 PFM 与 stats JSON 编码/写盘；启用 PFM 时，线性 beauty 的 D2H 和 float4→RGB 缓冲转换仍在 `render_optix()` 内，属于 Total。时间戳还早于函数局部 RAII 资源析构。因此 Total 不是完整 `Renderer.render()` 调用的墙钟时间，也不等于前三个分项简单相加。BVH 与 denoise 分项由同一 CUDA stream 上的 event 包围；区间可能包含主机尚未提交下一项工作时的 stream idle，不应解读成逐 kernel 时间之和。

## 4. 射线吞吐量怎样理解

每像素记录实际调用 `optixTrace` 的次数，包括常规 radiance 与二值 shadow。普通粗糙介电的随机 NEE 每个灯域至多增加一次 shadow；粗糙 water 的有限灯域有两份分层样本，因此连同环境域最多增加三次；此外每盏通过余弦/BSDF 检查的 point/directional 都可能增加一次 shadow。光滑首水面 split 会为被保留的第二个子路径增加后续 radiance 查询。令 $N_{\mathrm{rays}}$ 对应 `traced_rays`，$t_{\mathrm{render}}$ 对应以毫秒计的 `render_ms`：

$$
\text{rays/s}=
\frac{N_{\mathrm{rays}}}
{t_{\mathrm{render}}\times10^{-3}}.
$$

它不是纯 BVH microbenchmark：材质计算、随机数、分支、纹理和路径循环都在同一个 launch 内。不同场景的 rays/s 差异不应简单解释为硬件快慢。

`traced_rays` 也不等于 $W\times H\times \mathrm{spp}\times D_{\max}$，其中 $D_{\max}$ 对应 `max_depth`：路径可提前终止，普通表面可能为有限灯、环境和每盏 delta 灯各发 shadow ray，粗糙 water 还会多取一份有限灯样本，而首个光滑水面 split 可能继续两条有界子路径。

逐像素计数缓冲区在 launch 后回传到主机，并求和得到公式中的 $N_{\mathrm{rays}}$：

<!-- source-snippet id="validation-ray-count-sum" path="src/optix_renderer.cpp" anchor="ray_count.download" -->
```cpp
  ray_count.download(ray_counts.data(),
                     ray_counts.size() * sizeof(unsigned long long), stream);
  volume_count.download(volume_counts.data(),
                        volume_counts.size() * sizeof(VolumeCounters), stream);
  water_count.download(water_counts.data(),
                       water_counts.size() * sizeof(WaterCounters), stream);
  if (firefly_clamp_enabled) {
    firefly_count.download(&firefly_counts, sizeof(firefly_counts), stream);
  }
  check_cuda(cudaStreamSynchronize(stream),
             "cudaStreamSynchronize(output)");
  unsigned long long traced_rays = 0;
  for (const unsigned long long count : ray_counts)
    traced_rays += count;
```

统计结构只保留求和结果，并用 `render_ms * 1.0e-3` 完成毫秒到秒的换算：

<!-- source-snippet id="validation-rays-per-second" path="src/optix_renderer.cpp" anchor="result.stats.rays_per_second" -->
```cpp
  result.stats.water_height_evaluations = water_totals.height_evaluations;
  result.stats.water_tile_tests = water_totals.tile_tests;
  result.stats.water_roots_reported = water_totals.roots_reported;
  result.stats.water_medium_segments = water_totals.medium_segments;
  result.stats.water_solver_overflows = water_totals.solver_overflows;
  result.stats.water_medium_errors = water_totals.medium_errors;
  result.stats.water_rough_nee_attempts = water_rough_nee_attempts;
  result.stats.water_rough_nee_contributions =
      water_rough_nee_contributions;
  result.stats.water_delta_splits = water_delta_splits;
  result.stats.rays_per_second =
      render_ms > 0.0 ? traced_rays / (render_ms * 1.0e-3) : 0.0;
```

分母为零时明确返回 0，避免统计值成为无穷或 NaN。体积工作量独立保存，不混入 OptiX ray 计数。

## 5. 显存指标

- `peak_tracked_device_bytes`：项目 RAII 分配器直接记账的峰值；
- `peak_device_bytes`：在 CUDA context 与 stream 已建立后的 baseline 上，通过若干次 `cudaMemGetInfo` 采样观察到的增量峰值。它可包含随后出现的 OptiX 内部分配，可能受同 GPU 其他进程影响，也可能漏掉两个采样点之间的短峰值。

二者回答不同问题，不能把差值直接称为泄漏。正式 RTX 5090 数据见[RTX 5090 运行记录](../BENCHMARK.md)，gallery 中每张正式 PNG 旁也有对应的 stats JSON。

## 6. 测试为什么存在

测试不是渲染器的核心功能，而是按层保存其行为证据：

1. Host-only 单元测试检查向量、typed SceneBuilder、OBJ、PNG/HDR/PFM I/O、CDF 分布和输入语义；
2. typed SceneBuilder fixtures 覆盖 primitive、灯、UV、alpha、实例与共享 GAS 的输入组合，但不执行 GPU 着色；
3. 无 golden 的积分器 GPU 对照覆盖末端 bound/unbound MIS；rectangle、disk、sphere 共位 emitter 在单位坐标与 $10^6$ 平移下还要求 bound/unbound 像素完全一致，定向保护有限灯 endpoint residual/区间收缩；其余对照覆盖 HDR 环境唯一照明、旋转、确定性、零强度黑场，以及 uniform/importance 的高 spp 均值与低 spp MSE；
4. 多灯对照分别触发 rectangle、disk、sphere、flame，再验证功率选择降低强弱灯场景的低 spp MSE；sphere 对所有连续 BSDF 顶点验证可见锥采样，metal 另验证 VNDF 的均值与低样本误差；
5. 综合 mesh GPU fixture 定向覆盖共享 GAS、实例变换、UV、平滑法线、alpha 和 custom primitives；另一组极端倾斜顶点法线 fixture 检查几何正面/背面、共享边、metal/PBR half-vector、有限灯零-PDF MIS，以及光滑 dielectric 对顶点法线的像素不变性；scale-aware ray-spawn fixture 再把 directional/point 薄遮挡和 metal/dielectric 次级路径放到 $10^{-3}$、$1$、$10^4$ 尺度及 $10^6$ 平移坐标，检查可见性、非黑传输、尺度一致性与固定 seed 确定性；其中 translated case 保留一枚 custom disk blocker，专门防止 AABB 向内取整造成 BVH 漏交；
6. PBR host/API 测试检查独立 base-color/MR/normal 槽、linear 数据纹理、范围与 ownership、解析几何限制及无效 tangent 拒绝；GPU 对照检查过滤前 sRGB 解码、U/V wrap、MR 的 G/B 通道路由与 factor、`metallic=1` legacy 端点、`normal_scale`、镜像 UV/Mikk handedness、反向法线、OpenGL `+Y`、几何侧和非均匀变换；depth-2 对照还检查 secondary ray、固定 seed 确定性，并在极端着色法线下分别强制 `metallic=0/1` 的 diffuse-heavy 与纯 specular sampled transport；
7. delta 灯对照检查 point 逆平方、directional 距离不变性、背面、遮挡、逐灯确定性、粗糙介电两侧和水中 Beer；firefly 对照检查 direct/indirect 独立触发、最大 RGB 通道保色相缩放、计数器、Python API 参数覆盖和 clamp 0/0 兼容路径；
8. water GPU 对照用 clamp 0/0 线性 PFM 检查粗糙反射/透射、两侧介质、Beer、TIR、透明阻断、光滑有界 split，并以等散射阶数（bound depth 2 / unbound depth 3）比较高 spp 均值与三 seed 低 spp MSE；
9. 技术报告 pytest 逐字核对标记过的源码片段，并检查章节结构、导航、链接和若干关键语义；PhysX host 测试用 typed `PhysicsWorld`/`PhysicsResult`、合成结果和定向 mutation 覆盖协议版本、GPU-only 身份、body 顺序、附件交接与封面 validator，但不假装执行 subprocess worker、真实刚体或像素渲染；
10. RTX 5090 的维护者 acceptance 构建 Release renderer，运行启用 OptiX validation 的 smoke、受控数学契约和八个静态低分辨率示例预览；可用 PhysX SDK 时，Kinetic Foundry 与封面还会即时求解低分辨率样本并检查契约和像素流程。4K 发布前仍人工检查爆发构图、水池、火/烟/神光代理及同次 sidecar。

唯一保留的像素 golden 是 mesh fixture 的 RTX 5090 基线；积分器对照的临时 PNG 和 stats 会自动清理，不保存哈希。mesh golden 只证明定向输出与已接受结果逐字节相同，不能独立证明物理正确；跨 GPU、编译器或 `--use_fast_math` 的少量浮点差异，也不自动等于数学回归。正式 gallery 与 stats 继续作为作品和一次运行记录保存，但不再是自动测试门禁；默认 acceptance 不设置性能阈值或 profiling 验收。可靠结论仍需要公式审查、定向场景和数值/视觉证据结合。

需要特别区分：这组 host-only 检查不编译 CUDA/OptiX 渲染器，不执行路径着色，也不输出参考像素。因此它们不是 CPU reference renderer，不能代替上述 GPU 对照或 golden。RR、MIS、delta NEE 与贡献钳位实现只位于设备路径；第 4、5 章负责公式与源码审查，数值性质由 clamp 0/0 的 GPU 对照验证。

## 7. 从一个像素重新串起全文

1. 在像素与镜头上取样，得到相机射线；
2. OptiX 遍历 IAS/GAS/BVH，内建或自定义 intersection 返回最近交点；交点分开保存 $\mathbf n_g$ 和面向当前 $\boldsymbol\omega_o$ 的 $\mathbf n_s^{\mathrm{eff}}$，解析水面在 tile AABB 内求高度场根；
3. 支持 NEE 的表面对有限灯和 HDR 环境分别取样，并逐盏连接 point/directional：普通有限灯按顶点选择全局或均匀 PMF，粗糙 water 则从全局与均匀索引各取一份确定性样本；$\mathbf n_g$ 决定 Lambert/metal/PBR 的真实正半球和粗糙介电的反射/透射侧；透射在栈副本中切换一次并乘 Beer，任何后续透明边界都由二值 shadow 阻断；flame 再沿连接段估计吸收；
4. BSDF 选择下一方向，吞吐量乘 `scatter.weight`；连续事件对应 $f_s|\mathbf n_s^{\mathrm{eff}}\!\cdot\boldsymbol\omega_i|/p_B$，粗糙介电 PDF 含实际反射/透射分支概率与透射 Jacobian，粗糙水面至少把一半 BSDF 样本分配给反射；光滑 delta dielectric/water 改用 $\mathbf n_g$ 求 Fresnel/Snell 方向；含水路径用介质栈决定两侧 IOR 并在传播段累计 Beer；首个光滑水面改为一次确定性、至多两状态的 Fresnel split；
5. 普通面积灯 NEE 与命中灯面、环境 NEE 与 BSDF miss 分别用 power heuristic MIS 分权；粗糙 water 的两份有限灯样本和 BSDF-hit 用三技术 balance；point/directional 的 delta NEE 权重为 1；flame 保留互斥体积估计器；
6. 路径在 miss、emitter、无效散射、轮盘或最大深度处结束；最大深度的最后一个表面事件仍先完整估计有限灯与环境域，粗糙 water 的有限灯域包含两份样本；
7. 每份完成 throughput、可见性、介质与 MIS 的 RGB 贡献按 direct/indirect 阈值独立钳位；0 表示关闭。多条路径的线性 RGB 平均成为 HDR beauty；
8. 钳位后、降噪前的线性样本均值可选写 PFM；展示分支可选降噪后，再执行曝光、ACES 风格拟合、sRGB 编码和 8 bit 量化。程序化 flame 的吸收—自发光见第 10 章，解析水面的求交与介电传输见第 11 章。

渲染器真正的核心正是这条链：**渲染方程给出目标，Monte Carlo 构造估计，几何与材质定义路径，OptiX/GPU 把大量路径高效执行。**

## 8. 进一步阅读

- James T. Kajiya, *The Rendering Equation*（1986）。
- Eric Veach, *Robust Monte Carlo Methods for Light Transport Simulation*（1997）。
- Bruce Walter 等，*Microfacet Models for Refraction through Rough Surfaces*（2007）。
- Matt Pharr、Wenzel Jakob、Greg Humphreys，*Physically Based Rendering*。

[上一章：PhysX 刚体模拟与即时场景构建](12-physx-rigid-body-scene-baking.md) · [返回目录](README.md)
