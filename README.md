# SpectralDock

SpectralDock 是面向计算机图形学研究与教学的 NVIDIA GPU 离线路径追踪器。它用 CUDA 与 OptiX 完成射线遍历和光传输，并通过隔离的 PhysX GPU 进程为需要刚体动力学的 Python 程序求解瞬时场景。运行契约不绑定某个 CPU 架构或 GPU 型号，也不要求 RT Core；GPU 只需能实际运行 OptiX，并同时支持 PhysX 的 GPU dynamics 与 GPU broadphase。

## 综合能力展示

### Tidal Observatory / 暮潮观测站

![暮潮观测站](docs/gallery/showcase/tidal-observatory.avif)

“暮潮观测站”坐落在日落后的海岸平台。Spot 位于中央检修台，Sparky 操作
多材质光学仪器，Capsule Mascot 在侧台校准带法线纹理的金属样片。低角度
HDR 天光与有限灯共同刻画陶瓷、粗糙金属、铬、低粗糙度 PBR 光学外壳和纹理表面；前景解析
波浪水池通过微表面 Fresnel 与 RGB Beer 吸收映出冷暖交错的倒影，远侧火焰
信标以吸收—自发光体积补充暖色层次。场景不运行 PhysX，所有姿态固定，以
稳定展示 SpectralDock 的材质、光传输、纹理、解析几何、水面、体积和 GPU
后处理能力。

### Atelier / 工坊

![Atelier 工坊](docs/gallery/showcase/atelier.avif)

Atelier 让九块彩色砖、金属球、磨砂外观球以及 Capsule、Spot、Sparky 在
`480 × 1/120 s` 的短时 PhysX 求解后落定，再把 14 个 actor 的最终姿态应用到
完整渲染附件。左后壁炉使用程序化 flame，右前石盆使用有不透明边界的解析
水面和 RGB Beer 吸收。渲染器没有 spotlight；场景用定向布置的有限 disk
面积灯与 rectangle 顶灯形成局部亮区和软阴影，这是场景级替代，不是新增的
灯光类型。正式图为 2560×1440、1024 spp、depth 12、seed 20260717，开启
importance sampling、direct/indirect clamp 64/16 与 OptiX Denoiser。

### Assembly Hall / 装配大厅

![Assembly Hall 装配大厅](docs/gallery/showcase/assembly-hall.avif)

Assembly Hall 以真实屋顶开口、程序化正午 HDR 的太阳热点和开口内有限面光
共同形成天窗光斑；
12 个 Spot 在 `36 × 1/120 s` 的 PhysX 求解中从倾斜玩具箱半空倾泻，Capsule
与四个糖果色 Sparky 组织前中景。场景用近零自发光、高吸收 flame 代理烟影，
用高粗糙度 PBR 肋条安全罩和三个重叠有限 emitter 球表现封闭炉火的暖晕，以
PBR 的 GGX/Lambert 组合代替独立 clearcoat，并在发光屏幕前放置同位
rectangle NEE 灯，代替
原生纹理网格灯采样。冷却池以四项解析波浪近似 fBm 外观，后墙齿轮使用
RGBA alpha mask；这些均是现有能力的场景级组合。正式图为 2560×1440、
2048 spp、depth 12、seed 20260718，并使用与 Atelier 相同的采样、钳位和
降噪策略。

## 特性对比

每组图片固定同一场景、相机、局部和随机种子，只改变标题所示变量。图片是
两个独立的 renderer 原始输出，页面不对它们进行拼接或像素后处理。

### 法线贴图 Normal Mapping

| OFF（`normal_scale=0`） | ON（`normal_scale=1`） |
| --- | --- |
| ![关闭法线贴图](docs/gallery/comparisons/normal-mapping-off.avif) | ![启用法线贴图](docs/gallery/comparisons/normal-mapping-on.avif) |

几何轮廓和 PBR 参数保持不变；ON 侧由 OpenGL/+Y tangent-space normal map
改变掠射高光与细部明暗，而不增加网格三角形。

### 间接光 Indirect Lighting

