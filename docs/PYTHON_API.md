# Python 场景 API

SpectralDock 的场景就是普通 Python 程序。项目没有场景文件格式、场景注册表或接收脚本路径的渲染主程序；直接执行脚本即可构建并渲染：

```bash
source scripts/activate.sh
python3 scenes/neon-koi.py
```

用户场景与仓库示例使用完全相同的 API。脚本负责创建 `Renderer`、添加资源、调用 `render()`，并明确指定输出文件名和渲染参数。

## 最小程序

```python
from pathlib import Path

from spectraldock import Renderer


output = Path("output/first-light.png")
renderer = Renderer(device=0, scene_name="first-light")
renderer.integrator(
    direct_light_sampling="importance",
    clamp_direct=64.0,
    clamp_indirect=16.0,
)
renderer.camera(
    look_from=(0.0, 1.5, 5.0),
    look_at=(0.0, 0.8, 0.0),
    vfov=42.0,
)
renderer.background(type="constant", color=(0.002, 0.003, 0.006))

floor = renderer.material(
    name="floor",
    type="lambertian",
    base_color=(0.18, 0.20, 0.24),
)
ball = renderer.material(
    name="ball",
    type="metal",
    base_color=(0.70, 0.28, 0.08),
    roughness=0.22,
)
renderer.object(
    name="floor",
    type="rectangle",
    p1=(-4.0, 0.0, 3.0),
    p2=(-4.0, 0.0, -3.0),
    p3=(4.0, 0.0, -3.0),
    material=floor,
)
renderer.object(
    name="ball",
    type="sphere",
    center=(0.0, 1.0, 0.0),
    radius=1.0,
    material=ball,
)
renderer.light(
    name="key",
    type="point",
    position=(-2.0, 4.0, 3.0),
    intensity=(180.0, 150.0, 110.0),
)
renderer.render(
    output=output,
    stats_output=output.with_suffix(".stats.json"),
    width=640,
    height=360,
    spp=32,
    depth=8,
    seed=1,
    denoise=True,
)
```

`Renderer` 不猜测脚本位置，也不重写资产或输出路径。相对路径按启动 Python 时的当前工作目录解释；需要与脚本位置绑定时，应像内置示例一样用 `Path(__file__).resolve()` 自行构造绝对路径。

## Renderer 与 typed handle

```python
renderer = Renderer(device=0, scene_name="optional-stats-label")
```

`texture()`、`material()`、`mesh()` 和 `object()` 返回各自的 typed handle。引用关系直接传 handle，而不是传资源名称字符串；`light()` 是终端注册操作，成功时返回 `None`：

```python
albedo = renderer.texture(
    name="paint", type="image", path=Path("assets/paint.png"), color_space="srgb"
)
paint = renderer.material(
    name="paint", type="lambertian", texture=albedo
)
panel = renderer.object(
    name="panel", type="rectangle",
    p1=(-1.0, 0.0, 0.0), p2=(-1.0, 2.0, 0.0), p3=(1.0, 2.0, 0.0),
    material=paint,
)
renderer.light(
    name="panel-light", type="rectangle", object=panel,
    position=(-1.0, 0.0, 0.0), edge_u=(0.0, 2.0, 0.0),
    edge_v=(2.0, 0.0, 0.0), emission=(8.0, 6.0, 4.0),
)
```

handle 只能交回创建它的同一个 `Renderer`。名称只用于调试、统计和可读性，API 不提供按名称重新查询 handle 的注册表。`Renderer` 也不提供 `gpu_enabled` 探测属性；是否具备 GPU renderer 由构建配置决定，无 GPU 构建调用 `render()` 时会直接报告错误。

## 相机、积分器与背景

- `integrator(direct_light_sampling="importance", clamp_direct=64, clamp_indirect=16)`：直接光选择可用 `importance` 或 `uniform`；clamp 为 0 时关闭相应的有偏 firefly 抑制。
- `camera(look_from=..., look_at=..., up=(0,1,0), vfov=45, aperture=0, focus_distance=...)`
- `background(type="constant", color=..., exposure=...)`
- `background(type="sky", bottom=..., top=..., sun_direction=..., sun_color=..., sun_cos_angle=..., exposure=...)`
- `background(type="environment", path=..., intensity=1, rotation_degrees=0, exposure=...)`

环境贴图接受 Radiance RGBE `.hdr`。重要性模式按线性亮度和 texel 立体角构造分布；路径必须由调用代码明确给出。

## 纹理与材质

`texture(name, type, ...)` 支持：

- `constant`：`color=(r,g,b)`；
- `image`：`path=...`，`color_space="srgb" | "linear"`。

`material(name, type, ...)` 支持：

- `lambertian`：`texture` 或 `base_color`；
- `metal`：`texture`/`base_color` 与 `roughness`；
- `dielectric`：`texture`/`base_color`、`roughness` 与 `ior`；
- `emitter`：`texture`/`base_color` 与 `emission`；
- `water`：`roughness`、`ior` 与 RGB `absorption`。

水材质不接受普通表面纹理、`base_color` 或 `emission`。

## 几何

`object(name, type, ...)` 支持下列 `type`：

