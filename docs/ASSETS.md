# 示例素材与许可

## 许可矩阵

| 范围 | 许可证 |
| --- | --- |
| 代码、脚本、Python 场景程序、C++ worker、文档、SVG、测试 fixture、图像与 Sparky manifest、gallery stats 与物理 sidecar | Apache-2.0 |
| capsule mascot、Sparky OBJ/MTL/albedo、`model-manifest.json`、四张 imagegen PNG、程序化 HDR 环境和正式 gallery PNG | CC0-1.0 |
| third_party/tinyobjloader 下的 vendored 文件 | MIT |

CC0 只覆盖 assets/examples/models/CC0-1.0.txt 逐项列出的二十个文件。
tools/generate_mascot.py、tools/generate_hdr_environment.py、
scenes/kinetic-foundry.py、scenes/lava-temple-oracle.py、
python/spectraldock/physics.py 与 tools/physx_worker.cpp 均为 Apache-2.0，
不属于 CC0。PhysX 本身是仓库外部依赖，适用其 BSD-3-Clause 许可证。

所有运行时素材都位于仓库内的 `assets/examples/`，构建和运行不依赖外部素材目录。

- 图像素材的原始 prompt、生成尺寸、处理参数和 SHA-256：
  [`assets/examples/manifest.md`](../assets/examples/manifest.md)
- 原创胶囊吉祥物的几何统计、包围盒、字节数和 SHA-256：
  [`assets/examples/model-manifest.json`](../assets/examples/model-manifest.json)
- 原创 Sparky 模型、材质槽与纹理的完整清单：
  [`assets/examples/models/sparky/manifest.json`](../assets/examples/models/sparky/manifest.json)
- 零依赖确定性模型生成器：
  `python3 tools/generate_mascot.py [--output PATH] [--manifest PATH]`
- 零依赖确定性 HDR 环境生成器：
  `python3 tools/generate_hdr_environment.py [--output PATH]`
- 视觉资产 CC0 范围与官方法典链接：
  [`assets/examples/models/CC0-1.0.txt`](../assets/examples/models/CC0-1.0.txt)

## 图像素材

| 文件 | 尺寸/模式 | SHA-256 |
| --- | --- | --- |
| `planet-azure.png` | 1774×887 RGB | `813e73e7b89e28098d7926093268365037fd97bc68ff91f108aad1a4099096a3` |
| `planet-ember.png` | 1774×887 RGB | `14cb336904b10e18758aa1923ad786a2651e326e4f92dd116fd689675d1d5d52` |
| `koi-mask.png` | 1024×1536 RGBA | `fd4376986b5622043fdb63386bc02450f9ec162d7f4517ebb154e45e3052bf60` |
| `circuit-panel.png` | 1536×1024 RGB | `9361c04d5fab6098676cee2f65efb8d222246ddba0b1828a7ab4088f9f05f0be` |
| `models/sparky/sparky_albedo.png` | 1024×1024 RGBA（全不透明） | `e0c5f6b728a53d3cfbc1ef6f29bd55417170d5f02c53305a7a4b1a9f931e22f0` |
| `environments/radiance-pavilion.hdr` | 2048×1024 Radiance RGBE，modern RLE | `33b6e651abbacbf7458aac0c2610f96705a763251a1699e5548615ca36dbf6d7` |

上述四张 PNG 为本项目通过 AI 图像生成工作流生成，按现状提供，不保证
唯一性或排他性；仅在贡献者拥有相关权利的范围内作 CC0 dedication。
两张星球图先把经度边界滚动到中央，由 imagegen 修复中央接缝，再滚回
并令首末像素列严格相同；锦鲤先生成在平坦绿幕上，再生成透明 PNG。
仓库不收录原始生成图和处理中间图；prompt、尺寸、处理步骤及
SHA-256 均保留在图像素材清单中。

`sparky_albedo.png` 是项目所有者直接贡献的原创 Sparky 资产组成部分，
不是上述 imagegen 工作流的输出。它与同目录 OBJ、MTL 一起按 CC0-1.0
提供；其来源声明、精确字节数和摘要记录在独立 Sparky manifest 中。该
`manifest.json` 是 Apache-2.0 文档 sidecar，不计入二十项 CC0 文件。

