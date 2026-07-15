# RTX 5090 单机运行记录

以下数据是同一台 NVIDIA GeForce RTX 5090（CC 12.0）上的可复查运行记录，不是跨 GPU 基准，也不用于给出性能承诺。全部场景使用 driver 615.36、CUDA Driver API 13040、CUDA runtime 13030、OptiX 90100、`importance` 直接光采样，以及 schema v6 明确记录的 direct 64 / indirect 16 有偏贡献钳位。除 Ember Forge 外，七个内置场景以 1920×1080、512 spp、depth 12 和 AI denoise 渲染；Ember Forge 固定为 2048 spp、depth 12、无降噪。由于场景、采样数和算法工作量不同，各行适合解释阶段耗时、显存与计数器，不构成受控的横向性能比较。原始数据来自 `docs/gallery/*.stats.json`。

展示图允许贡献钳位以控制 firefly；所有下文涉及收敛均值、MSE、能量比例或采样器无偏性的 fixture 都显式传 `--clamp-direct 0 --clamp-indirect 0`。PFM 位于钳位之后，因此仅关闭 Denoiser 不足以得到无偏参考。

## 内置场景记录

| 场景 | BVH build (ms) | Path trace (ms) | Denoise (ms) | Total (ms) | Traced rays | G rays/s | Observed peak (MiB) | Tracked peak (MiB) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| material-cathedral | 4.343 | 1,584.514 | 13.046 | 5,478.862 | 5,689,199,443 | 3.591 | 1,774.3 | 494.3 |
| neon-koi | 4.269 | 1,415.758 | 12.307 | 5,273.090 | 4,843,501,621 | 3.421 | 1,786.3 | 506.3 |
| celestial-archive | 3.992 | 979.288 | 12.007 | 4,836.177 | 3,306,899,136 | 3.377 | 1,790.3 | 506.3 |
| reflector-laboratory | 3.595 | 848.571 | 13.380 | 4,649.451 | 2,858,115,041 | 3.368 | 1,774.3 | 494.3 |
| benchmark-harbor | 240.535 | 362.303 | 14.979 | 4,431.763 | 1,582,396,661 | 4.368 | 1,776.3 | 496.2 |
| ember-forge | 18.021 | 15,751.946 | 0.000 | 19,655.473 | 23,399,632,667 | 1.486 | 1,468.3 | 190.6 |
| moonlit-stepwell | 10.642 | 6,159.013 | 12.158 | 10,571.269 | 4,226,251,047 | 0.686 | 1,902.3 | 621.0 |
| radiance-pavilion | 8.307 | 762.571 | 12.128 | 4,737.143 | 2,407,120,944 | 3.157 | 1,816.3 | 534.4 |

`Path trace` 对应统计 JSON 的 `timings_ms.render`，只计一次 `optixLaunch`。`Total` 在 `render_optix()` 完成参数与像素数检查后开始，到返回前结束，包含 CUDA/OptiX 初始化、纹理解码与上传、BVH、追踪、可选降噪、后处理、设备到主机回传和设备信息查询；不含此前的场景/OBJ 解析、之后的 PNG/stats 写盘及函数局部 RAII 资源析构，因此不等于前三项简单相加。显存按 1 MiB = 1,048,576 bytes 换算。

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
Ember Forge 的三段 flame 不注册为几何，因此不增加 object、instance、GAS 或 SBT 数量；87 个几何对象来自砖砌锻炉、烟罩、铁砧、胶囊铁匠与锤子、工具墙、风箱、淬火桶、钢材和工坊结构。其密度求值、真实碰撞和体积选灯次数由独立 volume stats 记录。该场景的正式运行执行 26,880,900,322 次密度求值、719,613,737 次真实体积碰撞和 15,188,592,750 次 flame NEE 选灯；majorant violation 与 tracking overflow 均为 0。场景使用纯黑 constant background，不含 emitter、面积灯或隐藏补光，全部可见照明只来自三段 flame。体积求值是 raygen 中的纯 CUDA 工作，不计入 `traced_rays`，所以该场景的 rays/s 不应与纯表面场景直接比较。

Moonlit Stepwell 的 water_surface 注册为一个共享波面参数的 custom-primitive GAS；最短波长决定 tile 数和 GAS primitive 数，但不把解析曲面三角化。本次正式运行记录 13,179,520,982 次 height evaluation、1,704,266,814 次 tile test、276,339,417 个 reported root、238,141,315 个 medium segment、398,546,826 次粗糙水面 NEE 尝试和 233,686,645 份非零直接光贡献；delta split、solver overflow 与 medium error 均为 0。它在每个粗糙水面顶点各取一个功率选灯样本和均匀索引样本，并与 BSDF emitter-hit 使用三技术 balance；所有球外连续 BSDF 顶点对单面 sphere 灯按可见立体角取样。其路径追踪耗时和 rays/s 因包含 OptiX 自定义 intersection 中的 CUDA 数值求根、额外 shadow connection、介质栈与 Beer 计算，不应直接与纯表面场景比较。正式 PNG 启用 Denoiser 与贡献钳位；下面的线性误差对照显式关闭降噪和两级钳位。