| OFF（`depth=1`） | ON（`depth=12`） |
| --- | --- |
| ![仅直接光](docs/gallery/comparisons/indirect-light-off.avif) | ![多次反弹间接光](docs/gallery/comparisons/indirect-light-on.avif) |

OFF 侧仍保留首个表面的直接光 NEE；ON 侧允许后续反弹，使遮蔽区域获得间接
填充，并显现彩色墙面对中性表面的串色。

### 环境重要性采样 Importance Sampling

| OFF（均匀方向采样） | ON（亮度/立体角重要性采样） |
| --- | --- |
| ![均匀采样](docs/gallery/comparisons/environment-importance-off.avif) | ![环境重要性采样](docs/gallery/comparisons/environment-importance-on.avif) |

两侧在收敛后应得到同一均值；这里以相同的低样本预算展示 HDR 亮区重要性
采样的方差优势，不能把 OFF 解读为关闭 NEE 或 MIS。

### AI 降噪 OptiX Denoiser

| OFF（原始 16 spp） | ON（相同样本 + Denoiser） |
| --- | --- |
| ![未经降噪](docs/gallery/comparisons/denoiser-off.avif) | ![OptiX AI 降噪](docs/gallery/comparisons/denoiser-on.avif) |

两侧复用同一条 Monte Carlo 样本序列；ON 侧只增加 OptiX 后处理，用于观察
阴影和间接光噪声降低时，几何边缘与材质分区是否仍被保留。

### 水下吸收 Beer Absorption

| OFF（零吸收） | ON（RGB Beer 吸收） |
| --- | --- |
| ![关闭水下吸收](docs/gallery/comparisons/beer-absorption-off.avif) | ![启用水下吸收](docs/gallery/comparisons/beer-absorption-on.avif) |

波面、粗糙度、IOR、照明与水下中性参照物完全相同；ON 侧随传播距离产生
选择性衰减，用深浅参照物区分介质吸收和单纯的彩色灯光。

### Firefly 钳位 Contribution Clamping

| OFF（direct/indirect `0/0`） | ON（direct/indirect `64/16`） |
| --- | --- |
| ![关闭贡献钳位](docs/gallery/comparisons/firefly-clamp-off.avif) | ![启用贡献钳位](docs/gallery/comparisons/firefly-clamp-on.avif) |

ON 侧限制少数极端路径贡献以稳定展示图，但这是明确的有偏策略，不比 OFF
更准确；能量与收敛实验必须继续使用 `0/0`。

项目没有场景文件格式，也没有接收 `--scene` 参数的渲染主程序。每个示例都是普通 Python 程序：代码通过 SpectralDock API 添加相机、材质、几何和灯光，随后直接调用 `render()` 并明确指定分辨率、采样数与输出路径。

```python
from pathlib import Path
from spectraldock import Renderer

renderer = Renderer(device=0)
renderer.camera(
    look_from=(3.0, 2.0, 5.0),
    look_at=(0.0, 0.5, 0.0),
    up=(0.0, 1.0, 0.0),
    vfov=38.0,
    aperture=0.0,
    focus_distance=5.0,
)
renderer.background(type="constant", color=(0.01, 0.01, 0.015))
white = renderer.material(
    name="white", type="lambertian", base_color=(0.75, 0.75, 0.75)
)
renderer.object(
    name="floor", type="rectangle", material=white,
    p1=(-3.0, 0.0, 2.0), p2=(-3.0, 0.0, -3.0),
    p3=(3.0, 0.0, -3.0),
)
renderer.render(
    output=Path("output/first-light.avif"),
    stats_output=Path("output/first-light.stats.json"),
    width=640, height=360, spp=64, depth=8, seed=1,
    denoise=True,
)
```

Python 程序是受信任的应用代码，而不是由 SpectralDock 解释的数据；项目不提供 Python 沙箱。

## 功能

