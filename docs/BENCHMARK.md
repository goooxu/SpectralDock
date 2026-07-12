# RTX 5090 基准与分析

测试环境：NVIDIA GeForce RTX 5090（CC 12.0），driver 610.47.04，CUDA Driver API/runtime 13030，OptiX 90100。正式图均在 RR/MIS 修复后以 1920×1080、512 spp、depth 12 和 AI denoise 重新渲染。数据来自仓库中的 `docs/gallery/*.stats.json`。

## 正式渲染

| 场景 | BVH build (ms) | Path trace (ms) | Denoise (ms) | Total (ms) | Traced rays | G rays/s | Observed peak (MiB) | Tracked peak (MiB) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| material-cathedral | 3.054 | 1,096.225 | 15.483 | 1,877.056 | 5,830,761,817 | 5.319 | 1,308.3 | 483.8 |
| neon-koi | 3.156 | 836.061 | 14.199 | 1,574.567 | 4,899,441,181 | 5.860 | 1,320.3 | 495.7 |
| celestial-archive | 2.679 | 606.931 | 14.530 | 1,345.682 | 3,143,769,772 | 5.180 | 1,324.3 | 495.7 |
| reflector-laboratory | 2.655 | 782.546 | 14.367 | 1,472.562 | 2,762,368,581 | 3.530 | 1,308.3 | 483.7 |
| benchmark-harbor | 169.622 | 228.853 | 15.533 | 1,087.870 | 1,614,680,505 | 7.056 | 1,310.3 | 485.4 |

`Path trace` 对应统计 JSON 的 `timings_ms.render`，只计一次 `optixLaunch`。`Total` 在 `render_optix()` 完成参数与像素数检查后开始，到返回前结束，包含 CUDA/OptiX 初始化、纹理解码与上传、BVH、追踪、可选降噪、后处理、设备到主机回传和设备信息查询；不含此前的场景/OBJ 解析、之后的 PNG/stats 写盘及函数局部 RAII 资源析构，因此不等于前三项简单相加。显存按 1 MiB = 1,048,576 bytes 换算。

## 几何工作量

| 场景 | Objects | Instances | Unique meshes | Unique mesh triangles | GAS |
| --- | ---: | ---: | ---: | ---: | ---: |
| material-cathedral | 15 | 15 | 1 | 5,816 | 13 |
| neon-koi | 9 | 9 | 1 | 5,816 | 9 |
| celestial-archive | 9 | 9 | 1 | 5,816 | 9 |
| reflector-laboratory | 10 | 10 | 1 | 5,816 | 10 |
| benchmark-harbor | 1,040 | 1,040 | 1 | 5,816 | 1,025 |

Harbor 的 16 个胶囊吉祥物共享一份 mascot GAS，另有 1,024 个 sphere GAS；`mesh_triangles` 不按实例数重复计数。

## 按需 Kinetic Foundry（PhysX）

Kinetic Foundry 不属于上表五个内置场景，且生成/渲染环境与上表不是同一次运行，
因此单独记录。物理阶段使用 CUDA 12.8.1 专用镜像、PhysX 5.8.0 checked
配置和固定 commit `fc1018a3745664a1db2b95ce03fb5e91eb585f2e`，在 RTX 5090
上以 GPU dynamics、GPU broadphase、PCM、stabilization、seed `20260711`、
`1/120 s` 固定步长运行 300 步，在 2.5 秒的撞击峰值截帧。此时 sidecar
记录 0 个 sleeping dynamic actors。PhysX GPU 不支持 enhanced determinism；
同机双生成逐字节一致不构成跨 GPU 或软件栈保证。

该清晰的瞬时静态快照随后由 CUDA 13.3、OptiX 9.1、driver 615.36 在同一
RTX 5090 上以 1920×1080、512 spp、depth 12 和 AI denoise 渲染；场景不含
motion blur：

| BVH build (ms) | Path trace (ms) | Denoise (ms) | Total (ms) | Traced rays | G rays/s | Observed peak (MiB) | Tracked peak (MiB) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 30.204 | 507.553 | 13.136 | 1,290.944 | 2,716,886,066 | 5.353 | 1,320.3 | 494.6 |

该场景包含 24 个共享同一 mascot GAS 的 mesh 实例、192 个钢珠 sphere 和
4 个可见静态 rectangle，共 220 个 objects/instances、1 个 unique mesh、
5,816 个 unique mesh triangles 和 197 个 GAS。仓库提交 PNG、渲染 stats 与
PhysX sidecar，不提交 `scenes/generated/kinetic-foundry.json`。完整生成契约见
[PHYSX_SCENE.md](PHYSX_SCENE.md)。

## 定向 GPU fixture

综合 GPU fixture 使用 64×64、1 spp、depth 6、seed 1 和无降噪输出，覆盖带 UV/平滑法线/alpha 的 mesh、两个共享 GAS 且使用不同变换/材质的实例，以及 custom primitives。其 RTX 5090 SHA-256 为 `2ae722c6634d88de7f2ad56e790ebf54a9d7fe395eb8063e13be236a74ce6fd2`，由 `scripts/sanitizers.sh` 在三类检查后验证。

积分器对照使用 smoke 场景的临时绑定/未绑定灯副本，以 64×64、4 spp、depth 1、seed 1 和无降噪渲染；两版解码 RGBA 必须逐字节相同且非空。该测试由 `acceptance.sh` 在 Release 构建后运行，临时 PNG/stats 自动清理，不建立 golden。

正式 PNG、stats 和本页耗时表作为作品展示与一次运行记录保留，不属于自动 golden、画廊或性能回归门禁。

## 复现

```bash
BUILD_TYPE=Release ./scripts/render-examples.sh --preset final
BUILD_TYPE=Debug ./scripts/sanitizers.sh

# 独立的按需 PhysX 场景；会更新 kinetic-foundry 三件 gallery 记录
./scripts/build-physx-image.sh
OPTIX_ROOT="/absolute/path/to/OptiX-SDK-9.1.0" \
  ./scripts/render-physx-scene.sh --preset final
```
