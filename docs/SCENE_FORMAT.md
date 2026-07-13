# 场景格式

场景为 JSON，统一使用 `schema_version: 4`。当前 schema 同时包含 OBJ mesh、程序化 `flame` 体积光和运行时 `water_surface`；旧版本不再作为输入接口。未知引用、缺失资源、非有限数、退化几何和非法材质会在 CUDA/OptiX 初始化前报错。

## 顶层字段

- `camera`：`look_from`、`look_at`、`up`、`vfov`/`vertical_fov_degrees`、`aperture`、`focus_distance`。
- `background`：`constant`，或带渐变和太阳瓣的 `sky`；`exposure` 以 EV 表示。
- `render`：`width`、`height`、`spp`、`max_depth`、`seed`、`denoise`。
- `textures`：`constant` 或 PNG `image`，色彩空间为 `srgb`/`linear`。
- `materials`：`lambertian`、`metal`、`dielectric`、`emitter` 和 `water`。
- `meshes`：命名 OBJ 资源。
- `objects`：sphere、rectangle、sketch、disk、cylinder、parabola、mesh 和 water_surface。
- `lights`：显式采样的 rectangle、disk、sphere 面积光和 flame 体积光。

`max_depth` 的范围为 1–64，语义是最多处理的表面事件数；最后一个事件完整估计显式直接光，但不再生成下一事件的 BSDF 射线。

## OBJ 网格与实例

```json
{
  "schema_version": 4,
  "meshes": [
    {"name": "mascot", "path": "../assets/examples/models/capsule-mascot.obj"}
  ],
  "objects": [
    {
      "name": "mascot_instance",
      "type": "mesh",
      "mesh": "mascot",
      "transform": {
        "translate": [0, 0, 0],
        "rotate_degrees": [0, 30, 0],
        "scale": [1, 1, 1]
      },
      "material": "ceramic"
    }
  ]
}
```

变换顺序固定为先缩放，再绕 X/Y/Z 旋转，最后平移，即 `T * Rz * Ry * Rx * S`。缩放三个分量必须严格大于零；非 mesh 对象出现 `transform` 会被拒绝。

导入器合并全部 group，自动三角化多边形，支持正/负索引以及独立 position/normal/UV 索引。`mtllib`/`usemtl` 被忽略，材质、纹理、alpha 和正反面完全由 JSON 决定。完整 OBJ 法线执行重心插值；只要存在缺失法线，就按 smoothing group 生成面积加权法线，`s off` 使用面法线。UV 必须对所有角完整；PNG 采样只在设备侧执行一次顶部原点转换。绑定图像/alpha 纹理但无完整 UV 会明确报错。

同一 mesh 资源只上传并构建一份压缩 GAS。每个对象仍有独立 IAS transform、instance id、SBT offset、正反面材质和 alpha 配置。front/back 由真实三角几何法线判定，着色法线经插值并约束到几何法线同半球。

## 材质、正反面与灯

对象可用 `material` 同时设置两面，也可分别使用 `front_material`、`back_material`；null/缺失的一面透明。rectangle 的正面法线为 `normalize(cross(p3-p2, p2-p1))`。sketch 需要 `alpha_texture`，可设置 `alpha_cutoff`。

绑定到发光对象的显式灯必须与对象形状、位置、发光面和常量 emission 完全一致。带纹理 emitter 和 mesh emitter 不能成为显式采样灯，但可由路径命中后发光。

## 程序化 flame 体积光

```json
{
  "name": "rocket_plume",
  "type": "flame",
  "position": [0.0, 4.02, -2.5],
  "axis": [0.0, -1.0, 0.0],
  "height": 2.35,
  "radius_start": 0.34,
  "radius_end": 0.82,
  "emission_start": [1.2, 3.0, 12.0],
  "emission_end": [8.0, 1.5, 0.08],
  "extinction": 0.85,
  "density_scale": 1.0,
  "turbulence": 0.85,
  "noise_scale": 3.5,
  "seed": 707
}
```

`position` 是根部圆心；非零 `axis` 会被归一化，`height` 必须为正。两个半径必须非负且不能同时为零。两端 emission 是非负的线性 RGB 相对辐亮度，至少一个通道必须为正；它们沿轴向线性插值，不表示温度或黑体光谱。

`extinction`、`density_scale` 和 `noise_scale` 必须为正，`turbulence` 的范围是 0–1，`seed` 是 uint32。后四项默认分别为 1、0.35、2 和 0。flame 不能绑定 `object`；一个场景最多 8 个 flame。加载器还限制所有 flame 的保守光学厚度之和不超过 64，避免不可控的 null-collision 工作量。

