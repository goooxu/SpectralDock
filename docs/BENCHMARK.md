# RTX 5090 单机运行记录

以下数据是同一台 NVIDIA GeForce RTX 5090（CC 12.0）上的可复查运行记录，不是跨 GPU 基准，也不用于给出性能承诺。全部场景使用 driver 615.36、CUDA Driver API 13040、CUDA runtime 13030、OptiX 90100、`importance` 直接光采样，以及各 Python 程序明确设置的 direct 64 / indirect 16 有偏贡献钳位。除 Ember Forge 外，七个静态程序以 1920×1080、512 spp、depth 12 和 AI denoise 渲染；Ember Forge 固定为 2048 spp、depth 12、无降噪。由于场景、采样数和算法工作量不同，各行适合解释阶段耗时、显存与计数器，不构成受控的横向性能比较。原始数据来自 `docs/gallery/*.stats.json`。

为保留运行 provenance，gallery 的 stats 与 PhysX sidecar 按正式图片验收时的内容原样保存；其中 `scene` 字段可能仍记录已经移除的旧 JSON 路径，两份物理 sidecar 也采用当时的聚合格式。它们只和同 stem 的正式 PNG 组成历史运行记录，不是当前可执行输入。直接运行现有 Python 程序会写输出 stem 和当前 `spectraldock.physics/1` 明细，不能用新字段静默覆盖旧记录。

展示图允许贡献钳位以控制 firefly；所有下文涉及收敛均值、MSE、能量比例或采样器无偏性的 fixture 都在 Python `render()` 中显式传 `clamp_direct=0, clamp_indirect=0`。PFM 位于钳位之后，因此仅关闭 Denoiser 不足以得到无偏参考。

## 内置场景记录

| 场景 | BVH build (ms) | Path trace (ms) | Denoise (ms) | Total (ms) | Traced rays | G rays/s | Observed peak (MiB) | Tracked peak (MiB) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| material-cathedral | 3.278 | 3,840.720 | 11.790 | 10,068.360 | 5,696,463,300 | 1.483 | 1,774.3 | 494.3 |
| neon-koi | 2.856 | 3,114.284 | 11.513 | 9,317.566 | 4,844,789,609 | 1.556 | 1,786.3 | 506.3 |
| celestial-archive | 2.744 | 2,115.082 | 11.435 | 8,239.103 | 3,368,104,545 | 1.592 | 1,790.3 | 506.3 |
| reflector-laboratory | 2.769 | 3,241.696 | 11.627 | 9,354.175 | 4,471,049,788 | 1.379 | 1,774.3 | 494.3 |
| benchmark-harbor | 160.853 | 752.120 | 11.835 | 7,028.149 | 1,584,200,149 | 2.106 | 1,776.3 | 496.2 |
| ember-forge | 12.265 | 29,789.141 | 0.000 | 35,893.152 | 23,740,617,759 | 0.797 | 1,468.3 | 190.6 |
| moonlit-stepwell | 6.722 | 6,628.836 | 11.920 | 12,742.227 | 4,250,011,154 | 0.641 | 1,902.3 | 621.0 |
| radiance-pavilion | 5.871 | 1,561.085 | 10.864 | 7,822.482 | 2,409,807,029 | 1.544 | 1,816.3 | 534.4 |

`Path trace` 对应统计 JSON 的 `timings_ms.render`，只计一次 `optixLaunch`。`Total` 在 `render_optix()` 完成参数与像素数检查后开始，到返回前结束，包含 CUDA/OptiX 初始化、纹理解码与上传、BVH、追踪、可选降噪、后处理、设备到主机回传和设备信息查询；不含此前的 Python SceneBuilder 构造与 OBJ 解析、之后的 PNG/stats 写盘及函数局部 RAII 资源析构，因此不等于前三项简单相加。显存按 1 MiB = 1,048,576 bytes 换算。

## 几何工作量

| 场景 | Objects | Instances | Unique meshes | Unique mesh triangles | GAS |
| --- | ---: | ---: | ---: | ---: | ---: |
| material-cathedral | 15 | 15 | 1 | 5,816 | 13 |
| neon-koi | 9 | 9 | 1 | 5,816 | 9 |
| celestial-archive | 9 | 9 | 1 | 5,816 | 9 |
| reflector-laboratory | 10 | 10 | 1 | 5,816 | 10 |
| benchmark-harbor | 1,040 | 1,040 | 1 | 5,816 | 1,025 |
| ember-forge | 87 | 87 | 1 | 5,816 | 87 |
| moonlit-stepwell | 36 | 36 | 1 | 5,816 | 36 |
| radiance-pavilion | 37 | 37 | 1 | 5,816 | 37 |

