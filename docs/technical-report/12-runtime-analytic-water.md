# 12　运行时解析水面：波面求交、介电传输与 Beer 吸收

Moonlit Stepwell 的水不是平面贴图，也不是预先烘焙的网格。它是 schema v5 在运行时求值的有限解析高度场：OptiX 用保守 tile AABB 找出候选区域，自定义 intersection 程序求射线与波面的根，路径积分器再处理 Fresnel 反射、Snell 折射和水下吸收。

这里的“水体”有严格边界：`water_surface` 只是有限顶界面，不自带侧壁或底部。v0.1 加载器强制相机 aperture 位于水和玻璃外；场景还必须用不透明池壁与池底封住水下区域。它不是流体模拟，也没有时间演化、泡沫、飞溅、专用焦散或 motion blur。

## 1. 四项解析波浪

令水面中心为 $(x_c,y_c,z_c)$。第 $i$ 项波浪有单位水平传播方向
$\mathbf d_i=(d_{ix},d_{iz})$、振幅 $a_i$、波数
$k_i=2\pi/\lambda_i$ 和相位 $\phi_i$。高度为

$$
h(x,z)=y_c+\sum_i a_i\sin\theta_i,
\qquad
\theta_i=k_i[d_{ix}(x-x_c)+d_{iz}(z-z_c)]+\phi_i.
$$

解析偏导为

$$
h_x=\sum_i a_i k_i d_{ix}\cos\theta_i,
\qquad
h_z=\sum_i a_i k_i d_{iz}\cos\theta_i,
$$

所以朝上的几何法线可直接写成

$$
\mathbf n=\frac{(-h_x,1,-h_z)}{\|(-h_x,1,-h_z)\|}.
$$

这避免了有限差分步长和额外高度查询。加载器限制
$\sum_i 2\pi a_i/\lambda_i\le1$，既约束波面坡度，也让求交的数值上界可控；它还用 float32 重新检查派生波数、AABB 和 tile 尺寸均为有限正值，避免有限 JSON 输入在设备表示中溢出。

<!-- source-snippet id="water-analytic-height-gradient" path="src/device_programs.cu" anchor="const float angle =" -->
```cpp
  const float local_x = x - geometry.p0.x;
  const float local_z = z - geometry.p0.z;
  const unsigned int count =
      geometry.water_wave_count < 4u ? geometry.water_wave_count : 4u;
  for (unsigned int i = 0u; i < count; ++i) {
    const spectraldock::DeviceWaterWave& wave = geometry.water_waves[i];
    const float angle = wave.wave_number *
                            (wave.direction.x * local_x +
                             wave.direction.y * local_z) +
                        wave.phase;
    height += wave.amplitude * sinf(angle);
    const float slope = wave.amplitude * wave.wave_number * cosf(angle);
    dx += slope * wave.direction.x;
    dz += slope * wave.direction.y;
  }
  if (derivative_x != nullptr) *derivative_x = dx;
  if (derivative_z != nullptr) *derivative_z = dz;
  return height;
```

## 2. Tile AABB 与解析曲面求交

完整水面仍进入 OptiX GAS，但不是三角网格。最短波长的一半决定 tile 尺寸；每个 tile 只提供覆盖局部最大振幅的保守 AABB，全部 tile 共享同一组波浪参数和 SBT 数据。BVH 因而负责快速剔除，真正曲面仍由同一个解析函数定义。

沿射线 $\mathbf r(t)=\mathbf o+t\mathbf d$，交点满足

$$
f(t)=r_y(t)-h(r_x(t),r_z(t))=0.
$$

intersection 程序在射线进入 tile 的区间内隔离候选根，再以受区间保护的 Newton/bisection 收敛，并检查残差。相邻 tile 从同一个 `surface_min + width * integer` 计算边界，加载器会用同样的 float32 运算逐条确认边界严格递增，避免大坐标下小 tile 因 ULP 量化塌缩。最终用半开 XZ 区间决定唯一所有权；AABB 可以保守重叠，但同一根只由一个 tile 报告。这是 tile seam 不应出现在解析波面的原因。

具体实现先用正弦与余弦的区间包络估计 $f$ 和 $f'$：若 $f$ 的区间不含零就排除该段；若 $f'$ 不含零就得到单调段，再用二分和受 bracket 保护的 Newton 步求根。近切线处的单精度符号最容易产生一簇伪根，因此当根处 $|f'|<0.02$ 时才进入选择性的双精度复核：用 double 重新计算 bracket 两端，确认真实异号后再做 40 次二分。恰好落在分段端点的 float 零值也会在根两侧做 double 异号复核，切触零或舍入伪零不作为介质穿越报告。这样把昂贵的 double 三角函数限制在可疑区间，而普通根仍走 float 快路径。

