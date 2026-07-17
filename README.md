# SpectralDock

SpectralDock 是面向计算机图形学研究与教学的 NVIDIA GPU 离线路径追踪器。它用 CUDA 与 OptiX 完成硬件射线遍历和光传输，并通过隔离的 PhysX GPU 进程为需要刚体动力学的 Python 程序求解瞬时场景。

## 综合能力展示

### Tidal Observatory / 暮潮观测站

![暮潮观测站](docs/gallery/showcase/tidal-observatory.png)

“暮潮观测站”坐落在日落后的海岸平台。Spot 位于中央检修台，Sparky 操作
多材质光学仪器，Capsule Mascot 在侧台校准带法线纹理的金属样片。低角度
HDR 天光与有限灯共同刻画陶瓷、粗糙金属、铬、低粗糙度 PBR 光学外壳和纹理表面；前景解析
波浪水池通过微表面 Fresnel 与 RGB Beer 吸收映出冷暖交错的倒影，远侧火焰
信标以吸收—自发光体积补充暖色层次。场景不运行 PhysX，所有姿态固定，以
稳定展示 SpectralDock 的材质、光传输、纹理、解析几何、水面、体积和 GPU
后处理能力。

### Atelier / 工坊

![Atelier 工坊](docs/gallery/showcase/atelier.png)

Atelier 让九块彩色砖、金属球、磨砂外观球以及 Capsule、Spot、Sparky 在
`480 × 1/120 s` 的短时 PhysX 求解后落定，再把 14 个 actor 的最终姿态应用到
完整渲染附件。左后壁炉使用程序化 flame，右前石盆使用有不透明边界的解析
水面和 RGB Beer 吸收。渲染器没有 spotlight；场景用定向布置的有限 disk
面积灯与 rectangle 顶灯形成局部亮区和软阴影，这是场景级替代，不是新增的
灯光类型。正式图为 2560×1440、1024 spp、depth 12、seed 20260717，开启
importance sampling、direct/indirect clamp 64/16 与 OptiX Denoiser。

### Assembly Hall / 装配大厅

![Assembly Hall 装配大厅](docs/gallery/showcase/assembly-hall.png)

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
| ![关闭法线贴图](docs/gallery/comparisons/normal-mapping-off.png) | ![启用法线贴图](docs/gallery/comparisons/normal-mapping-on.png) |

几何轮廓和 PBR 参数保持不变；ON 侧由 OpenGL/+Y tangent-space normal map
改变掠射高光与细部明暗，而不增加网格三角形。

### 间接光 Indirect Lighting

| OFF（`depth=1`） | ON（`depth=12`） |
| --- | --- |
| ![仅直接光](docs/gallery/comparisons/indirect-light-off.png) | ![多次反弹间接光](docs/gallery/comparisons/indirect-light-on.png) |

OFF 侧仍保留首个表面的直接光 NEE；ON 侧允许后续反弹，使遮蔽区域获得间接
填充，并显现彩色墙面对中性表面的串色。

### 环境重要性采样 Importance Sampling

| OFF（均匀方向采样） | ON（亮度/立体角重要性采样） |
| --- | --- |
| ![均匀采样](docs/gallery/comparisons/environment-importance-off.png) | ![环境重要性采样](docs/gallery/comparisons/environment-importance-on.png) |

两侧在收敛后应得到同一均值；这里以相同的低样本预算展示 HDR 亮区重要性
采样的方差优势，不能把 OFF 解读为关闭 NEE 或 MIS。

### AI 降噪 OptiX Denoiser

| OFF（原始 16 spp） | ON（相同样本 + Denoiser） |
| --- | --- |
| ![未经降噪](docs/gallery/comparisons/denoiser-off.png) | ![OptiX AI 降噪](docs/gallery/comparisons/denoiser-on.png) |

两侧复用同一条 Monte Carlo 样本序列；ON 侧只增加 OptiX 后处理，用于观察
阴影和间接光噪声降低时，几何边缘与材质分区是否仍被保留。

### 水下吸收 Beer Absorption

| OFF（零吸收） | ON（RGB Beer 吸收） |
| --- | --- |
| ![关闭水下吸收](docs/gallery/comparisons/beer-absorption-off.png) | ![启用水下吸收](docs/gallery/comparisons/beer-absorption-on.png) |

波面、粗糙度、IOR、照明与水下中性参照物完全相同；ON 侧随传播距离产生
选择性衰减，用深浅参照物区分介质吸收和单纯的彩色灯光。

### Firefly 钳位 Contribution Clamping

| OFF（direct/indirect `0/0`） | ON（direct/indirect `64/16`） |
| --- | --- |
| ![关闭贡献钳位](docs/gallery/comparisons/firefly-clamp-off.png) | ![启用贡献钳位](docs/gallery/comparisons/firefly-clamp-on.png) |

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
    output=Path("output/first-light.png"),
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
- 可选 PFM 线性输出和显式指定的 JSON 运行统计。JSON 仅用于运行记录与资产 manifest，不用于描述场景。
- 受限 PhysX Python API：GPU 刚体、box/sphere/capsule/compound 碰撞体、冲量和 actor-local 渲染附件。