- OptiX GAS/IAS、Program Group、Pipeline、SBT、`optixLaunch` 与 AI Denoiser。
- sphere、支持 alpha 裁剪的 rectangle、disk、cylinder、parabola、共享 OBJ mesh 和有限解析波浪水面。
- OBJ `usemtl` 槽到 typed material handle 的显式映射；多材质实例仍共享一份 GAS。
- Lambert、GGX metal、metallic-roughness PBR、MikkTSpace normal map、
  光滑/粗糙 dielectric、water 与 emitter。
- rectangle、disk、sphere 面积灯，point/directional delta 灯，以及程序化吸收/自发光 flame 体积。
- Radiance RGBE HDR 环境、经纬映射、旋转与亮度/立体角重要性采样。
- NEE、MIS、俄罗斯轮盘、介质栈、Beer 吸收与 direct/indirect firefly 贡献钳位。
- 类型化 Python texture/material/mesh/object handle；灯光注册直接引用这些 handle，不使用字符串 schema 引用。
- 固定 HDR AVIF 输出和显式指定的 JSON 运行统计。JSON 仅用于运行记录与资产 manifest，不用于描述场景。
- 受限 PhysX Python API：GPU 刚体、box/sphere/capsule/compound 碰撞体、冲量和 actor-local 渲染附件。

## 图像格式契约

- 每次渲染都输出单帧 HDR AVIF：10 bit、Rec.2020/PQ、CICP `9/16/9`、
  YUV 4:4:4 full range，并在 10 bit 量化后使用固定 AOM AV1 lossless 编码。
- 线性 Rec.709 beauty 先应用场景曝光，再转换到 Rec.2020；保色相的 max-RGB
  soft shoulder 把线性 `1.0` 定义为 203 nit diffuse white，并把高光渐近限制在
  1000 nit。文件同时写入内容亮度元数据。
- 背景曝光只接受有限的 `[-128, 128]` EV，有效值严格按 $2^{EV}$
  缩放。越界会在创建输出文件前失败，不会静默饱和或截到端点；
  1000 nit 限制只来自后续明确定义的 soft shoulder。
- 普通颜色纹理和材质数据图使用单帧 8 bit AVIF。颜色纹理按 sRGB 解释；
  normal、metallic-roughness 和 alpha 等数据图使用 full-range 4:4:4、linear
  transfer 与 identity matrix 的严格配置。
- 自发光纹理还可使用单帧 10/12 bit HDR AVIF，但必须显式声明 CICP `9/16/9`
  （BT.2020/PQ/BT.2020 NCL）。输入会解码为以 203 nit 为 `1.0` 的线性
  Rec.709 `float4`，因此高于 diffuse white 的能量不会被 8 bit 归一化截断；
  HDR 纹理禁止用于 base color、normal、metallic-roughness 或 alpha。
- 所有 AVIF 纹理均拒绝动画/分层、ICC、gain map、预乘 alpha 和像素变换；
  Sample Transform/16 bit 派生图也会显式拒绝。输入和输出均限制为单边不超过
  16384、总计不超过 $2^{25}$ 像素；容器级违规在 AV1 component 解码前失败。
  仓库编码器使用 AV1 lossless。
- Radiance RGBE 只以严格小写 `.hdr` 保留作线性环境贴图输入；加载时累计消除
  header 的 `EXPOSURE`/`COLORCORR`，并按 `PRIMARIES`（缺省为 Radiance
  标准 primaries/等能白点）适配、转换到线性 Rec.709/D65。它不是普通材质纹理，
  也不是渲染输出；其他栅格格式以及非 `.avif` 渲染路径都会被拒绝。

## 平台与运行契约

项目不把 CPU 架构白名单作为运行契约，也不针对某个 CPU 微架构编译；构建使用
当前主机工具链，PhysX SDK 可通过 flat layout 或显式 library/runtime 目录适配
SDK 支持的宿主架构，随 libavif 获取的 AOM 在运行时选择当前 CPU 可用的实现。
GPU 必须是驱动、CUDA 与 OptiX 共同支持的 NVIDIA GPU，但不检查产品名、
compute capability 白名单或 RT Core。OptiX 初始化和 launch 必须成功。

