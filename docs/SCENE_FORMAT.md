# 场景格式

场景为 JSON。schema v1 保持兼容；schema v2 新增顶层 `meshes` 与 `type: "mesh"` 对象。未知引用、缺失资源、非有限数、退化几何和非法材质会在 CUDA/OptiX 初始化前报错。

## 顶层字段

- `camera`：`look_from`、`look_at`、`up`、`vfov`/`vertical_fov_degrees`、`aperture`、`focus_distance`。
- `background`：`constant`，或带渐变和太阳瓣的 `sky`；`exposure` 以 EV 表示。
- `render`：`width`、`height`、`spp`、`max_depth`、`seed`、`denoise`。
- `textures`：`constant` 或 PNG `image`，色彩空间为 `srgb`/`linear`。
- `materials`：`lambertian`、`metal`、`dielectric`、`emitter`。
- `meshes`（v2）：命名 OBJ 资源。
- `objects`：sphere、rectangle、sketch、disk、cylinder、parabola、mesh。
- `lights`：显式采样的 rectangle、disk、sphere 面积光。

`max_depth` 的范围仍为 1–64，语义是最多处理的表面事件数；最后一个事件完整估计显式直接光，但不再生成下一事件的 BSDF 射线。

## OBJ 网格与实例

```json
{
  "schema_version": 2,
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

## 统计

渲染统计的 `geometry` 节包含：

- `objects`：JSON 对象数；
- `instances`：IAS 实例数；
- `unique_meshes`：实际引用并构建的唯一网格数；
- `mesh_triangles`：唯一网格三角总数，不乘实例数；
- `gas_count`：primitive GAS 加唯一 mesh GAS，不含 IAS。

完整示例见 `scenes/`，v1 测试场景见 `tests/scenes/`。
