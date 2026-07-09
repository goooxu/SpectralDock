# 06　几何、可见性与 BVH

路径积分器反复提出两个几何问题：

1. 从 $\mathbf o$ 沿 $\mathbf d$ 前进，最先遇到哪个表面？
2. 从当前点到灯面点之间，是否有任何遮挡？

两者都从射线方程 $\mathbf r(t)=\mathbf o+t\mathbf d$ 出发；差别只是前者需要最近交点的完整信息，后者遇到第一个遮挡即可停止。

## 1. 解析几何求交

### 1.1 球

中心为 $\mathbf c$、半径为 $R$ 的球满足

$$
\|\mathbf p-\mathbf c\|^2=R^2.
$$

代入 $\mathbf p=\mathbf o+t\mathbf d$ 得到关于 $t$ 的二次方程：

$$
(\mathbf d\cdot\mathbf d)t^2
+2\mathbf d\cdot(\mathbf o-\mathbf c)t
+\|\mathbf o-\mathbf c\|^2-R^2=0.
$$

判别式小于零表示错过球；等于零表示相切；大于零有两个交点。选择有效范围内最小的正根。SpectralDock 使用 OptiX 内建 sphere primitive 完成遍历和求交。

球面外法线为

$$
\mathbf n_g=\frac{\mathbf p-\mathbf c}{R}.
$$

### 1.2 平面、圆盘与矩形

经过 $\mathbf p_0$、法线为 $\mathbf n$ 的平面满足

$$
\mathbf n\cdot(\mathbf p-\mathbf p_0)=0.
$$

射线交点参数为

$$
t=\frac{\mathbf n\cdot(\mathbf p_0-\mathbf o)}
{\mathbf n\cdot\mathbf d}.
$$

分母接近零时射线与平面平行。圆盘还要求 $\|\mathbf r(t)-\mathbf p_0\|\le R$。rectangle 和 sketch 则在主机端拆成两个三角形交给 OptiX 内建三角形求交。JSON 中的 rectangle 实际允许任意非退化平行四边形，并不额外校验四个角为直角；rectangle light 也只要求两条边不共线。

### 1.3 圆柱

设圆柱轴单位向量为 $\mathbf a$，底部参考点为 $\mathbf p_0$。对任意向量 $\mathbf q$，去掉沿轴分量：

$$
\mathbf q_\perp=\mathbf q-(\mathbf q\cdot\mathbf a)\mathbf a.
$$

圆柱侧面满足

$$
\|\mathbf q_\perp\|^2=R^2.
$$

把射线代入后仍是二次方程。有限高度圆柱再检查

$$
0\le(\mathbf r(t)-\mathbf p_0)\cdot\mathbf a\le H.
$$

当前 cylinder **只有侧壁，没有上下端盖**。若需要封闭物体，场景必须另外添加圆盘。

### 1.4 抛物柱面

场景中的 `parabola` 不是旋转抛物面，而是沿一根轴延伸的**抛物柱面**。在局部截面坐标 $(x,y)$ 中，它满足

$$
x^2=4fy,
$$

其中 $f$ 是顶点到焦点的距离。射线的局部 $x(t),y(t)$ 都是 $t$ 的一次式，代入后得到二次方程。最终交点还必须位于用户给定的 AABB 内，因此实际几何是被包围盒裁剪的一段抛物柱面。

圆盘、圆柱和抛物柱面的自定义求交分别位于 [`__intersection__disk`、`__intersection__cylinder`、`__intersection__parabola`](../../src/device_programs.cu)。

## 2. 三角形、重心坐标与 OBJ

三角形顶点为 $\mathbf a,\mathbf b,\mathbf c$。内部任一点可写成

$$
\mathbf p=\lambda_a\mathbf a+
\lambda_b\mathbf b+
\lambda_c\mathbf c,
$$

$$
\lambda_a+\lambda_b+\lambda_c=1,
\qquad
\lambda_a,\lambda_b,\lambda_c\ge0.
$$

这三个 $\lambda$ 是重心坐标。除判断交点外，它还能插值顶点属性：

$$
\mathbf n_s=\mathrm{normalize}
(\lambda_a\mathbf n_a+\lambda_b\mathbf n_b+\lambda_c\mathbf n_c),
$$

$$
\mathbf{uv}=\lambda_a\mathbf{uv}_a+\lambda_b\mathbf{uv}_b+\lambda_c\mathbf{uv}_c.
$$

