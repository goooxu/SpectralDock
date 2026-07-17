# 示例素材与许可

## 许可矩阵

| 范围 | 许可证 |
| --- | --- |
| 代码、脚本、Python 场景程序、C++ worker、文档、SVG、测试 fixture、图像素材清单、Sparky/Showcase Panel manifest、gallery stats 与物理 sidecar | Apache-2.0 |
| Capsule Mascot OBJ/MTL/manifest、Sparky OBJ/MTL/albedo、两张 imagegen PNG、两个程序化 HDR 环境、程序化 alpha 遮罩、程序化 Showcase Panel 三个运行时资产和 25 张正式 Gallery PNG | CC0-1.0（项目贡献者 dedication） |
| Spot OBJ 与 albedo 纹理 | CC0-1.0（Keenan Crane 上游 dedication） |
| third_party/tinyobjloader 下的 vendored 文件 | MIT |
| third_party/mikktspace 下 vendored 的 `mikktspace.c`/`.h` | zlib-style license |

CC0 只覆盖 assets/examples/models/CC0-1.0.txt 逐项列出的四十一个文件；其中
三十九个由项目贡献者明确 dedication，两个 Spot 文件保留 Keenan Crane 的上游
CC0 dedication。
tools/generate_mascot.py、tools/generate_hdr_environment.py、
tools/generate_showcase_panel.py、
tools/generate_assembly_hall_assets.py、
scenes/kinetic-foundry.py、scenes/lava-temple-oracle.py、
scenes/atelier.py、scenes/assembly-hall.py、
python/spectraldock/physics.py 与 tools/physx_worker.cpp 均为 Apache-2.0，
不属于 CC0。PhysX 本身是仓库外部依赖，适用其 BSD-3-Clause 许可证。
MikkTSpace 的 `mikktspace.c`/`.h` 是生成 OBJ face-corner tangent 的
vendored 第三方源码，不适用仓库级 Apache-2.0；两个文件顶部保留了
完整 zlib-style 许可声明。

所有运行时素材都位于仓库内的 `assets/examples/`，构建和运行不依赖外部素材目录。

- 图像素材的来源、原始 prompt、生成/处理参数和 SHA-256：
  [`assets/examples/manifest.md`](../assets/examples/manifest.md)
- AI 生成的 Capsule Mascot 的几何统计、材质槽、文件字节数和 SHA-256：
  [`assets/examples/models/capsule-mascot/manifest.json`](../assets/examples/models/capsule-mascot/manifest.json)
- AI 生成的 Sparky 模型、材质槽与纹理的完整清单：
  [`assets/examples/models/sparky/manifest.json`](../assets/examples/models/sparky/manifest.json)
- 程序化 Showcase Panel 的几何、数据贴图与摘要清单：
  [`assets/examples/models/showcase-panel/manifest.json`](../assets/examples/models/showcase-panel/manifest.json)