Harbor 的 16 个胶囊吉祥物共享一份 mascot GAS，另有 1,024 个 sphere GAS；`mesh_triangles` 不按实例数重复计数。
Ember Forge 的三段 flame 不注册为几何，因此不增加 object、instance、GAS 或 SBT 数量；87 个几何对象来自砖砌锻炉、烟罩、铁砧、胶囊铁匠与锤子、工具墙、风箱、淬火桶、钢材和工坊结构。其密度求值、真实碰撞和体积选灯次数由独立 volume stats 记录。当前正式 stats 记录 27,243,478,786 次密度求值、728,682,772 次真实体积碰撞和 15,403,178,792 次 flame NEE 选灯；majorant violation 与 tracking overflow 均为 0。场景使用纯黑 constant background，不含 emitter、面积灯或隐藏补光，全部可见照明只来自三段 flame。体积求值是 raygen 中的纯 CUDA 工作，不计入 `traced_rays`，所以该场景的 rays/s 不应与纯表面场景直接比较。

Moonlit Stepwell 的 water_surface 注册为一个共享波面参数的 custom-primitive GAS；最短波长决定 tile 数和 GAS primitive 数，但不把解析曲面三角化。当前正式 stats 记录 13,239,801,692 次 height evaluation、1,709,683,496 次 tile test、277,840,586 个 reported root、253,017,452 个 medium segment、398,730,722 次粗糙水面 NEE 尝试和 233,784,483 份非零直接光贡献；delta split、solver overflow 与 medium error 均为 0。它在每个粗糙水面顶点各取一个功率选灯样本和均匀索引样本，并与 BSDF emitter-hit 使用三技术 balance；所有球外连续 BSDF 顶点对单面 sphere 灯按可见立体角取样。其路径追踪耗时和 rays/s 因包含 OptiX 自定义 intersection 中的 CUDA 数值求根、额外 shadow connection、介质栈与 Beer 计算，不应直接与纯表面场景比较。正式 PNG 启用 Denoiser 与贡献钳位；下面的线性误差对照显式关闭降噪和两级钳位。

维护级 Moonlit time-to-error 在 320×180 上使用一份独立 seed 的 8192 spp 粗糙 NEE PFM 作为参考，并对三个候选 seed 求平均；候选为 NEE 1024 spp，以及仅删除显式灯绑定、保留 emitter 几何的 BSDF-only 2048 spp。该维护对照不写入 gallery stats，当前提交的 `docs/gallery/*.stats.json` 因此不能为它提供同次时间或 MSE。本页不沿用历史数值；需要发布新结论时必须重新运行维护脚本，并把独立原始记录与运行环境一起保存。

Radiance Pavilion 不放置有限面积灯或 emissive 几何，唯一照明来自 2048×1024 Radiance RGBE 日落海岸环境贴图。中央 mascot 与陶土风向标、青铜日晷、铬制抛物面日光镜和玻璃双透镜观测仪这四件户外观测装置同时展示漫反射、粗糙金属、光滑金属和介电材质，用于观察环境亮区的重要性采样、镜面反射与折射；HDR 纹理和两级 CDF 的设备内存计入显存统计。

## 即时 Kinetic Foundry（PhysX）

Kinetic Foundry 是按需求解的 PhysX 程序，不属于上表八个静态程序，因此单独记录。物理 worker 使用 CUDA 12.8.1 与 PhysX 5.8.0 checked
配置和固定 commit `fc1018a3745664a1db2b95ce03fb5e91eb585f2e`，在 RTX 5090
上以 GPU dynamics、GPU broadphase、PCM、stabilization、seed `20260711`、
`1/120 s` 固定步长运行 300 步，在 2.5 秒的撞击峰值截帧。此时 sidecar
记录 0 个 sleeping dynamic actors。PhysX GPU 不支持 enhanced determinism；
固定 seed 和固定步长仍可能因 GPU 接触与求解顺序产生不同最终姿态，因此
项目不要求同机或跨 GPU、软件栈逐字节一致。

