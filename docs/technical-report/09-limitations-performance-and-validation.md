# 09　边界、性能与验证

一张看起来合理的图不一定数学正确；一张带噪声的图也不一定错误。评估路径追踪器时，应先区分误差来自哪里，再讨论性能和测试。

## 1. 四类不同问题

| 类别 | 含义 | SpectralDock 中的例子 | 增加 spp 能否解决 |
|---|---|---|---|
| 随机方差 | 有限样本围绕目标波动 | 小灯、太阳瓣、尖锐高光的噪点 | 能缓解，约按 $1/\sqrt N$ |
| 数值偏差 | 算法求解了近似目标 | `max_depth` 截断长路径 | 不能 |
| 模型误差 | 数学模型省略现实机制 | RGB、无体积、无色散 | 不能 |
| 实现缺陷 | 代码没有实现既定公式 | PDF 漏掉选灯概率、方向写反 | 不能，必须修代码 |

降噪和色调映射属于另一层：**重建与显示变换**。它们可以改变观感，却不会增加积分器已经采集的路径信息。

## 2. 当前积分器的重要边界

### 光传输

- 只计算稳态表面光传输，没有雾、烟、参与介质、次表面散射或传播时间；
- 使用线性 RGB，不模拟波长、色散、衍射或偏振；
- `max_depth` 会截断最后一个已处理表面事件之后的继续路径；最后一个事件自身的显式直接光仍完整估计；
- 环境天空和太阳瓣没有显式重要性采样；
- 纹理 emitter 和 mesh emitter 不能进入 NEE 灯列表；
- 灯按数量而非功率均匀选择，球灯按整个球面而非可见立体角采样。

### 材质

- `metal` 是纯 GGX 镜面微表面瓣，$\mathbf F_0=\text{base_color}$，不是通用 metallic workflow；
- GGX 采样普通 NDF 而非 VNDF，掠射角方差可能较高；
- `dielectric` 是光滑 delta 界面，外部固定为空气，没有嵌套介质、粗糙折射或体吸收；
- 场景解析不强制被动材质的 `base_color ≤ 1`，能量合理性部分依赖输入；
- 阴影射线把介电质视为不透明遮挡物。

### 几何与颜色

- cylinder 没有端盖；`parabola` 是由 AABB 裁剪的抛物柱面；
- alpha 是二值 cutoff，不是连续透明或折射；
- 固定世界空间 `scene_epsilon` 不随场景尺度变化；
- 色调映射是逐通道 ACES 风格拟合曲线，不是完整 ACES；
- 8 bit PNG 不保存原始 HDR 缓冲区。
- sRGB 纹理先对编码码值做硬件双线性过滤，之后才解码到线性空间。

发光材质命中后立即终止路径，不会同时反射；背景也只是 y 向渐变加一个硬边太阳瓣，而非环境贴图或光度学天空。

这些是明确的设计边界。未来扩展时，应先判断新功能属于渲染方程、采样策略、几何查询还是显示变换。

## 3. 性能指标测量什么

[`RenderStats`](../../include/spectraldock/optix_renderer.h) 把一次渲染拆成几个指标。

### `timings_ms.bvh_build`

从开始上传/构建被引用 mesh 和每对象 primitive GAS，到 IAS 构建及满足条件时的压缩完成。它包含相关 mesh 设备上传、GAS/IAS 构建及紧凑尺寸更小时的压缩，不包含此前的纹理解码/上传和 pipeline 创建。

### `timings_ms.render`

只围绕一次 `optixLaunch` 的 CUDA event 时间，包含 raygen 路径循环、全部 radiance/shadow trace 和着色。基准表中的 **Path trace** 就是这个值。

### `timings_ms.denoise`

启用降噪时，围绕 denoiser setup、强度计算、invoke 与同步的 CUDA event 时间；关闭时为 0。

### `timings_ms.total`

在 `render_optix()` 完成 settings 与像素数检查后开始，到返回前记录。它包括 CUDA/OptiX 初始化、pipeline、纹理解码与上传、加速结构、SBT/缓冲区、路径追踪、可选降噪、后处理、RGBA/射线计数回传和设备信息查询。

它**不包括**调用前的 JSON/OBJ 解析，也不包括调用后的 PNG 与 stats JSON 写盘；时间戳还早于函数局部 RAII 资源析构。因此 Total 不是完整 CLI 进程墙钟时间，也不等于前三个分项简单相加。BVH 与 denoise 分项由同一 CUDA stream 上的 event 包围；区间可能包含主机尚未提交下一项工作时的 stream idle，不应解读成逐 kernel 时间之和。

