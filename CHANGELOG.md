# 变更记录

本文件记录 SpectralDock 各主要版本中面向使用者、研究者和贡献者的重要变化。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循
[语义化版本](https://semver.org/lang/zh-CN/)。

只记录主要功能、兼容性变化、重要修复和移除项；机械性重构、格式调整和完整
commit 列表仍以 Git 历史为准。发布新版本时，应把 `Unreleased` 中的内容移入
带 `YYYY-MM-DD` 日期的新版本章节，并保持新版本在前。

## [Unreleased]

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