## 已验证环境

| 组件 | 完整验证版本 |
| --- | --- |
| 操作系统 | Ubuntu 22.04 x86-64（Linux only） |
| GPU | NVIDIA GeForce RTX 5090 |
| 驱动 | 615.36 |
| Python | 3.10 |
| CUDA / OptiX 渲染 | CUDA 13.3 / OptiX 9.1 |
| PhysX 求解 | PhysX 5.8.0 / CUDA 12.8 |
| 构建工具 | CMake 3.28+、Ninja、C11/C++17、pybind11 |

Windows、多 GPU、其他显卡以及其他 CUDA/OptiX 组合尚未完整验证。CUDA、OptiX 和 PhysX SDK 不随仓库分发；OptiX 的正式驱动与平台要求以 NVIDIA 文档为准。

## 宿主构建

SpectralDock 只支持仓库内宿主构建，不需要也不提供容器镜像。准备两个 CUDA toolkit、OptiX SDK 和已安装的 PhysX SDK，然后明确设置路径：

```bash
export SPECTRALDOCK_CUDA_ROOT=/absolute/path/to/cuda-13.3
export OPTIX_ROOT=/absolute/path/to/OptiX-SDK-9.1.0
export SPECTRALDOCK_PHYSX_CUDA_ROOT=/absolute/path/to/cuda-12.8
export PHYSX_ROOT=/absolute/path/to/physx-5.8-install

./scripts/configure.sh Release
./scripts/build.sh Release
source ./scripts/activate.sh Release
```

OptiX 设备 module 默认以 OptiX IR（`.optixir`）构建。若特定驱动组合不能加载
OptiX IR，可在重新配置与构建前显式使用 PTX 兼容入口：

```bash
export SPECTRALDOCK_OPTIX_MODULE_FORMAT=ptx
./scripts/configure.sh Release
./scripts/build.sh Release
```

该选项只接受 `optixir`（默认）或 `ptx`，不改变既有 RTX 5090 的默认构建路径。

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

Radiance Pavilion 以两个 AI 生成角色——胶囊吉祥物和显式十槽材质映射的 Sparky——为双主角，且 HDR 环境是唯一光源；gallery 与同 stem stats 来自 RTX 5090 正式渲染。

维护者可用 `./scripts/render-examples.sh` 依次直接执行原有十个教学程序。该脚本只是批处理，不把 Python 文件作为参数传给渲染器。Gallery 生产程序独立运行，普通执行只写 `output/gallery/`，不会覆盖仓库中的正式图片。

更多代码与效果说明见[示例画廊](docs/EXAMPLES.md)，API 见[Python 渲染 API](docs/PYTHON_API.md)，PhysX 数学与工程边界见[PhysX 场景说明](docs/PHYSX_SCENE.md)。

## 测试

GitHub Actions 只执行无 GPU 的 C++/Python host 检查。RTX 5090 维护者验收包括
Release smoke、OptiX validation、受控光传输契约、八个静态教学示例预览和
五个纯 Renderer Gallery 程序的低成本预览；提供 PhysX SDK 时再运行两个
PhysX Gallery 封面和原有两个物理教学示例及其场景契约。标准托管 runner
不承担 GPU 或 PhysX 验收。

```bash
./scripts/test.sh
# 默认验收教学示例和 Gallery 预览，需要 Renderer 与 PhysX 两套 SDK
./scripts/acceptance.sh
# 没有 PhysX SDK 时，显式跳过四个 PhysX 程序
SPECTRALDOCK_BUILD_PHYSX=OFF ./scripts/acceptance.sh
# 非 RTX 5090 测试机只显式跳过该机型专属的 mesh 像素哈希；fixture 的结构、
# 几何统计、尺寸和非空像素检查仍会执行
SPECTRALDOCK_SKIP_RTX5090_GOLDEN=ON ./scripts/acceptance.sh
```

旧示例 gallery stats 与 mesh golden 只代表记录中的 RTX 5090、驱动、编译器和 seed，不是跨 GPU 的逐字节承诺。新首页/Gallery PNG 是作品展示，不提交临时渲染机 stats，也不作为像素 golden 或性能基线。

## 已知限制

- 单 GPU、离线 PNG/PFM；没有交互窗口、分布式、多 GPU 或 motion blur。
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

代码、Python 示例、文档与生成器使用 Apache-2.0；明确列出的视觉资产和 gallery PNG 使用 CC0-1.0；tinyobjloader 保留 MIT，MikkTSpace 保留其
zlib-style notice。详见 [LICENSE](LICENSE)、[NOTICE](NOTICE)、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和[素材清单](docs/ASSETS.md)。

NVIDIA、CUDA、OptiX、PhysX 和 RTX 是 NVIDIA Corporation 的商标或注册商标。SpectralDock 是独立的非官方项目，与 NVIDIA Corporation 无隶属关系，也未获得其赞助或背书。

更多资料：[版本变更](CHANGELOG.md)、[渲染技术报告](docs/technical-report/README.md)、[RTX 5090 运行记录](docs/BENCHMARK.md)。
