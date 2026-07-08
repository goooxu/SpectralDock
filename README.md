# SpectralDock

SpectralDock 是面向 NVIDIA RTX GPU 的确定性离线路径追踪参考项目。它使用 CUDA 与 OptiX 完成硬件光线遍历，在一个可审查的 C++/CUDA 代码库中实现自定义几何、OBJ 实例、GGX/Fresnel、Next Event Estimation、MIS、透明 any-hit、景深和可选 AI 降噪。

![Neon Koi：透明 any-hit、纹理、彩色面积光与共享网格](docs/gallery/neon-koi.png)

当前首发定位为中文参考项目 v0.1。仓库收录运行所需的五个场景、模型、纹理及 gallery 成品，但不分发 CUDA、OptiX 或其他外部 SDK。

## 功能摘要

- schema v1/v2 场景加载，包含 sphere、triangle、rectangle、disk、cylinder、parabola 与 OBJ mesh。
- 网格资源共享压缩 GAS；每个实例拥有独立变换、正反面材质、纹理和 alpha。
- Lambert、GGX metal、光滑 dielectric 与 emitter，配合直接光采样、MIS 和俄罗斯轮盘。
- 固定 seed 的确定性渲染、PNG 输出和同名 `*.stats.json` 运行记录。
- 五个 1920×1080 展示场景、低成本 smoke fixture、CPU 测试和 RTX 5090 手工 GPU 验收流程。

## 依赖与已验证平台

| 组件 | v0.1 使用方式 | 验证状态 |
| --- | --- | --- |
| 操作系统 | Linux；容器基于 Ubuntu 24.04 | 仅 Linux 完整验证 |
| NVIDIA GPU | 支持所用 OptiX 功能的 RTX GPU | 仅 GeForce RTX 5090 完整验证 |
| CUDA | `nvidia/cuda:13.3.0-devel-ubuntu24.04` 容器 | CUDA 13.3 |
| OptiX | 用户另行取得并解压 SDK | OptiX 9.1 |
| 容器运行时 | Docker Engine；GPU 流程需要 NVIDIA Container Toolkit | Linux 主机 |
| 构建与测试工具 | CMake 3.28+、Ninja、C++17、Python 3/pytest | 已包含在项目容器中 |

Windows、多 GPU、其他显卡及其他 CUDA/OptiX 组合尚未完整验证，不能由现有 gallery 或像素 golden 推断为兼容。OptiX 的正式平台和驱动要求以 [NVIDIA OptiX 下载与文档](https://developer.nvidia.com/designworks/optix/download) 为准。

## 获取 OptiX 与构建

从 NVIDIA 官方页面另行下载并解压 OptiX 9.1。SDK 不在本仓库中，也不会被复制进容器镜像；GPU 脚本要求显式提供其绝对路径：

```bash
export OPTIX_ROOT="/absolute/path/to/OptiX-SDK-9.1.0"
test -f "$OPTIX_ROOT/include/optix.h"

./scripts/build-image.sh
./scripts/configure.sh Release
./scripts/build.sh Release
```

构建产物位于 `build/Release/`。v0.1 只支持从构建目录或项目容器运行；不提供可重定位安装包，因为可执行文件会加载同一构建树中的 OptiX IR。

## 低成本 smoke render

下面的命令渲染 64×64、1 spp、depth 2 的无降噪图片，适合先验证完整 GPU 路径：

```bash
./scripts/spectraldock.sh \
  --scene tests/scenes/smoke.json \
  --output output/smoke.png \
  --width 64 --height 64 --spp 1 --max-depth 2 --seed 1 \
  --no-denoise
```

结果写入 `output/smoke.png`，运行信息写入 `output/smoke.stats.json`。固定 CLI 为：

```text
spectraldock --scene SCENE.json --output OUTPUT.png
  [--width N] [--height N] [--spp N] [--max-depth N]
  [--seed N] [--exposure EV] [--denoise|--no-denoise]
```

CLI 参数覆盖场景默认值。`max_depth` 表示最多处理的表面事件数；最后一个事件仍估计显式直接光，但不会继续生成 BSDF 射线。

## 测试与示例

CPU 测试不需要 NVIDIA GPU 或 OptiX SDK：

```bash
./scripts/build-image.sh
./scripts/test.sh
```

它会完成 shell 语法检查、关闭 GPU 的 CMake 构建、CTest 和全部 Python 测试。GPU 环境、官方 OptiX 示例、MIS 对照、Compute Sanitizer 与像素 golden 属于 RTX 5090 手工验收，详见[实施与验收状态](docs/STATUS.md)。

运行时模型和纹理已完整收录在 `assets/examples/`，无需额外素材挂载。普通预览写入被忽略的 `output/examples/`：

```bash
./scripts/render-examples.sh --preset preview
```

`./scripts/render-examples.sh --preset final` 会直接覆盖受版本控制的 `docs/gallery/*.png` 和对应 stats，仅供维护者在正式验收与发布时使用。五个场景及其说明见[示例画廊](docs/EXAMPLES.md)。

## 已知限制

- 单 GPU、离线 RGBA PNG；没有交互窗口、分布式或多 GPU 渲染。
- 不实现 MTL、骨骼、动画、体积或通用非网格对象变换。
- mesh emitter 可显示发光，但不能作为显式采样灯；显式灯为 rectangle、disk 或 sphere。
- gallery 和 mesh 像素 golden 是一次 RTX 5090 结果，不是跨 GPU、驱动或编译器的逐字节承诺。
- 首版只发布源码，不附带二进制、容器镜像或第三方 SDK。

## 许可与商标

- 代码、文档、场景、SVG 和生成器：Apache License 2.0。
- 吉祥物 OBJ/manifest、为本项目生成的纹理和 gallery PNG：CC0 1.0 Universal。
- tinyobjloader：保留其 MIT 许可证。
- CUDA、OptiX 及其他外部 SDK 不随仓库分发。

完整说明见 [LICENSE](LICENSE)、[NOTICE](NOTICE) 与[素材和许可清单](docs/ASSETS.md)。AI 生成纹理为本项目生成，按现状提供且不保证唯一性；其来源和处理记录见素材清单。

NVIDIA、CUDA、OptiX 和 RTX 是 NVIDIA Corporation 在美国及其他国家和地区的商标或注册商标。SpectralDock 是独立的非官方项目，与 NVIDIA Corporation 无隶属关系，也未获得其赞助或背书。

更多资料：[渲染技术报告](docs/technical-report/README.md)、[场景格式](docs/SCENE_FORMAT.md)、[基准](docs/BENCHMARK.md)、[发布检查清单](docs/RELEASE_CHECKLIST.md)。