火焰支持位于半径 `max(radius_start,radius_end)`、高度 `height` 的有向圆柱中。三 octave 确定性噪声、径向/轴向平滑包络和中心线扰动共同产生归一化密度。传输只包含吸收与自发光，不包含散射、烟雾、燃烧化学、CFD、动画或 motion blur。运行时使用 Delta Tracking 处理透射和首次真实碰撞，并在普通表面上以体积 NEE 显式采样发光密度；体积不进入 OptiX GAS/IAS/SBT，`max_depth` 仍只计算表面事件。

## 解析波浪水面

```json
{
  "materials": [
    {
      "name": "pool_water",
      "type": "water",
      "ior": 1.333,
      "absorption": [0.42, 0.10, 0.035]
    }
  ],
  "objects": [
    {
      "name": "moon_pool",
      "type": "water_surface",
      "center": [0.0, -0.35, -1.0],
      "size": [6.8, 5.4],
      "material": "pool_water",
      "waves": [
        {"direction": [1.0, 0.25], "amplitude": 0.07,
         "wavelength": 2.6, "phase_radians": 0.35}
      ]
    }
  ]
}
```

`water` 是只供 water_surface 使用的光滑介电材质。`ior` 默认 1.333，范围为 `(1,3]`；RGB `absorption` 默认 `[0.35,0.08,0.025]`，表示场景长度倒数单位下的 Beer 吸收系数，三个分量都必须非负。water 不接受 texture、base_color、emission 或 roughness，其他几何也不能绑定 water 材质。

water_surface 是以 `center` 为中心、在 XZ 平面覆盖正 `size` 的有限解析顶界面，不自带侧壁或池底。场景必须用不透明池壁和池底封住水下区域，并让整个相机光圈从水外开始；开放边界会让介质状态无法定义。多个 water_surface 的 XZ footprint 必须严格分离。含 water_surface 的场景中，普通 `dielectric` 只允许绑定无 alpha 的闭合 sphere，且必须用同一个 dielectric 材质同时绑定球面两侧。这些球面只能严格分离或严格包含，不能相交、相切或与波面的保守高度带相交；相机光圈也必须在所有玻璃球之外。介质栈最多四层，含水场景保守地为水预留一层，因此最多允许三层同时活跃的嵌套玻璃球，包括远离水面的干燥玻璃。water_surface 不接受 transform、alpha、front_material 或 back_material。`waves` 必须包含 1–4 项；非零二维 `direction` 会归一化，`amplitude` 与 `wavelength` 必须为正，有限 `phase_radians` 会规约到 `[0,2π)`。波数、tile 宽度、每条 float32 tile 边界和波面 AABB 的派生值也必须在 float32 中有限、严格递增且非退化。为保持单值高度场与稳定求交，总坡度必须满足

$$
\sum_i \frac{2\pi a_i}{\lambda_i}\le 1.
$$

运行时高度为四项以内的确定性正弦叠加，法线由解析偏导得到。最短波长的一半决定 XZ tile 边长，两个方向 tile 数向上取整且总数不能超过 4096；每个 tile 成为 OptiX 自定义 primitive 的保守 AABB，但所有 tile 共享同一 water_surface 数据和材质。

相机路径在水面使用精确光滑介电 Fresnel 与 Snell 折射，介质栈跟踪当前 IOR/吸收系数，每段水下距离按 `exp(-absorption * distance)` 衰减。跨水面的显式直接光最多处理 8 个边界，保留表面遮挡并应用 Fresnel 透射与 Beer 衰减；为控制成本，这条 shadow 路径保持直线，不执行 Snell 弯折，因此不是焦散求解器。水面是固定单帧，不包含时间、流体动力学、泡沫或 motion blur。

## 统计

渲染统计的 `geometry` 节包含：

- `objects`：JSON 对象数；
- `instances`：IAS 实例数；
- `unique_meshes`：实际引用并构建的唯一网格数；
- `mesh_triangles`：唯一网格三角总数，不乘实例数；
- `gas_count`：primitive GAS 加唯一 mesh GAS，不含 IAS。

含 water_surface 的新渲染还在 `water` 节记录 `water_height_evaluations`、`water_tile_tests`、`water_roots_reported`、`water_shadow_transmissions` 和 `water_medium_segments`。`water_solver_overflows`、`water_medium_errors`、`water_shadow_boundary_overflows` 是安全门；任一非零时渲染器直接报错而不接受输出。无水场景不分配该逐像素计数缓冲，也不改变原随机数序列。

完整示例见 `scenes/`，定向测试场景见 `tests/scenes/`。