涉及物理的程序还必须创建有效的 PhysX CUDA context，并同时启用
`PxSceneFlag::eENABLE_GPU_DYNAMICS` 与 `PxBroadPhaseType::eGPU`。任一条件失败
都会终止运行，CPU PhysX fallback 明确禁止；CPU dispatcher 只承担 PhysX 的
宿主任务调度，不是 CPU 刚体求解器。

当前构建接口使用 CUDA 13.x / OptiX 9.1 渲染和 CUDA 12.8 / PhysX 5.8 worker；
两者位于不同构建树和进程。CUDA、OptiX 与 PhysX SDK 不随仓库分发。其驱动与
平台兼容性仍以 NVIDIA 文档为准。

## 宿主构建

准备两个 CUDA toolkit、OptiX SDK 和已安装的 PhysX GPU SDK，然后明确设置路径：

```bash
export SPECTRALDOCK_CUDA_ROOT=/absolute/path/to/cuda-13.x
export OPTIX_ROOT=/absolute/path/to/OptiX-SDK-9.1.0
export SPECTRALDOCK_PHYSX_CUDA_ROOT=/absolute/path/to/cuda-12.8
export PHYSX_ROOT=/absolute/path/to/physx-5.8-install

./scripts/configure.sh Release
./scripts/build.sh Release
source ./scripts/activate.sh Release
```

OptiX 设备 module 固定生成为 portable PTX。配置时 CMake 读取
`nvcc --list-gpu-arch`，选择当前 toolkit 报告的最老虚拟架构作为 PTX baseline；
它不探测或写死实际 GPU 的产品名、SM/SASS 目标或 RT Core。驱动在运行时为
所选 GPU JIT。工具链仍为当前主机生成原生 host 对象。仓库也提供
`containers/test/Dockerfile` 作为双 CUDA toolkit 的测试环境定义；OptiX 与
PhysX SDK 需按本机架构挂载。

`activate.sh` 只把仓库内 Python 包、Renderer 原生扩展和独立 PhysX worker 加入当前 shell 的查找路径，不会发现、加载或执行任何场景程序。

只构建无 GPU 的 SceneBuilder 与 host 测试时，不需要上述 NVIDIA SDK：

```bash
./scripts/test.sh
```

## 直接运行示例

每个示例自行指定输出文件和渲染参数：

```bash
python3 scenes/material-cathedral.py
python3 scenes/radiance-pavilion.py
python3 scenes/kinetic-foundry.py
python3 scenes/lava-temple-oracle.py

# 新首页/Gallery 生产程序；支持 --device、--output-dir 与 --preview
python3 scenes/tidal-observatory.py
python3 scenes/atelier.py
python3 scenes/assembly-hall.py
python3 scenes/compare-light-transport.py
python3 scenes/compare-hdr-sampling.py
python3 scenes/compare-normal-mapping.py
python3 scenes/compare-water-absorption.py
```

八个静态教学示例直接进入 OptiX。原有两个物理教学示例以及 Atelier、
Assembly Hall 两个 PhysX Gallery 程序都在各自 Python 程序中显式创建
`PhysicsWorld`、运行 fresh GPU PhysX、把结果应用到 `Renderer`，然后调用
OptiX；它们不会读取或生成场景 JSON，也不会回退到 CPU 物理。

Radiance Pavilion 以两个 AI 生成角色——胶囊吉祥物和显式十槽材质映射的 Sparky——为双主角，且 HDR 环境是唯一光源；gallery 与同 stem stats 只记录产出时的软件栈和设备，不构成型号相关基线。

维护者可用 `./scripts/render-examples.sh` 依次直接执行原有十个教学程序。该脚本只是批处理，不把 Python 文件作为参数传给渲染器。Gallery 生产程序独立运行，普通执行只写 `output/gallery/`，不会覆盖仓库中的正式图片。

更多代码与效果说明见[示例画廊](docs/EXAMPLES.md)，API 见[Python 渲染 API](docs/PYTHON_API.md)，PhysX 数学与工程边界见[PhysX 场景说明](docs/PHYSX_SCENE.md)。

## 测试

