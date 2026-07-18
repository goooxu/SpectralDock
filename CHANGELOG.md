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
- 增加 `mesh(materials={...})` 显式多材质 OBJ 接口，通过逐三角形材质索引
  在单个 GAS 中解析 `usemtl` 槽；新增 AI 生成的 CC0 Sparky OBJ/MTL/albedo 资产。
- 增加 metallic-roughness PBR 材质、独立 base-color/MR/normal 纹理槽、
  MikkTSpace OBJ 切线生成，以及 clamp/repeat/mirrored-repeat 纹理寻址。
- 增加 Keenan Crane / CMU Model Repository 以 CC0-1.0 发布的 Spot
  三角网格与位图纹理，作为可复用示例模型资产；现有场景保持不变。
- 为 capsule mascot 增加包含 15 个部件槽的 CC0 MTL；确定性生成器现在同时
  重建 OBJ、MTL 与 manifest，并明确记录原始资产的 AI 来源。现有场景继续
  显式选择材质，画面保持不变。
- 增加新首页与 Gallery 生产程序：2K 级“暮潮观测站”综合展示，
  以及法线贴图、间接光、环境重要性采样、OptiX Denoiser、Beer 吸收和
  firefly 贡献钳位六组 1K 级单变量 OFF/ON 对比。
- 增加 Atelier 与 Assembly Hall 两个 2560×1440 PhysX Gallery 封面程序；
  前者展示 14 个刚体落定、壁炉和水盆，后者展示 12 个 Spot 半空倾泻、天窗
  HDR、炉火/烟影代理、冷却池和 alpha 齿轮。两图不附带 stats、physics
  sidecar、像素 golden 或性能基准。
- 增加可确定重建的 `assembly-hall-noon.hdr` 与
  `assembly-hall-gear-alpha.avif`，分别提供环境太阳热点和 alpha 裁剪标志。
- 增加可确定重建的 showcase panel OBJ、OpenGL/+Y 法线纹理和
  metallic-roughness 数据纹理，用于 Gallery 的 PBR 对比与综合场景。

### 变更

- 所有渲染输出统一为 10 bit Rec.2020/PQ HDR AVIF：CICP `9/16/9`、YUV
  4:4:4 full range、203 nit diffuse white、1000 nit peak，并在量化后固定使用
  AOM AV1 lossless。删除公共线性文件输出。
- 所有普通颜色纹理和材质数据图统一为 8 bit lossless AVIF；数据图采用严格的
  BT.709/linear/identity/full-range 4:4:4 profile。自发光纹理可额外使用
  CICP `9/16/9` 的 10/12 bit HDR AVIF，并解码、上传为保留大于 `1.0` 能量的
  线性 Rec.709 float texture；HDR profile 禁止用于表面数据槽和 alpha。
  Radiance RGBE `.hdr` 继续只用于环境贴图。
- Radiance 环境路径必须使用小写 `.hdr`；加载器累计消除 `EXPOSURE` 与
  `COLORCORR`，并按单个 `PRIMARIES`（缺省为 Radiance 标准值）经白点适配
  转换到线性 Rec.709/D65。项目生成器显式声明其 Rec.709/D65 色彩语义。
- 栅格 I/O 改为固定 libavif 1.4.2 commit 与其 AOM 3.14.1 local backend；构建
  不再引入旧栅格编解码依赖，AOM 保留运行时 CPU dispatch。
- 平台契约不绑定 CPU 架构、GPU 型号或 RT Core；host 对象由当前原生工具链
  构建，PhysX SDK layout 由发现逻辑或显式目录提供。GPU 必须能运行 OptiX；
  物理验收必须同时证明 PhysX GPU dynamics、GPU broadphase 和有效 CUDA
  context，CPU PhysX fallback 禁止。

- 将 Capsule Mascot 的 OBJ、MTL 与 manifest 归整到独立模型目录，与 Sparky
  和 Spot 的资产包布局保持一致；使用该模型的九个场景只同步仓库内路径。
- 十个示例改为十个可直接执行的 Python 程序。SpectralDock 不再发现、加载或
  解释所谓“场景文件”，用户自定义渲染程序也不需要注册。
- 构建与运行改为仓库内宿主流程；CUDA 13.x/OptiX 9.1 renderer 和 CUDA
  12.8/PhysX 5.8 worker 保持进程隔离。
- Radiance Pavilion 改为 capsule mascot 与 Sparky 并列的双主角展台，同时
  保持 HDR 环境贴图是唯一光源。
- Neon Koi 改为纯几何霓虹装置：用锦鲤线稿、电路折线和 PBR
  墙板替代原有图像纹理，保留湿地反射、彩色间接光与景深。
- OBJ 导入器会丢弃 corner 解析到完全重复 position 的零面积导出器残留，
  但仍拒绝三点不同的共线退化面；Sparky 源面与可渲染面统计分别锁定。
- Python API 收敛到单一规范写法：相机使用 `vfov`，mesh 使用平铺变换，
  parabola 使用 `clip_min`/`clip_max`，渲染深度使用 `depth`，曝光属于背景；
  `light()` 改为注册后返回 `None`。
- 默认 GPU 验收收敛为 Release smoke、OptiX validation、受控数学契约、静态
  与 Gallery 预览、PhysX GPU-only 探针和四个物理程序；完整 acceptance 不允许
  跳过 PhysX，host 检查统一由 `scripts/test.sh` 进入。
- 移除 GPU 型号门禁、型号专属像素哈希和固定 SM 架构列表；fixture 改为验证
  结构、几何统计、HDR AVIF profile、图像尺寸、非空像素和数值容差。