- `sphere`：`center`、`radius`；
- `rectangle`：连续角点 `p1`、`p2`、`p3`，可选 `alpha_texture` 与 `alpha_cutoff`；
- `disk`：`center`、`normal`、`radius`；
- `cylinder`：`base`、`axis`、`height`、`radius`；
- `parabola`：`origin`、`normal`、`focus`、`clip_min` 和 `clip_max`；
- `mesh`：由 `mesh(name, path, materials=...)` 返回的 `mesh` handle，以及可选 `translate`、`rotate_degrees`、`scale`；
- `water_surface`：`center`、二维 `size`、一个 water `material` 与最多四项 `waves`。

普通表面可传一个共享 `material`，或分别传 `front_material`、`back_material`；也可传 `alpha_texture` 与 `alpha_cutoff`。`water_surface` 只接受一个共享 water 材质。

波项是普通 mapping：

```python
waves=(
    {"direction": (1.0, 0.2), "amplitude": 0.08,
     "wavelength": 2.5, "phase_radians": 0.0},
)
```

OBJ 通过 `mesh()` 加载。省略 `materials` 或传入空 mapping 时继续使用
legacy 模式：不读取 `mtllib`/`usemtl`，由每个 mesh object 的 `material` 或
front/back material 统一着色。多材质 OBJ 则在创建 mesh resource 时显式给出
非空槽映射：

```python
screen_albedo = renderer.texture(
    name="screen-albedo", type="image",
    path=Path("assets/robot-screen.png"), color_space="srgb",
)
screen = renderer.material(
    name="screen", type="lambertian", texture=screen_albedo
)
body = renderer.material(
    name="body", type="lambertian", base_color=(0.35, 0.65, 0.9)
)
robot = renderer.mesh(
    name="robot",
    path=Path("assets/robot.obj"),
    materials={"Body": body, "Screen": screen},
)
renderer.object(
    name="robot-instance", type="mesh", mesh=robot,
    translate=(0.0, 0.0, 0.0),
)
```

非空 `materials` 是 `usemtl` 名称到同一 Renderer 所属 `MaterialHandle` 的
mapping，并启用严格模式。加载器读取 OBJ 及其 sibling MTL 来解析每个三角形的
槽名；映射键必须与实际使用的槽集合精确一致，而且每个三角形都必须有有效
`usemtl` assignment。`Kd`、`map_Kd`、`illum`、材质名及其他 MTL 字段都不会
自动创建 texture、material 或 BSDF；Python 传入的 typed handle 是唯一材质
定义。

严格映射会在 mesh resource 上保存每个三角形一个全局材质 ID。同一 resource
仍只构建一份 GAS，所有实例共享这张逐 primitive 表；如需另一套槽材质，应创建
另一个 mesh resource，也会得到另一份 GAS。mapped mesh object 不能再传
`material`、`front_material` 或 `back_material`，每个三角形的正反面使用同一
槽材质；`alpha_texture` 与 `alpha_cutoff` 仍是 object-wide 设置。

若任一已绑定材质或 alpha 使用纹理，OBJ 必须具备完整 UV。变换顺序为
$T R_z R_y R_x S$，旋转单位为度。mesh 实例只接受平铺的 `translate`、
`rotate_degrees` 和 `scale` 参数，不接受嵌套 `transform` mapping；对象类型固定为
`mesh`，没有 `mesh_instance` 别名。

## 灯光

`light(name, type, ...)` 支持：

- `sphere`：`position`、`radius`、`emission`；
- `rectangle`：`position`、`edge_u`、`edge_v`、`emission`；
- `disk`：`position`、`normal`、`radius`、`emission`；
- `flame`：`position`、`axis`、`height`、`radius_start`、`radius_end`、`emission_start`、`emission_end`、`extinction`，以及可选 `density_scale`、`turbulence`、`noise_scale`、`seed`；
- `point`：`position`、`intensity`；
- `directional`：从表面指向光源的 `direction` 与 `irradiance`。

前三种有限面光可通过 `object=<ObjectHandle>` 绑定可见发光几何；绑定时几何与灯的形状必须一致。flame、point 和 directional 不绑定对象。

## 渲染与输出

```python
stats = renderer.render(
    output=Path("output/frame.png"),
    stats_output=Path("output/frame.stats.json"),
    linear_output=Path("output/frame.pfm"),
    width=1920,
    height=1080,
    spp=512,
    depth=12,
    seed=1,
    denoise=True,
    validation=False,
)
```

- `output` 必须为 `.png`；父目录会按显式路径创建。
- `linear_output` 可选，必须为线性 RGB `.pfm`。
- `stats_output` 省略时默认为与 PNG 同 stem 的 `.stats.json`。
- `depth` 设置最大表面事件数。
- 曝光属于 `background(..., exposure=...)`，不是 `render()` 参数。
- `render()` 返回与 sidecar 相同的 Python `dict`。
- 首次 `render()` 会冻结场景；之后可用不同输出参数再次渲染，但不能再添加场景内容。

## PhysX 场景

物理场景仍是直接执行的同一类 Python 程序。它显式创建 `PhysicsWorld`、添加刚体/碰撞形状并调用 `simulate()`；`PhysicsResult.apply_to(renderer)` 把选定时刻的刚体姿态应用到 renderer attachments。没有 PhysX 场景生成器命令、场景名分派器或持久化场景中间文件。详见 [PhysX Python API](PHYSX_SCENE.md)。

## 内置程序

`scenes/` 中十个 `.py` 都是完整范例，最适合从与需求最接近的一个开始修改。批量执行脚本只是便利入口：

```bash
./scripts/render-examples.sh
```

它逐个执行这些 Python 文件，不接收场景参数，也不解释场景内容。
