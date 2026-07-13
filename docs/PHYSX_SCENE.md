# Kinetic Foundry：PhysX 场景生成与复现

Kinetic Foundry 是一个按需生成的静态 gallery 场景。PhysX 5.8.0 只负责
GPU 刚体模拟，并在固定第 300 步（2.5 秒）烘焙撞击峰值的瞬时姿态；
SpectralDock 随后读取普通 schema v2 JSON，以 CUDA/OptiX 完成路径追踪。
渲染器本身不链接 PhysX，也不提供运行时物理、交互或动画。

## 发行边界

- 六个内置 `scenes/*.json` 和默认 `render-examples.sh` 批处理保持独立；PhysX 仍只生成 Kinetic Foundry。
- 生成器把临时场景和 metadata 写入被忽略的
  `scenes/generated/kinetic-foundry.json` 与
  `scenes/generated/kinetic-foundry.physics.json`。
- 仓库不提交临时场景 JSON，只提交正式
  `docs/gallery/kinetic-foundry.png`、同 stem 的渲染 `.stats.json` 和
  从同次生成保留的 `.physics.json`。
- PhysX 源码、SDK、库、二进制和专用容器镜像均不进入源码仓库或
  GitHub Release。

## 固定生成环境

`Dockerfile.physx` 使用 CUDA 12.8.1 开发镜像，在构建镜像时从
NVIDIA 官方仓库获取 PhysX，并固定到：

- repository: `https://github.com/NVIDIA-Omniverse/PhysX`
- tag: `110.0-omni-and-physx-5.8.0`
- commit: `fc1018a3745664a1db2b95ce03fb5e91eb585f2e`
- license: BSD-3-Clause

默认构建不会查找 PhysX。专用镜像在容器内提供 checked 版
`/opt/physx`，无需在宿主机设置 `PHYSX_ROOT`；渲染步骤仍要求用户自行
取得 OptiX 9.1，并以 `OPTIX_ROOT` 只读挂载。

## 生成、检查与渲染

首次使用先构建专用镜像：

```bash
./scripts/build-physx-image.sh
```

生成器 target 为 `spectraldock_physx_scene`，源码是
`tools/generate_physx_kinetic_foundry.cpp`；CMake 仅在显式设置
`SPECTRALDOCK_ENABLE_PHYSX_SCENE=ON` 时构建它。默认 CUDA device 为 `0`，
seed 为 `20260711`。维护者脚本支持 `--output`、`--metadata`、`--device`、
`--seed` 和 `--verify`：

```bash
./scripts/generate-physx-scene.sh --verify

python3 tools/check_physx_scene.py \
  scenes/generated/kinetic-foundry.json \
  scenes/generated/kinetic-foundry.physics.json
```

`--verify` 在同一固定容器镜像和设备上生成两次，分别逐字节比较 scene
JSON 和 metadata sidecar，再运行验证器。sidecar 记录 PhysX GPU backend、
设备、seed、`dt=1/120`、`steps=300`、重力、scene flags、actor 计数和结果
摘要。正式 sidecar 还必须记录 `sleeping_dynamic_actors=0`，证明截帧时没有
动态 actor 进入 PhysX sleeping 状态。

普通预览写入被忽略的 `output/examples/`：

```bash
OPTIX_ROOT="/absolute/path/to/OptiX-SDK-9.1.0" \
  ./scripts/render-physx-scene.sh --preset preview
```

只有维护者在完成验收后才运行 final；它显式替换受版本控制的同名 PNG、
渲染 stats 和物理 metadata 三件套，不增加 gallery stem 或资产数量，且仍
不提交临时场景 JSON：

```bash
OPTIX_ROOT="/absolute/path/to/OptiX-SDK-9.1.0" \
  ./scripts/render-physx-scene.sh --preset final
```

## 确定性边界与验收

PhysX GPU 模式不支持 enhanced determinism；sidecar 必须记录
`enhanced_determinism=false` 和
`enhanced_determinism_unsupported_on_gpu`。本项目依靠固定 seed、固定
时间步与撞击峰值步数、固定 actor 创建/导出顺序，以及同一测试机、同一设备和
同一软件栈上的双生成逐字节比较来发现漂移。这不是跨 GPU、驱动、CUDA、
PhysX 版本、编译器或操作系统的确定性承诺。

正式更新前应完成：

1. 使用 `--verify` 生成，确认 scene 和 metadata 两组逐字节比较均通过。
2. 确认第 300 步（2.5 秒）、0 个 sleeping dynamic actors、24 个采用
   capsule 碰撞代理的 mascot、192 个钢珠 sphere、有限变换、落地区域、
   至少 12 个倾角超过 15° 的 toppled mascot 和 GPU-only flags 通过
   `check_physx_scene.py`。
3. 渲染 preview，人工检查撞击峰值构图，以及明显穿透、飞散、悬空、落出
   构图和材质错误；该作品是清晰的瞬时单帧，不使用 motion blur。
4. 在 RTX 5090 正式环境运行 final，逐项核对 PNG、stats 与 physics
   metadata，并确认 `scenes/generated/` 仍未被跟踪。

Kinetic Foundry PNG 属于 `assets/examples/models/CC0-1.0.txt` 明确列出的
CC0-1.0 视觉资产；生成器、验证器、渲染 stats 和 `.physics.json` 均按
Apache-2.0 提供。PhysX 保持其上游 BSD-3-Clause 许可。NVIDIA、CUDA、
OptiX、PhysX 和 RTX 是 NVIDIA Corporation 的商标或注册商标；
SpectralDock 是独立的非官方项目，与 NVIDIA Corporation 无隶属关系，
也未获得其赞助或背书。