- OptiX 设备 module 固定生成 portable PTX；配置时从 `nvcc --list-gpu-arch`
  选择 toolkit 支持的最老虚拟架构，避免设备型号、SM/SASS 或 RT Core 假设，
  再由当前驱动在运行时为实际 GPU JIT。

### 修复

- Scene 成为曝光与积分器默认阈值的唯一真源；逐次 clamp override 不再改写
  Scene，并删除 Python 镜像状态。HDR AVIF 编码现在拒绝 NaN/无穷，不再静默
  写成黑色。
- AVIF 容器在 component 解码前拒绝多帧/分层、ICC、gain map、像素变换、
  预乘 alpha 与 Sample Transform；输入输出统一限制单边 16384、总计 $2^{25}$
  像素，避免极端长宽组合触发数 GiB 临时分配。
- 修正表面派生射线在极大坐标与极小几何上的自交/漏交风险：交点现在携带
  primitive-aware 位置误差界；triangle/mesh 计入顶点 extent、对象到世界重建与
  traversal 的世界到对象仿射误差，解析 primitive 使用命中点、位移和包围 extent 的保守 fallback，
  sphere/disk/cylinder/parabola 与解析水面还加入实际曲面 residual。
  radiance 与 shadow origin 沿定向几何法线
  偏移后再用 `nextafterf` 外推；rectangle/disk/sphere 有限灯的采样端点也按
  anchor/extent 与实际灯面 residual 的位置误差界沿法线向连接内部外推，统一有限灯的数值 endpoint，并排除
  unbound light 同位置但 `light_index = -1` 的 emitter geometry，以及其他端点
  附近 coincident geometry 的闭区间舍入误命中；bound target geometry 仍由
  any-hit 按 `light_index` 忽略。最终 `tmax` 再向零舍入一个 ULP。固定
  `water_solver_epsilon` 仅用于
  水面端点交叉探测与无法分辨的近切
  enter/exit 对，不再控制 ray spawn。
- 修正大坐标 custom primitive 的 float AABB 可能向内取整并被 BVH 错误剔除：
  设备侧语义边界先逐分量把 min 向负无穷、max 向正无穷外推一个 ULP，构建
  `OptixAabb` 时再保留一个 traversal ULP guard；普通 custom GAS 同时镜像设备
  root clip 的共享容差，water tile 则镜像既有 overlap。该 clip 容差不参与 ray spawn。
- 修正平滑网格的着色法线语义：连续 Lambert/GGX 按有效着色法线及 `AbsDot`
  求值，定向几何法线统一负责物理半空间、介质栈和所有表面射线偏移；光滑
  dielectric/water 的 Fresnel 与 Snell 方向不再被顶点法线扭曲。
- 修正 sRGB 图像纹理的过滤顺序：CUDA 现在先在线性空间解码颜色，再执行
  双线性插值，不再对编码码值插值后才解码。

### 移除

- 移除 schema v6、全部场景 JSON、C++ JSON loader、`--scene` 主程序及临时
  场景序列化。这是有意的破坏性接口变化；stats、physics 和资产 manifest
  JSON 仍作为非场景运行记录保留。
- 移除旧容器运行路径；新增的 `containers/test/Dockerfile` 仅定义可复现的双
  CUDA 测试环境，并通过多架构基础镜像选择宿主 ISA。
- 移除 Python API 的 `vertical_fov_degrees`、`mesh_instance`、嵌套
  `transform`、`max_depth`、parabola `clip` 和 render `exposure` 兼容入口，
  以及按名称查询 handle 的 registry、`LightHandle` 与 `gpu_enabled`。
- 移除独立 `sketch` 几何；alpha 图形统一使用 rectangle 的
  `alpha_texture`/`alpha_cutoff`。同时删除独立 sanitizer 矩阵、Moonlit
  time-to-error、Radiance Pavilion 场景级 A/B 和粗糙介电 8192 spp full
  profile 等高成本维护流程。
- 移除 Koi mask 与 circuit panel 两张生成式示例纹理及其
  来源记录；纹理 smoke 改用测试运行时构造的小型确定性 fixture。

## [0.1.0] - 2026-07-15

### 新增

- 建立面向计算机图形学研究与教学的 CUDA 13.x / OptiX 9.1 单 GPU 离线路径
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
- 加入 direct/indirect 两级 firefly 贡献钳位、早期展示图输出，以及同名
  `*.stats.json` 性能和安全计数记录；这些旧输出接口已由 0.2 的固定 HDR AVIF
  契约取代。
- 将 PhysX 5.8.0 GPU 作为物理场景的 JIT 构建子系统；每次渲染 Kinetic
  Foundry 或 Lava Temple Oracle 前重新计算刚体姿态，再通过临时 schema v6
  场景交给相邻的 OptiX 进程。
- 提供八个静态教学场景、两个 PhysX 物理场景和十张正式 gallery 图；其中
  “熔岩圣殿的机械先知”以 3840×2160、2048 spp 发布为项目封面。

### 改进

- 为粗糙水面补充有限灯、火焰与 HDR 环境 NEE，并通过分层选灯、可见球锥和
  反射分支过采样改善特色水面场景的收敛。
- 使用 HDR 环境重要性采样、点光/平行光和 firefly 抑制改善常用布光与高光
  噪声控制；Radiance Pavilion 与 Ember Forge 分别作为环境光和纯火焰照明
  的研究场景。
- 项目定位收敛为 Linux/NVIDIA GPU 图形学研究与教学参考实现；运行记录不
  外推为跨 GPU golden 或性能承诺。

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
  Compute Sanitizer，以及 gallery、stats 和 physics sidecar 运行记录。
