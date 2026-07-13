# 示例素材与许可

## 许可矩阵

| 范围 | 许可证 |
| --- | --- |
| 代码、脚本、Python/C++ 生成器、文档、场景 JSON、SVG、测试 fixture、素材 sidecar、gallery stats 与物理生成 sidecar | Apache-2.0 |
| capsule-mascot.obj、model-manifest.json、四张运行时纹理和正式 gallery PNG | CC0-1.0 |
| third_party/tinyobjloader 下的 vendored 文件 | MIT |

CC0 只覆盖 assets/examples/models/CC0-1.0.txt 逐项列出的十四个文件。
tools/generate_mascot.py、tools/generate_benchmark_harbor.py、
tools/generate_physx_kinetic_foundry.cpp 和 tools/check_physx_scene.py
均为 Apache-2.0，不属于 CC0。PhysX 本身是仓库外部依赖，适用其
BSD-3-Clause 许可证。

所有运行时素材都位于仓库内的 `assets/examples/`，容器不挂载外部素材目录。

- 图像素材的原始 prompt、生成尺寸、处理参数和 SHA-256：
  [`assets/examples/manifest.md`](../assets/examples/manifest.md)
- 原创胶囊吉祥物的几何统计、包围盒、字节数和 SHA-256：
  [`assets/examples/model-manifest.json`](../assets/examples/model-manifest.json)
- 零依赖确定性模型生成器：
  `python3 tools/generate_mascot.py [--output PATH] [--manifest PATH]`
- 视觉资产 CC0 范围与官方法典链接：
  [`assets/examples/models/CC0-1.0.txt`](../assets/examples/models/CC0-1.0.txt)

## 图像素材

| 文件 | 尺寸/模式 | SHA-256 |
| --- | --- | --- |
| `planet-azure.png` | 1774×887 RGB | `813e73e7b89e28098d7926093268365037fd97bc68ff91f108aad1a4099096a3` |
| `planet-ember.png` | 1774×887 RGB | `14cb336904b10e18758aa1923ad786a2651e326e4f92dd116fd689675d1d5d52` |
| `koi-mask.png` | 1024×1536 RGBA | `fd4376986b5622043fdb63386bc02450f9ec162d7f4517ebb154e45e3052bf60` |
| `circuit-panel.png` | 1536×1024 RGB | `9361c04d5fab6098676cee2f65efb8d222246ddba0b1828a7ab4088f9f05f0be` |

这些图像为本项目通过 AI 图像生成工作流生成，按现状提供，不保证
唯一性或排他性；仅在贡献者拥有相关权利的范围内作 CC0 dedication。
两张星球图先把经度边界滚动到中央，由 imagegen 修复中央接缝，再滚回
并令首末像素列严格相同；锦鲤先生成在平坦绿幕上，再生成透明 PNG。
仓库不收录原始生成图和处理中间图；prompt、尺寸、处理步骤及
SHA-256 均保留在图像素材清单中。

只有 circuit-panel.png 保留内嵌 caBX/JUMBF C2PA 结构，其中标识
OpenAI Media Service；仓库保留该结构，但不验证其密码学有效性。另外
三张后处理纹理不含 C2PA。manifest.md 是普通的未签名
sidecar，不应解释为签名来源声明。

## 模型素材

| OBJ | 三角数 | 规格 | 许可 |
| --- | ---: | --- | --- |
| `capsule-mascot.obj` | 5,816 | Y-up、脚底 `y=0`、正面 `+Z`、无 UV/MTL | CC0 1.0 Universal |

胶囊吉祥物为本项目原创模块化角色，由圆润躯干、横向面罩、双眼浮雕、非对称天线、短手臂与手套、短腿与靴子及腰带凸缘组成；不使用品牌角色的护目镜、背带裤或其他识别特征。各组件是不相交的闭合网格，并留有小型装配间隙，使纯色与介电材质都能保持清楚轮廓。

生成器只使用 Python 标准库，固定六位小数、部件顺序、顶点顺序和
三角顺序。生成器本身为 Apache-2.0；它生成并提交的 OBJ 与
model-manifest.json 才属于明确列出的 CC0 范围。默认命令同时重建 OBJ
与清单；清单记录三角数、闭合边、包围盒、字节数与 SHA-256，供重建时
核对。模型颜色和 BSDF 完全来自场景材质。

## Gallery

docs/gallery 下八张 PNG 按 CC0-1.0 提供；同名 *.stats.json 是正式
RTX 5090 运行记录，按 Apache-2.0 提供。gallery 图像是渲染器输出，
不含 C2PA 来源凭据。Kinetic Foundry 还带有同 stem 的 `.physics.json`，
用于记录 PhysX 版本、设备、模拟参数和临时场景摘要；该 sidecar 按
Apache-2.0 提供，不属于 CC0。中间场景 JSON 不提交到仓库。

PhysX GPU 不支持 enhanced determinism；固定输入的重复模拟可能得到不同的
有效姿态。gallery 保存的是一次通过场景契约和人工构图检查的运行记录，不是
可由 seed 逐字节重建的物理 golden。