该清晰的瞬时静态快照随后由 CUDA 13.3、OptiX 9.1、driver 615.36 在同一
RTX 5090 上以 1920×1080、512 spp、depth 12 和 AI denoise 渲染；场景不含
motion blur：

| BVH build (ms) | Path trace (ms) | Denoise (ms) | Total (ms) | Traced rays | G rays/s | Observed peak (MiB) | Tracked peak (MiB) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 32.007 | 1,751.006 | 11.212 | 7,992.055 | 2,867,770,420 | 1.638 | 1,774.3 | 494.7 |

该场景包含 24 个共享同一 mascot GAS 的 mesh 实例、192 个钢珠 sphere 和
4 个可见静态 rectangle，共 220 个 objects/instances、1 个 unique mesh、
5,816 个 unique mesh triangles 和 197 个 GAS。仓库提交 PNG、渲染 stats 与
PhysX sidecar；Python API 直接把内存中的 actor 姿态应用到 renderer，不生成场景 JSON。完整执行契约见
[PHYSX_SCENE.md](PHYSX_SCENE.md)。

## 4K 封面：Lava Temple Oracle（PhysX）

“熔岩圣殿的机械先知”是第二个即时物理场景，也是独立于上表八个静态场景
的 4K 封面记录。直接执行 Python 程序时，它先在同一 RTX 5090 上启动 PhysX 5.8.0 checked
GPU worker，以 seed 909、`1/120 s` 固定步长运行 24 步，在 0.2 秒的径向
爆发瞬间返回 130 个 actor；契约要求 GPU dynamics/broadphase、TGS、PCM、
stabilization、无 CPU fallback 与 0 个 sleeping actors。随后由 CUDA 13.3、
OptiX 9.1 以 3840×2160、2048 spp、depth 12、AI Denoiser、direct clamp 64
和 indirect clamp 16 渲染。

封面只使用解析 primitive，不读取 mesh 或纹理。动态部分为 24 块外壳板、
2 块面罩、2 只眼、4 个肢体、3 个天线部件、6 个复合齿轮、29 个机械件、
12 块顶石和 48 颗火星；静态圣殿另包含有限解析水面、三段火焰、两段烟代理、
一段低发光神光代理、沿神光轴的 30 颗不发光 dust sphere、一盏 directional
与四盏 point。第 5 个 PhysX 复合齿轮携带一个可见
`oracle_core_emitter` sphere；它与火星不注册为显式灯。场景契约把解析
object 数限制在不超过 450，但这只是预算上限。水和体积的 CUDA 工作不会
全部体现在 `traced_rays`，因此其 rays/s 不能与纯表面场景直接比较。

| BVH build (ms) | Path trace (ms) | Denoise (ms) | Total (ms) | Traced rays | G rays/s | Observed peak (MiB) | Tracked peak (MiB) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 66.214 | 743,705.188 | 22.633 | 750,371.025 | 294,345,540,582 | 0.396 | 4,052.3 | 2,764.7 |

同次 stats 记录 450 个 objects/instances、0 个 mesh/triangle 和 450 个 GAS。
体积路径完成 312,207,027,302 次密度求值、5,966,434,375 次真实碰撞和
57,557,356,560 次体积选灯；majorant violation 与 tracking overflow 均为 0。
水面路径完成 308,648,046,113 次 height evaluation、37,936,343,787 次 tile
test、7,482,772,769 个 reported root、2,446,684,411 个 medium segment、
16,658,170,907 次粗糙水面 NEE 尝试和 4,816,810,187 份非零贡献；solver
overflow、medium error 与 delta split 均为 0。展示钳位触发 30,504,182 次
direct contribution 和 1,360,014 次 indirect contribution。

同次 physics sidecar 记录 130 个 moving、130 个达到最小径向位移、130 个
rotating、四个水平象限全部占用、0 个 sleeping dynamic actors，且
`cpu_fallback=false`。该 PNG、stats 和 physics sidecar 是一次通过契约、
Compute Sanitizer memcheck 与人工构图检查的运行记录，不是跨 GPU 物理姿态 golden
或性能门槛。