## 4. 射线吞吐量怎样理解

每像素记录实际调用 `optixTrace` 的次数，包括 radiance 和 shadow ray：

$$
\text{rays/s}=
\frac{\text{traced rays}}
{\text{render\_ms}\times10^{-3}}.
$$

它不是纯 BVH microbenchmark：材质计算、随机数、分支、纹理和路径循环都在同一个 launch 内。不同场景的 rays/s 差异不应简单解释为硬件快慢。

`traced_rays` 也不等于 $W\times H\times spp\times max\_depth$：路径可提前终止，普通表面还可能额外发一条 shadow ray。

## 5. 显存指标

- `peak_tracked_device_bytes`：项目 RAII 分配器直接记账的峰值；
- `peak_device_bytes`：在 CUDA context 与 stream 已建立后的 baseline 上，通过若干次 `cudaMemGetInfo` 采样观察到的增量峰值。它可包含随后出现的 OptiX 内部分配，可能受同 GPU 其他进程影响，也可能漏掉两个采样点之间的短峰值。

二者回答不同问题，不能把差值直接称为泄漏。正式 RTX 5090 数据见[基准与分析](../BENCHMARK.md)，gallery 中每张正式 PNG 旁也有对应的 stats JSON。

## 6. 测试为什么存在

测试不是渲染器的核心功能，而是按层保存其行为证据：

1. CPU 单元测试检查向量、场景解析、OBJ、输入语义，以及 MIS 互补性、RR 补偿和末端策略权重；
2. parser fixtures 覆盖 primitive、灯、UV、alpha、实例与共享 GAS 的输入组合，但不执行 GPU 着色；
3. 无 golden 的积分器 GPU 对照以 64×64、4 spp、depth 1、seed 1 渲染绑定/未绑定同一灯的两版 smoke 场景，要求解码 RGBA 逐字节相同且非空；
4. 综合 mesh GPU fixture 定向覆盖共享 GAS、实例变换、UV、平滑法线、alpha 和 custom primitives；
5. Compute Sanitizer 查找越界、竞争和未初始化数据；
6. 素材与复现工具测试保护纹理接缝、确定性场景/模型生成、几何闭合性和资产哈希。

唯一保留的像素 golden 是 mesh fixture 的 RTX 5090 基线；积分器对照的临时 PNG 和 stats 会自动清理，不保存哈希。mesh golden 只证明定向输出与已接受结果逐字节相同，不能独立证明物理正确；跨 GPU、编译器或 `--use_fast_math` 的少量浮点差异，也不自动等于数学回归。正式 gallery 与 stats 继续作为作品和一次运行记录保存，但不再是自动测试门禁；项目也不设置自动性能阈值或 profiling 验收。可靠结论仍需要公式审查、定向场景和数值/视觉证据结合。

## 7. 从一个像素重新串起全文

1. 在像素与镜头上取样，得到相机射线；
2. OptiX 遍历 IAS/GAS/BVH，返回最近交点、法线、UV 和材质；
3. 普通表面用 NEE 连接面积灯，以 shadow ray 判断可见性；
4. BSDF 选择下一方向，吞吐量乘 `scatter.weight`；连续事件对应 $f_s|\mathbf n\cdot\boldsymbol\omega_i|/p_B$，介电 delta 分支按离散事件处理；
5. NEE 与命中灯面的估计用 power heuristic MIS 分权；
6. 路径在 miss、emitter、无效散射、轮盘或最大深度处结束；最大深度的最后一个表面事件仍先完整估计直接光；
7. 多条路径的线性 RGB 平均成为 HDR beauty；
8. 可选降噪后，执行曝光、ACES 风格拟合、sRGB 编码和 8 bit 量化。

渲染器真正的核心正是这条链：**渲染方程给出目标，Monte Carlo 构造估计，几何与材质定义路径，OptiX/GPU 把大量路径高效执行。**

## 8. 进一步阅读

- James T. Kajiya, *The Rendering Equation*（1986）。
- Eric Veach, *Robust Monte Carlo Methods for Light Transport Simulation*（1997）。
- Bruce Walter 等，*Microfacet Models for Refraction through Rough Surfaces*（2007）。
- Matt Pharr、Wenzel Jakob、Greg Humphreys，*Physically Based Rendering*。

[上一章：降噪、色调映射与输出](08-denoising-color-and-output.md) · [返回目录](README.md)
