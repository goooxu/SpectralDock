# 示例画廊：综合展示与特性对比

本页只展示两类正式图片：一张覆盖大部分渲染能力的综合场景，以及六组在同一
场景、同一相机局部下只改变一个变量的 OFF/ON 对比。每张 PNG 都是
SpectralDock renderer 的直接输出，不包含拼接、文字叠加或其他像素后处理。

Gallery 生产程序默认写入 `output/gallery/`，不会覆盖本页图片。正式图片通过
人工构图与数值安全检查后才晋升到 `docs/gallery/`；按项目所有者要求，新图
不提交临时渲染机生成的 stats sidecar，也不作为跨 GPU 像素 golden 或性能
基线。原有十个教学场景、历史 PNG/stats 与技术报告记录继续保留，但不再占用
首页和本页的主展示顺序。

## 第一类：综合能力展示

### Tidal Observatory / 暮潮观测站

![暮潮观测站](gallery/showcase/tidal-observatory.png)

暮潮观测站坐落在日落后的海岸平台。Spot 位于中央检修台，Sparky 操作显式
映射十个 OBJ `usemtl` 槽的光学设备，Capsule Mascot 在侧台校准带法线纹理
的金属样片。Spot 的上游 sRGB albedo、Sparky 的共享屏幕 atlas、Capsule 的
十五槽材质和重复使用的 mesh GAS 在同一构图中保留各自清晰的读形。

低角度 Radiance HDR 天光与 rectangle、sphere 有限灯共同刻画陶瓷、粗糙
金属、铬、低粗糙度 PBR 光学外壳和 metallic-roughness PBR 表面；前景有限解析波浪水池通过
粗糙介电 Fresnel、介质栈与 RGB Beer 吸收映出冷暖交错的倒影，远侧 flame
信标以吸收—自发光体积补充暖色层次。观测设备还使用 disk、cylinder、sphere
和 parabola，材质样片以 MikkTSpace tangent frame 读取 OpenGL/+Y normal
map。环境与有限灯进入同一 NEE/MIS 路径，最终画面使用轻微景深和 OptiX
Denoiser。

两枚镜头是不透明的低粗糙度 PBR 光学外壳，不声称玻璃透射。这避免在同一幅
高样本解析水面图中额外引入独立介质边界；真实 dielectric 的 Fresnel/Snell
路径仍由 Material Cathedral、Radiance Pavilion 和定向 GPU fixture 覆盖。

该场景不运行 PhysX，所有姿态固定。正式参数为 2560×1440、1024 spp、
depth 12、seed 909、importance direct-light sampling、direct clamp 64、
indirect clamp 16 和 Denoiser ON。

## 第二类：单特性 OFF/ON 对比

所有单图均为 1024×1024。每一对固定相机、几何、灯光、曝光和随机种子，
只改变标题列出的目标变量；不同对之间可以使用不同场景和样本预算。

### 法线贴图 Normal Mapping

| OFF（`normal_scale=0`） | ON（`normal_scale=1`） |
| --- | --- |
| ![关闭法线贴图](gallery/comparisons/normal-mapping-off.png) | ![启用法线贴图](gallery/comparisons/normal-mapping-on.png) |

同一张 linear normal texture 在两侧都已绑定，OBJ、UV、MikkTSpace frame、
metallic-roughness 参数和掠射主光也完全相同。OFF 侧将强度设为零；ON 侧只
改变切线空间着色法线，因此轮廓不变而沟槽高光和细部明暗出现。正式图使用
512 spp、depth 8、seed 3301、无降噪和 clamp 0/0。

### 间接光 Indirect Lighting

| OFF（`depth=1`） | ON（`depth=12`） |
| --- | --- |
| ![仅直接光](gallery/comparisons/indirect-light-off.png) | ![多次反弹间接光](gallery/comparisons/indirect-light-on.png) |

双色漫反射回廊由同一盏有限面积灯照明。`depth=1` 仍在首个表面执行直接光
NEE，但不会继续传播；`depth=12` 允许暗部填充和墙面色彩串扰。场景刻意不放
玻璃和镜面物体，避免把反射层数误写成漫反射 GI。正式图使用 512 spp、
seed 1101、无降噪和 clamp 0/0。

### 环境重要性采样 Importance Sampling

| OFF（`uniform`） | ON（`importance`） |
| --- | --- |
| ![均匀方向采样](gallery/comparisons/environment-importance-off.png) | ![环境重要性采样](gallery/comparisons/environment-importance-on.png) |