GitHub Actions 只执行无 GPU 的 C++/Python host 检查。完整维护者验收在任意
满足上述运行契约的测试机上执行 Release smoke、OptiX validation、受控光传输
契约、静态/Gallery 预览，并强制运行 PhysX GPU-only 探针和四个物理程序。
标准托管 runner 不承担 GPU 或 PhysX 验收。

```bash
./scripts/test.sh
# 完整验收需要 Renderer 与 PhysX 两套 SDK，并拒绝 CPU PhysX fallback
./scripts/acceptance.sh
```

验收不按 GPU 型号选择或跳过测试，也不保存型号专属像素哈希。fixture 检查结构、
几何统计、HDR AVIF profile、尺寸、非空像素和数值容差；gallery stats 只用于
运行溯源，不是跨 GPU 的逐字节承诺或性能门槛。

## 已知限制

- 单 GPU、离线 HDR AVIF；没有交互窗口、分布式、多 GPU 或 motion blur。
- 不自动把 MTL 数值推断为 BSDF；支持显式 `usemtl` 槽映射，但尚无
  glTF/GLB、骨骼、动画、通用参与介质、燃烧化学或流体动力学。
- PBR normal map 首版只支持 OBJ triangle mesh；尚无材质级 emission/alpha、
  occlusion、mipmap、各向异性过滤或扩展 PBR lobes。
- `water_surface` 是静态有限解析界面，需要不透明池壁和池底；它不是 PhysX 流体。
- flame 是确定性吸收/自发光体积代理，不是烟流或燃烧模拟。
- point/directional 是理想 delta 灯；软阴影需使用有限面积灯。
- 没有原生 spotlight、独立 clearcoat、可采样纹理网格灯、烟流或 fBm 水面；
  Atelier 与 Assembly Hall 分别用定向有限面积灯、现有 PBR 瓣、同位 NEE
  面灯、吸收性 flame 和四项解析波浪作场景级近似。为保持含开放水面的严格
  介质栈安全，两场景的磨砂球/隔间还分别使用不透明高粗糙度 PBR 球，以及
  PBR 肋条罩加有限 emitter 暖晕；它们不宣称玻璃透射。
- 表面派生射线已使用 primitive-aware 位置误差界与 ULP 外推，不再把固定 epsilon 当作
  ray-spawn 距离；解析水面的端点交叉探测与无法分辨的近切 enter/exit 对仍使用
  独立的固定世界空间
  `water_solver_epsilon`，极端缩放的波面参数不在当前验收范围内。解析 primitive
  的误差界在通用 fallback 上为 sphere、disk、cylinder、parabola 和 water 加入实际曲面
  residual，但仍不保证严格封闭所有近切求交的条件数放大。custom primitive
  的设备边界先向外舍入一个 float ULP；普通 custom GAS 还镜像设备 root clip
  容差，构建遍历用 `OptixAabb`（包括每个 water tile）时再保留一个 ULP guard，
  避免大坐标包围盒向内取整导致 BVH 漏交。
- 默认 direct 64、indirect 16 的贡献钳位有偏；能量或收敛实验必须在 Python 调用中把两个阈值设为 0。
- PhysX GPU 不承诺重复运行逐字节相同；固定 seed 和 actor 顺序约束输入，契约验证约束结果。

## 许可与商标

代码、Python 示例、文档与生成器使用 Apache-2.0；明确列出的视觉资产和 gallery AVIF 使用 CC0-1.0；tinyobjloader 保留 MIT，MikkTSpace 保留其
zlib-style notice。详见 [LICENSE](LICENSE)、[NOTICE](NOTICE)、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和[素材清单](docs/ASSETS.md)。

NVIDIA、CUDA、OptiX、PhysX 和 RTX 是 NVIDIA Corporation 的商标或注册商标。SpectralDock 是独立的非官方项目，与 NVIDIA Corporation 无隶属关系，也未获得其赞助或背书。

更多资料：[版本变更](CHANGELOG.md)、[渲染技术报告](docs/technical-report/README.md)、[验证与统计说明](docs/BENCHMARK.md)。