当前 acceptance 对封面使用一次显式 `--target-processes all` memcheck，同时
检查 CUDA 13.3 OptiX 根进程和它启动的 CUDA 12.8 PhysX worker。PhysX 5.8
内部容量缓冲复制会产生上游 initcheck 诊断，所以项目不宣称对 worker 运行
initcheck 或 racecheck；GPU-only 身份、双运行 validator 和独立渲染帧仍负责
物理结果契约，但它们不能替代内存安全检查。

## 定向 GPU fixture

综合 GPU fixture 使用 64×64、1 spp、depth 6、seed 1 和无降噪输出，覆盖带 UV/平滑法线/alpha 的 mesh、两个共享 GAS 且使用不同变换/材质的实例，以及 custom primitives。其 RTX 5090 SHA-256 为 `8218a4c77997e6c581a846b32a75f15e78238c344ae5a8b9f3d6090e5b4ed990`；`acceptance.sh` 在 Release smoke 后立即调用 `check_mesh_smoke.py` 验证它，随后才进入独立的 Debug Compute Sanitizer 检查。

积分器兼容性对照使用 smoke 场景的临时绑定/未绑定灯副本，以 64×64、4 spp、depth 1、seed 1 和无降噪渲染；两版解码 RGBA 必须逐字节相同且非空。该测试由 `acceptance.sh` 在 Release 构建后运行，临时 PNG/stats 自动清理，不建立 golden。

HDR 环境 fixture 检查 RGBE 加载、固定 seed 确定性、强度缩放、yaw 旋转、`uniform`/`importance` 均值收敛，以及低样本 MSE 改善。有限灯 fixture 分别覆盖 rectangle、disk、sphere 与 flame，检查功率加权采样的固定 seed 确定性、均值无偏性、低样本 MSE，并通过两个绑定 emitter 的不等功率案例验证 NEE 与 BSDF-hit MIS 使用同一选择概率 $q_i$。sphere 对照还验证从所有连续 BSDF 球外顶点采可见立体角。delta 灯 fixture 独立检查 point 的逆平方衰减、directional 的距离不变性、背面、遮挡、水中 Beer 衰减、粗糙介电反射/透射、逐灯确定性和最多 32 盏限制。它们都以 clamp 0/0 运行，不建立跨 GPU 像素 golden。

firefly fixture 分别触发 direct 与 indirect 长尾贡献，检查默认 64/16、Python API 覆盖、最大 RGB 通道保色相缩放、两类原子计数器，以及 0/0 时输出与原有随机序列不变。钳位是明确的有偏展示策略，因此其降噪效果不参与无偏采样器的收敛均值判定。

flame fixture 额外检查固定 seed RGBA 确定性、外部漫反射面的体积 NEE、表面遮挡、面积光穿过体积后的吸收、介电 delta 路径以及 volume counters；同一 fixture 进入三种 Compute Sanitizer 检查：memcheck 覆盖 OptiX/CUDA 内存访问，带 `--check-optix` 的 initcheck 覆盖 OptiX launch 未初始化读取，racecheck 只覆盖普通 CUDA postprocess，不宣称检查 OptiX device program 的竞争。它不建立跨 GPU 像素 golden，也不设置自动性能阈值。

water fixture 检查固定 seed、解析波面、粗糙/光滑反射与折射、GGX 介电两侧语义、三技术 NEE/MIS、可见球锥、delta 灯 NEE、深浅路径的 RGB Beer 吸收、浸没玻璃 sphere 的介质栈、透明边界阻断、不透明遮挡和 water counters；同一 fixture 进入三种 Compute Sanitizer 检查。tile seam 还在 Moonlit Stepwell 预览中人工检查；它不建立跨 GPU 像素 golden。耗时较高的同模型 time-to-error 脚本只供维护者手工运行，不进入默认 acceptance。

PNG、stats 和本页耗时表作为图形学实验的一次运行记录保留，不属于自动 golden 或性能回归门禁。

## 复现

```bash
./scripts/configure.sh Release
./scripts/build.sh Release
source ./scripts/activate.sh Release

# 每个程序的 render() 已写明正式参数；两个 PhysX 程序每次都会重新求解
python3 scenes/kinetic-foundry.py
python3 scenes/lava-temple-oracle.py
./scripts/render-examples.sh

# 完整回归会自行构建 Release、Debug 与 PhysX worker，再运行 sanitizer
./scripts/acceptance.sh
```