OBJ 导入器会三角化多边形、合并 group，并处理 OBJ 独立的 position/normal/UV 索引。它忽略 `mtllib` 与 `usemtl`；最终材质、纹理和正反面都由场景 JSON 决定。若法线不完整，导入器按 smoothing group 生成法线；纹理所需的 UV 必须完整。

## 3. 几何法线、着色法线和正反面

**几何法线**由真实表面形状决定，用来判断射线命中正面还是背面。**着色法线**可由网格顶点法线插值得到，让低多边形表面看起来平滑。

SpectralDock 先确保着色法线与几何外法线位于同一半球，再根据当前射线来自正面还是背面，把最终 `hit.normal` 朝向射线一侧。这样 `wo = -ray_direction` 与法线满足正点积，同时仍用真实几何法线选择 `front_material` 或 `back_material`。

着色法线只改变光照方向，不改变真实轮廓和求交位置；极端插值法线仍可能不完全满足严格的能量守恒校正。

## 4. UV、纹理与 alpha cutoff

UV 把三维表面点映射到二维纹理。球、圆盘、圆柱和抛物柱面有解析映射；三角网格用重心插值。设备采样图像时执行一次纵向坐标转换，以适配 PNG 顶部原点。

`alpha_cutoff` 是确定性二值测试：

$$
\alpha<\text{cutoff}
\quad\Longrightarrow\quad
\text{忽略本次交点}.
$$

它适合叶片、纸片镂空等效果，但不是半透明混合。通过测试的纹素完全存在，未通过的完全不存在；相机射线和阴影射线使用同样的裁剪逻辑。

## 5. 为什么需要 BVH

若场景有 $M$ 个三角形、总共追踪 $R$ 条射线，逐射线测试所有三角形需要约 $R\times M$ 次求交。BVH（Bounding Volume Hierarchy）用便宜的轴对齐包围盒测试排除大片几何：

1. 根节点包住整个场景；
2. 子节点包住更小的几何集合；
3. 射线错过一个盒子，就跳过其全部后代；
4. 只有命中叶节点盒子时，才测试实际 primitive。

![射线遍历包围盒以及 GAS/IAS 两级结构](figures/ray-bvh.svg)

*图 5：左侧展示 BVH 如何跳过未命中的整组几何；右侧展示 SpectralDock 的两级 OptiX 加速结构。*

BVH 不改变求交答案，只改变寻找答案的工作量。最坏情况仍可能很差，但典型场景会比线性遍历少测试大量 primitive。

## 6. SpectralDock 的 GAS 与 IAS

OptiX 把底层几何加速结构称为 GAS，把实例层称为 IAS：

- 每个被引用的 mesh 资源上传并构建一份 GAS；若紧凑尺寸确实更小则压缩，多个对象实例共享最终结构；
- 每个非 mesh primitive 对象各构建一份 GAS；
- IAS 为 JSON 中每个对象保存一个实例，并指向相应 GAS；
- 只有 mesh 对象支持 `T * Rz * Ry * Rx * S` 实例变换；缩放三分量必须严格大于零，不能用负缩放做镜像；其他 primitive 已在世界坐标中定义。

构建标志使用 `ALLOW_COMPACTION | PREFER_FAST_TRACE`。前者允许在紧凑尺寸确实更小时减少最终 GAS 占用；快速追踪偏好适合“一次构建后发射大量射线”的离线渲染。

## 7. 两类射线的不同答案

| 射线类型 | 需要的结果 | OptiX 行为 |
|---|---|---|
| radiance | 最近交点的位置、法线、UV、材质和灯索引 | 执行 closest-hit，未命中执行 radiance miss |
| shadow | 到指定距离是否无阻挡 | 首个有效遮挡即终止，不执行 closest-hit |

自交偏移和有限的阴影 `tmax` 都是必要的数值边界。但固定世界尺度的 `scene_epsilon = 1e-4` 不是尺度自适应方案：场景极大或极小时，可能需要更精细的误差处理。

下一章将把路径状态、BVH 和材质程序接到 OptiX 的 GPU 执行模型中。

[上一章：直接光照、NEE 与 MIS](05-direct-lighting-and-mis.md) · [返回目录](README.md) · [下一章：OptiX/GPU 实现](07-optix-gpu-implementation.md)