<!-- source-snippet id="water-double-root-refinement" path="src/device_programs.cu" anchor="refine_suspicious_water_bracket" -->
```cpp
static __forceinline__ __device__ bool refine_suspicious_water_bracket(
    const GeometryData& geometry, float3 origin, float3 direction,
    float lower, float upper, float& root, float& residual,
    int& orientation) {
  double precise_lower = static_cast<double>(lower);
  double precise_upper = static_cast<double>(upper);
  double lower_value = water_function_value_precise(
      geometry, origin, direction, precise_lower);
  const double upper_value = water_function_value_precise(
      geometry, origin, direction, precise_upper);
  if ((lower_value < 0.0) == (upper_value < 0.0)) return false;
  orientation = lower_value < 0.0 ? 1 : -1;
  for (int iteration = 0; iteration < 40; ++iteration) {
    const double middle = 0.5 * (precise_lower + precise_upper);
    const double middle_value = water_function_value_precise(
        geometry, origin, direction, middle);
    if ((middle_value < 0.0) == (lower_value < 0.0)) {
      precise_lower = middle;
      lower_value = middle_value;
    } else {
      precise_upper = middle;
    }
  }
  root = static_cast<float>(0.5 * (precise_lower + precise_upper));
```

求根容量或残差检查失败不会被当成“没有交点”：设备增加 solver overflow，主机拒绝保存图片。预览还必须人工检查水面没有 tile seam、针孔或介质泄漏。

## 3. 精确光滑介电 Fresnel 与 Snell

设入射、透射折射率为 $\eta_i,\eta_t$，入射角余弦为 $c_i$。Snell 定律给出

$$
\sin^2\theta_t=\left(\frac{\eta_i}{\eta_t}\right)^2(1-c_i^2).
$$

右侧不小于 1 时发生全反射。否则 $c_t=\sqrt{1-\sin^2\theta_t}$，非偏振 Fresnel 反射率为

$$
F=\frac12\left[
\left(\frac{\eta_i c_i-\eta_t c_t}{\eta_i c_i+\eta_t c_t}\right)^2+
\left(\frac{\eta_t c_i-\eta_i c_t}{\eta_t c_i+\eta_i c_t}\right)^2
\right].
$$

<!-- source-snippet id="water-exact-fresnel" path="src/device_programs.cu" anchor="const float sin2_t =" -->
```cpp
static __forceinline__ __device__ float dielectric_fresnel(
    float cos_i, float eta_i, float eta_t, float* cos_t_out = nullptr) {
  cos_i = fminf(fmaxf(cos_i, 0.0f), 1.0f);
  const float eta = eta_i / eta_t;
  const float sin2_t = eta * eta * fmaxf(0.0f, 1.0f - cos_i * cos_i);
  if (sin2_t >= 1.0f) {
    if (cos_t_out != nullptr) *cos_t_out = 0.0f;
    return 1.0f;
  }
  const float cos_t = sqrtf(fmaxf(0.0f, 1.0f - sin2_t));
  if (cos_t_out != nullptr) *cos_t_out = cos_t;
  const float rs_denominator = eta_i * cos_i + eta_t * cos_t;
  const float rp_denominator = eta_t * cos_i + eta_i * cos_t;
  const float rs = (eta_i * cos_i - eta_t * cos_t) /
                   fmaxf(rs_denominator, 1.0e-20f);
  const float rp = (eta_t * cos_i - eta_i * cos_t) /
                   fmaxf(rp_denominator, 1.0e-20f);
  return 0.5f * (rs * rs + rp * rp);
}
```

路径按概率 $F$ 反射，否则按 Snell 向量式折射。折射分支的吞吐量乘
$(\eta_i/\eta_t)^2$；这是从相机反向追踪辐亮度时的测度换元，不是额外吸收。水面和普通光滑 dielectric 共用这一精确分支；未使用 `water_surface` 的旧场景仍走原分支，保持原 RNG 序列。

## 4. 介质栈与严格嵌套

仅知道当前交点“正面还是背面”不足以处理水中的玻璃球：从水进入玻璃时，入射 IOR 是水而不是空气；离开玻璃后又必须恢复水。因此每条路径维护最多四层 LIFO 介质栈，层中记录材质 ID、IOR 和 RGB 吸收系数。