- Spot 模型、纹理、上游许可与建议引用：
  [Keenan Crane 的 CMU Model Repository](https://www.cs.cmu.edu/~kmcrane/Projects/ModelRepository/)
- 零依赖确定性模型生成器：
  `python3 tools/generate_mascot.py [--output PATH] [--manifest PATH]`
- 零依赖确定性 HDR 环境生成器：
  `python3 tools/generate_hdr_environment.py [--output PATH]`
- 零依赖确定性 Showcase Panel 生成器：
  `python3 tools/generate_showcase_panel.py [--output-dir PATH]`
- 零依赖确定性 Assembly Hall HDR/alpha 生成器：
  `python3 tools/generate_assembly_hall_assets.py [--hdr-output PATH] [--alpha-output PATH]`
- 视觉资产 CC0 范围与官方法典链接：
  [`assets/examples/models/CC0-1.0.txt`](../assets/examples/models/CC0-1.0.txt)

## 图像素材

| 文件 | 尺寸/模式 | SHA-256 |
| --- | --- | --- |
| `planet-azure.png` | 1774×887 RGB | `813e73e7b89e28098d7926093268365037fd97bc68ff91f108aad1a4099096a3` |
| `planet-ember.png` | 1774×887 RGB | `14cb336904b10e18758aa1923ad786a2651e326e4f92dd116fd689675d1d5d52` |
| `models/sparky/sparky_albedo.png` | 1024×1024 RGBA（全不透明） | `e0c5f6b728a53d3cfbc1ef6f29bd55417170d5f02c53305a7a4b1a9f931e22f0` |
| `models/spot/spot_texture.png` | 1024×1024 RGB（内嵌 sRGB profile） | `cddabbae52a666173e7953e238b88340d285044dc20b36f8ed3f1a41db534fa5` |
| `environments/radiance-pavilion.hdr` | 2048×1024 Radiance RGBE，modern RLE | `33b6e651abbacbf7458aac0c2610f96705a763251a1699e5548615ca36dbf6d7` |
| `environments/assembly-hall-noon.hdr` | 2048×1024 Radiance RGBE，modern RLE | `032f091333a6035ec2898430aec6d7b8decb8cdc2667edde52fed4040812fb07` |
| `textures/assembly-hall-gear-alpha.png` | 1024×1024 RGBA8，无色彩 profile | `7cde4cd9f598954a39197ced1b23ace5d5e452e65f8ba2dd25663606d4f110ee` |
| `models/showcase-panel/showcase-panel-normal.png` | 1024×1024 RGB8，linear，无色彩 profile，OpenGL/+Y | `aafd558f3057f2ad25e9fec041603ced9d2ebf743b5e25c1fca3752c3766fe49` |
| `models/showcase-panel/showcase-panel-metallic-roughness.png` | 1024×1024 RGB8，linear，无色彩 profile，G=roughness、B=metallic | `b9ecec85c490fc0377d4c39260cf175b98da10d5e0c8bdfd8694ea3e57109329` |

上述两张星球 PNG 为本项目通过 AI 图像生成工作流生成，按现状提供，不保证
唯一性或排他性；仅在贡献者拥有相关权利的范围内作 CC0 dedication。
两张星球图先把经度边界滚动到中央，由 imagegen 修复中央接缝，再滚回
并令首末像素列严格相同。仓库不收录原始生成图和处理中间图；prompt、
尺寸、处理步骤及 SHA-256 均保留在图像素材清单中。

`sparky_albedo.png` 是项目所有者贡献的 AI 生成 Sparky 资产组成部分，
不是上述两张星球 imagegen 输出之一。它与同目录 OBJ、MTL 一起按 CC0-1.0
提供；其 AI 来源声明、精确字节数和摘要记录在独立 Sparky manifest 中。该
`manifest.json` 是 Apache-2.0 文档 sidecar，不计入三十九项项目贡献者 CC0
文件。

`spot_texture.png` 是 Spot 上游归档中的未修改位图，不属于项目 imagegen
工作流。它保留内嵌 sRGB profile；未来场景使用时仍应通过 typed texture API
显式注册为 sRGB，并在两个方向使用 repeat wrapping 以覆盖稍微超出单位方形的
上游 UV。其来源和许可与同目录三角网格一致。

`radiance-pavilion.hdr` 不是 AI 生成图。它由 Python 标准库生成器按固定
球面解析公式构造冷色天顶、暖色分层云、低角度金色夕阳、暗青海面、太阳
反光带和远岛剪影，再按固定顺序转换为 RGBE 与 modern RLE；
文件不含时间戳或机器相关元数据。生成器按 Apache-2.0 提供，明确列出的
`.hdr` 输出按 CC0-1.0 提供。

`assembly-hall-noon.hdr` 与 `assembly-hall-gear-alpha.png` 也不是 AI 生成图。
同一个 Python 标准库生成器分别构造带小面积正午太阳热点的线性 RGBE 环境，
以及后墙齿轮的确定性 RGBA alpha mask；输出不含时间戳或机器相关元数据。
HDR 由环境重要性采样使用，PNG 通过 rectangle 的 alpha 裁剪路径使用；二者
按 CC0-1.0 提供，生成器按 Apache-2.0 提供。

两张 Showcase Panel PNG 也不是 AI 生成图；它们由 Python 标准库生成器按
整数算法确定性构造。normal map 使用渲染器约定的 OpenGL/+Y tangent-space
法线，metallic-roughness map 是 linear 数据贴图，G 通道表示 roughness、B
通道表示 metallic，R 通道固定为未使用值。两图均为 1024×1024 RGB8，不带
色彩 profile，场景必须通过 typed texture API 按 linear 数据读取，不能执行
sRGB 解码。三个运行时输出按 CC0-1.0 提供；生成器及记录字节数、摘要和几何
统计的独立 `manifest.json` 按 Apache-2.0 提供。

## 模型素材

| OBJ | 三角数 | 规格 | 许可 |
| --- | ---: | --- | --- |
| `capsule-mascot/capsule-mascot.obj` | 5,816 | Y-up、脚底 `y=0`、正面 `+Z`、无 UV/显式 normal、15 个 `usemtl` 槽 | CC0 1.0 Universal |
| `sparky/sparky.obj` | 7,284 源面 / 6,388 可渲染面 | Y-up、正面 `+Z`、完整 UV、10 个 `usemtl` 槽 | CC0 1.0 Universal |
| `spot/spot_triangulated.obj` | 5,856 | 2,930 positions、3,225 UV、无显式 normal/smoothing group/MTL、闭合三角网格 | CC0 1.0 Universal（上游） |
| `showcase-panel/showcase-panel.obj` | 2 | Y-up、正面 `+Z`、4 positions、完整 UV、1 个显式 `+Z` normal | CC0 1.0 Universal |

Capsule Mascot 是为本项目 AI 生成的模块化角色，由圆润躯干、横向面罩、双眼浮雕、非对称天线、短手臂与手套、短腿与靴子及腰带凸缘组成；不使用品牌角色的护目镜、背带裤或其他识别特征。各组件是不相交的闭合网格，并留有小型装配间隙，使纯色与介电材质都能保持清楚轮廓。

生成器只使用 Python 标准库，固定六位小数、部件顺序、顶点顺序、三角顺序
和 MTL 槽顺序。生成器本身为 Apache-2.0；它生成并提交的 OBJ、MTL 与
`capsule-mascot/manifest.json` 才属于明确列出的 CC0 范围。默认命令同时重建这三个
文件；清单记录三角数、包围盒、15 个材质槽以及 OBJ/MTL 的字节数与
SHA-256，供重建时核对。MTL 的 `Kd` 只提供互操作颜色；SpectralDock 不从
MTL 数值推断 BSDF，现有场景仍显式选择 object-wide 材质。

确定性生成器描述的是当前 Capsule Mascot 文件的可重建方式，不改变其最初
由 AI 生成的来源。Capsule Mascot 与 Sparky 都由项目所有者作为 AI 生成资产
贡献；Spot 则是保留原样的第三方 CC0 资产。

Sparky 是一个 AI 生成的履带式箱体机器人，包含塑料、金属、玻璃、彩色装饰和三块
共享同一 sRGB atlas 的屏幕。仓库原样保存 OBJ、MTL 与 PNG；MTL 用于声明
材质槽和互操作信息，SpectralDock 不从名称或 MTL 数值猜测 BSDF。场景通过
`mesh(materials={...})` 把十个 `usemtl` 名称显式映射到 typed material
handle，逐三角形材质索引仍由一份共享 mesh GAS 使用。
源 OBJ 还包含 896 个由两个完全重合坐标构成的零面积极点面；加载器只丢弃
这类无法求交的明确导出器残留，三点坐标不同但共线的退化面仍会报错。原始
文件、逐槽源面统计和实际可渲染面数均记录在 Sparky manifest 中。

Spot 是 Keenan Crane 整理的可爱斑点奶牛模型（上游称 spotted animal），
本仓库原样保留上游
`spot_triangulated.obj` 与 `spot_texture.png` 两个文件，不补造 MTL，也不修改
网格或图像。OBJ 每个 face corner 都带 UV；没有显式 normal，导入器按现有路径
为没有 smoothing group 的网格生成逐面法线，保持 flat shading。上游在 CMU
Model Repository 中将模型和关联数据置于
CC0-1.0，并说明可用于任何用途。CC0 不要求署名；上游仍建议论文作者考虑引用
Keenan Crane、Ulrich Pinkall、Peter Schröder，〈Robust fairing via conformal
curvature flow〉，ACM Transactions on Graphics 32(4)，2013。

Showcase Panel 是项目为 PBR 和 tangent-space normal mapping 展示而设计的
程序化平面，不属于 Capsule Mascot/Sparky 的 AI 生成资产，也没有第三方上游。
OBJ 仅由两个三角形组成，每个 face corner 都带完整 UV 和显式 `+Z` normal；
其 `d907577a7da1ea01eded6ca26cde4cce0553e4f0559e211973f51d3cf5b0e5f1`
摘要及两张数据贴图的摘要均由同目录 Apache-2.0 manifest 记录。

## Gallery

`docs/gallery/` 下共二十五张 PNG，均是 SpectralDock 渲染器输出并按
CC0-1.0 提供，不是 AI 图像生成输出。其中原有十张教学场景图继续保留；
`showcase/` 下按 Tidal Observatory、Atelier、Assembly Hall 排列三张
2560×1440 综合能力展示，
`comparisons/` 下十二张 1024×1024 图组成六组同场景、同局部的 feature
OFF/ON 对比：normal mapping、indirect lighting、environment importance
sampling、OptiX Denoiser、Beer absorption 和 firefly contribution clamping。

原有十张图各自的同名 `*.stats.json` 是正式 RTX 5090 运行记录，按
Apache-2.0 提供。十五张新的综合展示/对比图不提交临时 stats 或 physics sidecar，
也不作为性能 benchmark 或逐像素 golden。用于生成它们的 Python 场景程序
按 Apache-2.0 提供；图像本身才属于 CC0 清单。

Kinetic Foundry 与 Lava Temple Oracle 还各带有
同 stem 的 `.physics.json`，用于记录 PhysX 版本、设备、模拟参数和刚体
结果摘要；这些 sidecar 按
Apache-2.0 提供，不属于 CC0。运行过程不生成中间场景 JSON。

PhysX GPU 不支持 enhanced determinism；固定输入的重复模拟可能得到不同的
有效姿态。gallery 保存的是一次通过场景契约和人工构图检查的运行记录，不是
可由 seed 逐字节重建的物理 golden。“熔岩圣殿的机械先知”PNG 作为视觉
资产按 CC0 提供；定义并求解其 130 个动态 actor 的 Python 场景程序、
physics API、PhysX worker、契约测试、渲染 stats 和 physics sidecar 均是
Apache-2.0 项目材料。
