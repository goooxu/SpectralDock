# 变更记录

本文件记录 SpectralDock 各主要版本中面向使用者、研究者和贡献者的重要变化。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循
[语义化版本](https://semver.org/lang/zh-CN/)。

只记录主要功能、兼容性变化、重要修复和移除项；机械性重构、格式调整和完整
commit 列表仍以 Git 历史为准。发布新版本时，应把 `Unreleased` 中的内容移入
带 `YYYY-MM-DD` 日期的新版本章节，并保持新版本在前。

## [Unreleased]

### 新增

- 提供命令式 Python `Renderer` API；普通 Python 程序可直接创建相机、材质、
  几何和灯光，并在 `render()` 调用中指定分辨率、采样数和输出路径。
- 提供隔离进程中的受限 PhysX Python API，使同一个 Python 程序可以运行 GPU
  刚体模拟、应用 actor-local 渲染附件并立即启动 OptiX。

### 变更

- 十个示例改为十个可直接执行的 Python 程序。SpectralDock 不再发现、加载或
  解释所谓“场景文件”，用户自定义渲染程序也不需要注册。
- 构建与运行改为仓库内宿主流程；CUDA 13.3/OptiX 9.1 renderer 和 CUDA
  12.8/PhysX 5.8 worker 保持进程隔离。

### 移除

- 移除 schema v6、全部场景 JSON、C++ JSON loader、`--scene` 主程序及临时
  场景序列化。这是有意的破坏性接口变化；stats、physics 和资产 manifest
  JSON 仍作为非场景运行记录保留。
- 移除 Dockerfiles、镜像构建脚本和容器运行路径。

## [0.1.0] - 2026-07-15

### 新增

- 建立面向计算机图形学研究与教学的 CUDA 13.3 / OptiX 9.1 单 GPU 离线路径
  追踪器，覆盖 GAS/IAS、Pipeline、SBT、自定义求交、路径追踪与 OptiX AI
  Denoiser 完整流程。
- 引入 schema v6 场景格式，支持共享 OBJ mesh、实例变换、alpha any-hit、纹理，
  以及 sphere、rectangle、disk、cylinder、parabola 等解析几何。
- 实现 Lambert、GGX metal、光滑和粗糙 dielectric、emitter，配套 NEE、MIS、
  俄罗斯轮盘、可见法线采样与确定性随机数流程。
- 加入 Radiance RGBE HDR 环境贴图、亮度与立体角重要性采样，以及 rectangle、
  disk、sphere、flame、point 和 directional 灯光模型。
- 加入程序化异质体积火焰、吸收与自发光传输、Delta Tracking 和体积 NEE。
- 加入有限解析波浪水面、粗糙介电反射与折射、Fresnel/Snell、RGB Beer 吸收、
  介质栈和水面 NEE/MIS。
- 加入 direct/indirect 两级 firefly 贡献钳位、PNG 与可选线性 PFM 输出，以及
  同名 `*.stats.json` 性能和安全计数记录。
- 将 PhysX 5.8.0 GPU 作为物理场景的 JIT 构建子系统；每次渲染 Kinetic
  Foundry 或 Lava Temple Oracle 前重新计算刚体姿态，再通过临时 schema v6
  场景交给相邻的 OptiX 进程。
- 提供八个静态教学场景、两个 PhysX 物理场景和十张正式 gallery PNG；其中
  “熔岩圣殿的机械先知”以 3840×2160、2048 spp 发布为项目封面。

### 改进

- 为粗糙水面补充有限灯、火焰与 HDR 环境 NEE，并通过分层选灯、可见球锥和
  反射分支过采样改善特色水面场景的收敛。
- 使用 HDR 环境重要性采样、点光/平行光和 firefly 抑制改善常用布光与高光
  噪声控制；Radiance Pavilion 与 Ember Forge 分别作为环境光和纯火焰照明
  的研究场景。
- 项目定位收敛为 Linux/RTX 图形学研究与教学参考实现；当前完整验证平台为
  RTX 5090、driver 615.36、CUDA 13.3 和 OptiX 9.1，不将结果外推为跨 GPU
  golden 或性能承诺。

### 修复

- 修正技术报告在 GitHub 上的公式宏和下划线渲染问题，并加入与源码同步校验的
  代码摘录。
- 收紧 Compute Sanitizer 的 API 错误报告范围，并为光传输、HDR、火焰、水面、
  delta 灯、firefly 和 PhysX 场景契约增加定向验收。

### 移除

- 移除 CPU 渲染实现及其渲染测试；host-only 路径只保留场景解析、文档、资产
  和契约检查，正式像素验收统一在 CUDA/OptiX GPU 环境完成。

### 文档与工程

- 增加从渲染方程到 OptiX、PhysX、体积火焰、解析水面、HDR 与重要性采样的
  中文技术报告，并让公式、原理、优化和源码实现相互对照。
- 增加 Ubuntu 容器工作流、host CTest/pytest、Release/Debug GPU 验收、
  Compute Sanitizer，以及 RTX 5090 gallery、stats 和 physics sidecar 记录。