HDR 光学台只由带小面积太阳热点的环境贴图照明，chrome parabola 与玻璃元件
放大低样本噪声差异。两侧都执行 NEE/MIS，并在收敛后得到同一均值；ON 侧
只把方向分布改为亮度与 texel 立体角重要性采样。正式图使用 16 spp、
depth 12、seed 2201、无降噪和 clamp 0/0。

### AI 降噪 OptiX Denoiser

| OFF（原始 16 spp） | ON（相同样本 + Denoiser） |
| --- | --- |
| ![未经降噪](gallery/comparisons/denoiser-off.png) | ![OptiX AI 降噪](gallery/comparisons/denoiser-on.png) |

两侧复用同一个冻结后的漫反射回廊 Renderer，并以同一 seed 重新生成完全相同
的 Monte Carlo 样本；唯一差异是 `denoise=False/True`。正式图使用 16 spp、
depth 12、seed 1102 和相同的 direct/indirect clamp 64/16。该对比观察低频
阴影与间接光噪声降低时，首命中几何边缘和材质分区是否仍被保留。

### 水下吸收 Beer Absorption

| OFF（`absorption=(0,0,0)`） | ON（RGB Beer 吸收） |
| --- | --- |
| ![关闭水下吸收](gallery/comparisons/beer-absorption-off.png) | ![启用水下吸收](gallery/comparisons/beer-absorption-on.png) |

两侧保留同一个 `water_surface`、解析波浪、粗糙度、IOR、照明和位于不同水深
的中性参照物；ON 侧只把吸收系数改为 `(0.45, 0.09, 0.025)`，使传播距离
增加时出现选择性青蓝衰减。正式图使用 512 spp、depth 12、seed 808、无
降噪和 clamp 0/0。

### Firefly 钳位 Contribution Clamping

| OFF（direct/indirect `0/0`） | ON（direct/indirect `64/16`） |
| --- | --- |
| ![关闭贡献钳位](gallery/comparisons/firefly-clamp-off.png) | ![启用贡献钳位](gallery/comparisons/firefly-clamp-on.png) |

该对比复用 HDR 光学台与 importance sampling，使用 32 spp、depth 12、
seed 909 和无降噪输出。钳位 helper 不改变随机数序列；ON 侧只限制少数极端
路径贡献，以减少展示图中的亮点。它是有偏的稳定化策略，不代表更准确；能量
或收敛实验仍必须使用 0/0。

## 运行 Gallery 程序

```bash
source ./scripts/activate.sh Release

# 低成本构图预览；所有输出和临时 stats 留在 output/gallery/
python3 scenes/tidal-observatory.py --preview
python3 scenes/compare-light-transport.py --preview
python3 scenes/compare-hdr-sampling.py --preview
python3 scenes/compare-normal-mapping.py --preview
python3 scenes/compare-water-absorption.py --preview

# 正式质量；每个程序也可用 --device 和 --output-dir 明确选择设备与目录
python3 scenes/tidal-observatory.py
python3 scenes/compare-light-transport.py
python3 scenes/compare-hdr-sampling.py
python3 scenes/compare-normal-mapping.py
python3 scenes/compare-water-absorption.py
```

同一 ON/OFF 对应在同一 GPU、同一进程内顺序生成；多个独立程序可以通过外部
多进程调度分配到不同 GPU。这不改变 Renderer “一次渲染使用一张 GPU”的
边界，也不是多 GPU 单帧渲染。

## 保留的教学程序索引

以下十个普通 Python 程序及历史渲染记录继续保留，供专题阅读、性能记录和
PhysX 复现使用，但它们的旧图片不再出现在本页主展示中：

- `material-cathedral.py`：PBR、metal、dielectric 与共享 mesh。
- `radiance-pavilion.py`：HDR 唯一光源与显式多材质 Sparky。
- `neon-koi.py`：发光几何、彩色间接光与景深。
- `celestial-archive.py`：球面纹理、天空和玻璃天体。
- `reflector-laboratory.py`：parabola、point/directional 灯和钳位。
- `benchmark-harbor.py`：大 IAS、共享 GAS 与 BVH 吞吐。
- `ember-forge.py`：异质吸收—自发光 flame 体积。
- `moonlit-stepwell.py`：粗糙解析水面、介质栈与 Beer 吸收。
- `kinetic-foundry.py`：即时 PhysX GPU 刚体场景。
- `lava-temple-oracle.py`：预碎裂刚体爆发、水面与体积组合的 PhysX 专题场景。

原有 RTX 5090 运行记录见 [BENCHMARK.md](BENCHMARK.md)，PhysX 边界见
[PHYSX_SCENE.md](PHYSX_SCENE.md)，素材来源与 CC0 范围见
[ASSETS.md](ASSETS.md)。