<!-- source-snippet id="water-medium-stack-update" path="src/device_programs.cu" anchor="update_medium_after_transmission" -->
```cpp
static __forceinline__ __device__ bool update_medium_after_transmission(
    MediumState& state, int material_index, const MaterialData& material,
    int front_face, WaterCounters& counters) {
  if (front_face != 0) {
    if (state.depth >= 4) {
      ++counters.medium_errors;
      return false;
    }
    state.layers[state.depth++] =
        {material_index, fmaxf(material.ior, 1.0e-3f), material.absorption};
    return true;
  }
  if (state.depth <= 0 ||
      state.layers[state.depth - 1].material_index != material_index) {
    ++counters.medium_errors;
    return false;
  }
  --state.depth;
  return true;
}
```

正面透射压栈，背面透射必须弹出同一材质；次序不符就是相交、开放或错误嵌套。加载器因此把含水场景的拓扑约束变成硬错误：dielectric sphere 必须在正反面绑定同一个非空 dielectric 且不能使用 alpha；任意两球只能严格分离或严格包含，拒绝相交与内外相切；四层总栈深包含水层，所以最多允许三层同时活跃的嵌套玻璃。sphere 不能与水面的保守高度带相交，多个水面 footprint 必须严格分离，相机的有限 aperture 也必须位于水和所有玻璃之外。Moonlit Stepwell 的不透明池壁和池底进一步保证路径不会从没有边界的侧面“漏出水体”。

有限顶界面本身没有水体侧面。一条已经在水下的路径若从 footprint 边缘绕入，可能在介质栈为空时首先碰到水面的背面；直接按严格弹栈会把这个几何缺口误报成介质错误。实现只对“空栈 + 水材质背面”这一无歧义情形推断基底水层，并在计算该段 Beer 衰减前压入水；只要栈非空，尤其存在嵌套玻璃时，绝不搜索或修补层次，仍按严格 LIFO 报错。这个补偿不是通用 point-in-volume 判定，也是 v0.1 必须使用不透明池壁、从水外启动相机的原因之一。

### 水中 dielectric sphere 为什么使用自定义实心边界

OptiX Programming Guide 9.1 的 back-face culling 规则把内建 sphere primitive 视为中空单面表面并执行背面剔除；射线若从球内开始，不会得到这个 sphere 的退出命中。这对普通不透明或 alpha 表面很方便，却与介质栈冲突：路径折射进水下玻璃球后，必须命中背面并弹出玻璃层，才能恢复水的 IOR 与吸收系数。

令 sphere 中心为 $\mathbf c$、半径为 $R$，射线为 $\mathbf o+t\mathbf d$，并记 $\mathbf q=\mathbf o-\mathbf c$。代入球方程得到

$$
a=\mathbf d\cdot\mathbf d,\qquad
b=2\mathbf q\cdot\mathbf d,\qquad
\gamma=\mathbf q\cdot\mathbf q-R^2,
$$

$$
\Delta=b^2-4a\gamma,\qquad
t_{\pm}=\frac{-b\pm\sqrt{\Delta}}{2a}.
$$

射线在球内时有 $\gamma<0$ 且 $a>0$，因此 $t_-t_+=\gamma/a<0$：两个根一负一正，正退出根必须保留。项目的共享二次求根器按距离排序；近根不在当前 ray 范围时会继续报告远根，所以球内射线能得到正退出根。交点的外法线仍是 $(\mathbf p-\mathbf c)/R$；此时 $\mathbf d\cdot\mathbf n>0$，closest-hit 将它识别为背面，介质栈才会正确弹出。

<!-- source-snippet id="water-solid-sphere-intersection" path="src/device_programs.cu" anchor="__intersection__solid_sphere" -->
```cpp
extern "C" __global__ void __intersection__solid_sphere() {
  const HitgroupData* record =
      reinterpret_cast<const HitgroupData*>(optixGetSbtDataPointer());
  const GeometryData& geometry = record->geometry;
  const float3 offset = sub(optixGetObjectRayOrigin(), geometry.p0);
  const float3 direction = optixGetObjectRayDirection();
  report_quadratic(dot3(direction, direction),
                   2.0f * dot3(offset, direction),
                   dot3(offset, offset) - geometry.radius * geometry.radius,
                   geometry);
}
```

主机只在场景含 `water_surface` 且 sphere 绑定 dielectric 时，把它改为带保守 AABB 的 `kPrimitiveSolidSphere` 自定义 primitive；普通 sphere 和全部无水场景仍使用 OptiX 内建 sphere。这既满足水中闭合边界语义，也避免机械改动既有场景的求交路径与 golden 输出。

## 5. Beer 吸收

在均匀介质中走过距离 $d$ 后，RGB 透射率为

$$
\mathbf T(d)=\exp(-\boldsymbol\sigma_a d),
$$

指数按通道计算。Moonlit Stepwell 让红通道吸收大于蓝通道，因此深水路径呈蓝绿色；这只是线性 RGB 近似，不是光谱水体模型。