维护级 Moonlit time-to-error 在 320×180 上使用一份独立 seed 的 8192 spp 粗糙 NEE PFM 作为参考，并对三个候选 seed 求平均。NEE 1024 spp 与仅删除显式灯绑定、保留 emitter 几何的 BSDF-only 2048 spp 平均 path-trace 时间分别为 2,444.827 ms 与 2,687.225 ms；反射 ROI 的归一化 MSE 分别为 0.00894643 与 0.00942178，水下 ROI 为 0.138436 与 0.200359。它说明本机同次运行中的 time-to-error 改善，不是跨 GPU 性能门槛。

Radiance Pavilion 不放置有限面积灯或 emissive 几何，唯一照明来自 2048×1024 Radiance RGBE 日落海岸环境贴图。中央 mascot 与陶土风向标、青铜日晷、铬制抛物面日光镜和玻璃双透镜观测仪这四件户外观测装置同时展示漫反射、粗糙金属、光滑金属和介电材质，用于观察环境亮区的重要性采样、镜面反射与折射；HDR 纹理和两级 CDF 的设备内存计入显存统计。

## 按需 Kinetic Foundry（PhysX）

Kinetic Foundry 是按需生成的 PhysX 场景，不属于上表八个内置场景，因此单独记录。物理阶段使用 CUDA 12.8.1 专用镜像、PhysX 5.8.0 checked
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
| 53.024 | 767.583 | 15.337 | 4,710.809 | 2,856,046,929 | 3.721 | 1,774.3 | 494.7 |

该场景包含 24 个共享同一 mascot GAS 的 mesh 实例、192 个钢珠 sphere 和
4 个可见静态 rectangle，共 220 个 objects/instances、1 个 unique mesh、
5,816 个 unique mesh triangles 和 197 个 GAS。仓库提交 PNG、渲染 stats 与
PhysX sidecar，不提交 `scenes/generated/kinetic-foundry.json`。完整生成契约见
[PHYSX_SCENE.md](PHYSX_SCENE.md)。

## 定向 GPU fixture

综合 GPU fixture 使用 64×64、1 spp、depth 6、seed 1 和无降噪输出，覆盖带 UV/平滑法线/alpha 的 mesh、两个共享 GAS 且使用不同变换/材质的实例，以及 custom primitives。其 RTX 5090 SHA-256 为 `2ae722c6634d88de7f2ad56e790ebf54a9d7fe395eb8063e13be236a74ce6fd2`，由 `scripts/sanitizers.sh` 在三类检查后验证。

积分器兼容性对照使用 smoke 场景的临时绑定/未绑定灯副本，以 64×64、4 spp、depth 1、seed 1 和无降噪渲染；两版解码 RGBA 必须逐字节相同且非空。该测试由 `acceptance.sh` 在 Release 构建后运行，临时 PNG/stats 自动清理，不建立 golden。

HDR 环境 fixture 检查 RGBE 加载、固定 seed 确定性、强度缩放、yaw 旋转、`uniform`/`importance` 均值收敛，以及低样本 MSE 改善。有限灯 fixture 分别覆盖 rectangle、disk、sphere 与 flame，检查功率加权采样的固定 seed 确定性、均值无偏性、低样本 MSE，并通过两个绑定 emitter 的不等功率案例验证 NEE 与 BSDF-hit MIS 使用同一选择概率 $q_i$。sphere 对照还验证从所有连续 BSDF 球外顶点采可见立体角。delta 灯 fixture 独立检查 point 的逆平方衰减、directional 的距离不变性、背面、遮挡、水中 Beer 衰减、粗糙介电反射/透射、逐灯确定性和最多 32 盏限制。它们都以 clamp 0/0 运行，不建立跨 GPU 像素 golden。

firefly fixture 分别触发 direct 与 indirect 长尾贡献，检查默认 64/16、CLI 覆盖、最大 RGB 通道保色相缩放、两类原子计数器，以及 0/0 时输出与原有随机序列不变。钳位是明确的有偏展示策略，因此其降噪效果不参与无偏采样器的收敛均值判定。

flame fixture 额外检查固定 seed RGBA 确定性、外部漫反射面的体积 NEE、表面遮挡、面积光穿过体积后的吸收、介电 delta 路径以及 volume counters；同一 fixture 进入三种 Compute Sanitizer 检查。它不建立跨 GPU 像素 golden，也不设置自动性能阈值。

water fixture 检查固定 seed、解析波面、粗糙/光滑反射与折射、GGX 介电两侧语义、三技术 NEE/MIS、可见球锥、delta 灯 NEE、深浅路径的 RGB Beer 吸收、浸没玻璃 sphere 的介质栈、透明边界阻断、不透明遮挡和 water counters；同一 fixture 进入三种 Compute Sanitizer 检查。tile seam 还在 Moonlit Stepwell 预览中人工检查；它不建立跨 GPU 像素 golden。耗时较高的同模型 time-to-error 脚本只供维护者手工运行，不进入默认 acceptance。

PNG、stats 和本页耗时表作为图形学实验的一次运行记录保留，不属于自动 golden 或性能回归门禁。

## 复现

```bash
BUILD_TYPE=Release ./scripts/render-examples.sh --preset final
BUILD_TYPE=Debug ./scripts/sanitizers.sh

# 独立的按需 PhysX 场景；会更新 kinetic-foundry 三件 gallery 记录
./scripts/build-physx-image.sh
OPTIX_ROOT="/absolute/path/to/OptiX-SDK-9.1.0" \
  ./scripts/render-physx-scene.sh --preset final
```