只有 circuit-panel.png 保留内嵌 caBX/JUMBF C2PA 结构，其中标识
OpenAI Media Service；仓库保留该结构，但不验证其密码学有效性。另外
三张后处理纹理不含 C2PA。manifest.md 是普通的未签名
sidecar，不应解释为签名来源声明。

`radiance-pavilion.hdr` 不是 AI 生成图。它由 Python 标准库生成器按固定
球面解析公式构造冷色天顶、暖色分层云、低角度金色夕阳、暗青海面、太阳
反光带和远岛剪影，再按固定顺序转换为 RGBE 与 modern RLE；
文件不含时间戳或机器相关元数据。生成器按 Apache-2.0 提供，明确列出的
`.hdr` 输出按 CC0-1.0 提供。

## 模型素材

| OBJ | 三角数 | 规格 | 许可 |
| --- | ---: | --- | --- |
| `capsule-mascot.obj` | 5,816 | Y-up、脚底 `y=0`、正面 `+Z`、无 UV/MTL | CC0 1.0 Universal |
| `sparky/sparky.obj` | 7,284 源面 / 6,388 可渲染面 | Y-up、正面 `+Z`、完整 UV、10 个 `usemtl` 槽 | CC0 1.0 Universal |

胶囊吉祥物为本项目原创模块化角色，由圆润躯干、横向面罩、双眼浮雕、非对称天线、短手臂与手套、短腿与靴子及腰带凸缘组成；不使用品牌角色的护目镜、背带裤或其他识别特征。各组件是不相交的闭合网格，并留有小型装配间隙，使纯色与介电材质都能保持清楚轮廓。

生成器只使用 Python 标准库，固定六位小数、部件顺序、顶点顺序和
三角顺序。生成器本身为 Apache-2.0；它生成并提交的 OBJ 与
model-manifest.json 才属于明确列出的 CC0 范围。默认命令同时重建 OBJ
与清单；清单记录三角数、闭合边、包围盒、字节数与 SHA-256，供重建时
核对。模型颜色和 BSDF 完全来自场景材质。

Sparky 是一个履带式箱体机器人，包含塑料、金属、玻璃、彩色装饰和三块
共享同一 sRGB atlas 的屏幕。仓库原样保存 OBJ、MTL 与 PNG；MTL 用于声明
材质槽和互操作信息，SpectralDock 不从名称或 MTL 数值猜测 BSDF。场景通过
`mesh(materials={...})` 把十个 `usemtl` 名称显式映射到 typed material
handle，逐三角形材质索引仍由一份共享 mesh GAS 使用。
源 OBJ 还包含 896 个由两个完全重合坐标构成的零面积极点面；加载器只丢弃
这类无法求交的明确导出器残留，三点坐标不同但共线的退化面仍会报错。原始
文件、逐槽源面统计和实际可渲染面数均锁定在 Sparky manifest 与测试中。

## Gallery

docs/gallery 下十张 PNG 按 CC0-1.0 提供；同名 *.stats.json 是正式
RTX 5090 运行记录，按 Apache-2.0 提供。gallery 图像是渲染器输出，
不含 C2PA 来源凭据。Kinetic Foundry 与 Lava Temple Oracle 还各带有
同 stem 的 `.physics.json`，用于记录 PhysX 版本、设备、模拟参数和刚体
结果摘要；这些 sidecar 按
Apache-2.0 提供，不属于 CC0。运行过程不生成中间场景 JSON。

PhysX GPU 不支持 enhanced determinism；固定输入的重复模拟可能得到不同的
有效姿态。gallery 保存的是一次通过场景契约和人工构图检查的运行记录，不是
可由 seed 逐字节重建的物理 golden。“熔岩圣殿的机械先知”PNG 作为视觉
资产按 CC0 提供；定义并求解其 130 个动态 actor 的 Python 场景程序、
physics API、PhysX worker、契约测试、渲染 stats 和 physics sidecar 均是
Apache-2.0 项目材料。