<!-- source-snippet id="water-beer-segment" path="src/device_programs.cu" anchor="medium_segment_transmittance" -->
```cpp
static __forceinline__ __device__ float3 medium_segment_transmittance(
    const MediumState& state, float distance, WaterCounters& counters) {
  if (state.depth <= 0 || !(distance > 0.0f)) {
    return f3(1.0f, 1.0f, 1.0f);
  }
  ++counters.medium_segments;
  return exp_attenuation(medium_absorption(state), distance);
}
```

相机路径在每个表面段、体积碰撞段或背景段之前把该透射率乘进 throughput。介质栈顶决定当前吸收系数，所以进入无吸收玻璃球时暂时停止水吸收，离开后再恢复。

## 6. 跨水面直接光的工程近似

若完全按 Snell 弯折 shadow ray，从着色点到面积灯不再是一条已知直线，而会变成两点边值和焦散连接问题。v0.1 采用受控近似：连接仍是直线，最多穿过 8 个透明边界；每段乘 Beer 衰减，每个边界乘 $1-F$，普通不透明交点仍阻断光。

<!-- source-snippet id="water-straight-shadow-boundaries" path="src/device_programs.cu" anchor="++counters.shadow_transmissions" -->
```cpp
    const float eta_i = medium_ior(media);
    const float eta_t = hit.front_face != 0
        ? fmaxf(material.ior, 1.0e-3f)
        : exit_ior(media, hit.material_index, counters);
    const float cos_i =
        fminf(fmaxf(dot3(neg(direction), hit.normal), 0.0f), 1.0f);
    const float fresnel = dielectric_fresnel(cos_i, eta_i, eta_t);
    if (!(fresnel < 1.0f)) return f3(0.0f, 0.0f, 0.0f);
    transmittance = mul(transmittance, 1.0f - fresnel);
    if (!update_medium_after_transmission(
            media, hit.material_index, material, hit.front_face, counters)) {
      return f3(0.0f, 0.0f, 0.0f);
    }
    ++counters.shadow_transmissions;
    const float advance = hit.distance + params.scene_epsilon * 2.0f;
    origin = add(origin, mul(direction, advance));
    remaining -= advance;
```

这能让水上月光照亮池底，并保留遮挡和选择性吸收，但不会产生正确的折射焦散。报告和 gallery 都不能把它描述成完整水面双向连接算法。

## 7. 安全统计、验证与限制

stats 分开记录 height evaluations、tile tests、roots reported、shadow transmissions 和 medium segments。solver overflows、medium errors 或 shadow-boundary overflows 任一非零都会让主机拒绝输出。

<!-- source-snippet id="water-host-safety-gate" path="src/optix_renderer.cpp" anchor="water transport safety check failed" -->
```cpp
  if (water_totals.solver_overflows != 0ull ||
      water_totals.medium_errors != 0ull ||
      water_totals.shadow_boundary_overflows != 0ull) {
    throw std::runtime_error(
        "water transport safety check failed: solver overflows=" +
        std::to_string(water_totals.solver_overflows) +
        ", medium errors=" + std::to_string(water_totals.medium_errors) +
        ", shadow boundary overflows=" +
        std::to_string(water_totals.shadow_boundary_overflows));
  }
```

定向 GPU fixture 检查固定 seed、镜面反射、折射位移、深浅路径和 RGB Beer 色移、水上灯照亮水下漫反射面、不透明遮挡、浸没玻璃 sphere 的严格介质栈，以及全部安全计数。Moonlit Stepwell 正式配置使用 2048 spp、depth 16 并关闭 Denoiser，使 tile seam、漏交、异常介质边界和高亮噪点不会被降噪掩盖。

当前模型仍有以下边界：

- 波浪是确定性静态正弦叠加，不是 CFD、浅水方程或海洋频谱动画；
- `water_surface` 只是有限顶界面，依赖场景的不透明池壁/底部封闭；
- 加载器强制相机 aperture 从水与玻璃外开始；普通 dielectric 只支持同材质双面、无 alpha 的闭合 sphere，水层加嵌套玻璃合计最多四层；
- 路径折射精确，但直接光 shadow 不按 Snell 弯折，因此没有物理正确焦散；
- RGB Beer 吸收不是波长采样，也没有体散射、悬浮物或泡沫。

输入字段和约束见[场景格式](../SCENE_FORMAT.md)，展示构图见 [Moonlit Stepwell](../EXAMPLES.md#moonlit-stepwell)。

[上一章：程序化体积火焰](11-procedural-volumetric-flame.md) · [返回目录](README.md) · [下一章：HDR 环境与重要性采样](13-hdr-environment-and-importance-sampling.md)
