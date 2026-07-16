# 12　运行时解析水面：波面求交、介电传输与 Beer 吸收

Moonlit Stepwell 的水不是平面贴图，也不是预先烘焙的网格。Python 程序通过 `Renderer.object(type="water_surface", ...)` 构造一个在运行时求值的有限解析高度场：OptiX 用保守 tile AABB 找出候选区域，自定义 intersection 程序求射线与波面的根，路径积分器再处理粗糙 GGX 介电反射/透射、NEE/MIS、Fresnel/Snell、介质栈和水下吸收。

“熔岩圣殿的机械先知”在右侧下陷池体中使用同一个解析模型：带苔石砖与
不透明池壁/池底封闭水下区域，RGB Beer 吸收让池边保持可见而深处迅速转为
幽蓝。PhysX 只计算空中预碎裂刚体；水面没有粒子、SPH/FLIP、刚体耦合或
时间演化，仍由 OptiX 自定义求交与 CUDA 介质传输在渲染时求值。

封面穹顶的“冰晶”不进入本章的介质栈。早期 dielectric sphere 在解析水面
存在时，高样本诊断发现了稀有近切线路径的介质栈安全错误；在不修改渲染器
且坚持正式输出 `medium_errors == 0` 的前提下，最终场景改用非透明冷色粗糙
metal sphere 作为冰晶外观代理，并以 `opaque_frost_visual_proxy: true`
显式记录。这保留了轮廓和冷色反光，但不宣称模拟冰的透射光学。

这里的“水体”有严格边界：`water_surface` 只是有限顶界面，不自带侧壁或底部。原生 SceneBuilder 强制相机 aperture 位于水和玻璃外；Python 程序还必须用不透明池壁与池底封住水下区域。它不是流体模拟，也没有时间演化、泡沫、飞溅、专用焦散或 motion blur。

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
\mathbf n_g=\frac{(-h_x,1,-h_z)}{\|(-h_x,1,-h_z)\|}.
$$

这避免了有限差分步长和额外高度查询。SceneBuilder 限制
$\sum_i 2\pi a_i/\lambda_i\le1$，既约束波面坡度，也让求交的数值上界可控；它还用 float32 重新检查派生波数、AABB 和 tile 尺寸均为有限正值，避免有限 Python 数值在设备表示中溢出。

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

intersection 程序在射线进入 tile 的区间内隔离候选根，再以受区间保护的 Newton/bisection 收敛，并检查残差。相邻 tile 从同一个 `surface_min + width * integer` 计算边界，SceneBuilder 会用同样的 float32 运算逐条确认边界严格递增，避免大坐标下小 tile 因 ULP 量化塌缩。最终用半开 XZ 区间决定唯一所有权；AABB 可以保守重叠，但同一根只由一个 tile 报告。这是 tile seam 不应出现在解析波面的原因。

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

## 3. 精确介电 Fresnel 与 Snell

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

光滑含水路径按概率 $F$ 反射，否则按 Snell 向量式折射；首个光滑水面命中则按第 7 节同时构造两个加权分支。这些 delta 事件的入射角、反射与 Snell 折射方向全部使用 $\mathbf n_g$，不读取顶点着色法线。折射吞吐量包含 $(\eta_i/\eta_t)^2$，这是从相机反向追踪辐亮度时的测度换元，不是额外吸收。粗糙介电路径则把同一个精确 $F$ 用于绕 $\mathbf n_s^{\mathrm{eff}}$ 建立的 GGX 反射/透射值与混合 PDF，$\mathbf n_g$ 仍检查最终介质侧；完整 BTDF、Jacobian 和 VNDF 推导见[第 3 章第 4 节](03-materials-and-bsdf.md#4-介电质从-delta-界面到粗糙微表面)。未使用 `water_surface` 的光滑旧场景仍走兼容分支，保持原 RNG 序列。

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

正面透射压栈，背面透射必须弹出同一材质；次序不符就是相交、开放或错误嵌套。SceneBuilder 因此把含水场景的拓扑约束变成硬错误：dielectric sphere 必须在正反面绑定同一个非空 dielectric 且不能使用 alpha；任意两球只能严格分离或严格包含，拒绝相交与内外相切；四层总栈深包含水层，所以最多允许三层同时活跃的嵌套玻璃。sphere 不能与水面的保守高度带相交，多个水面 footprint 必须严格分离，相机的有限 aperture 也必须位于水和所有玻璃之外。Moonlit Stepwell 的不透明池壁和池底进一步保证路径不会从没有边界的侧面“漏出水体”。

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

主机只在场景含 `water_surface` 且 sphere 绑定 dielectric 时，把它改为带保守 AABB 的 `kPrimitiveSolidSphere` 自定义 primitive；普通 sphere 和全部无水场景仍使用 OptiX 内建 sphere。这既满足水中闭合边界语义，也避免机械改动既有场景的求交路径与确定性输出序列。

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

## 6. 粗糙水面的 NEE：只连接当前散射事件

Moonlit Stepwell 将水材质设为 `roughness: 0.12`。宏观波面仍决定交点和 $\mathbf n_g$；这个解析 primitive 没有额外顶点法线，所以 $\mathbf n_s^{\mathrm{eff}}=\mathbf n_g$，GGX 微表面只决定该点的反射/透射方向分布。因为这个 BSDF 是连续分布，有限灯、程序化 flame、HDR 环境和 point/directional delta 灯都能在当前水面顶点执行 NEE。其中有限表面灯使用两份灯样本与一份 BSDF 样本组成三技术 balance，环境 NEE 仍与后来的 BSDF miss 用 power MIS 配对，delta 灯则逐盏连接且权重为 1。

两个水面专用的采样优化直接针对“水面是主角，却最慢收敛”的问题：

- GGX 微表面的物理反射率仍是精确 Fresnel $F$，但当 $F<1$ 时以 $s_R=\max(F,0.5)$ 选反射分支，用 $F/s_R$ 的路径权重回补；透射分支同理用 $(1-F)/(1-s_R)$ 回补。这使低 Fresnel 概率下的月盘反射也至少获得一半 BSDF 样本，但不改变期望值。
- 有限灯的全局功率分布记为 $q_G(i)$，均匀索引分布为 $q_U(i)=1/N$。每个粗糙水面顶点**确定性地各取一份** $q_G$ 样本和 $q_U$ 样本；两份使用联合灯索引密度 $q_G(i)+q_U(i)$，不乘 0.5。这同时给强月光与弱水下灯独立的采样机会；介质内的其他顶点仍只用 $q_U$ 取一份样本。
- 两份水面有限灯样本若各自选中 sphere，球外顶点都在其可见立体角内均匀采方向；球内或近球顶点回退到面积采样。该规则现已推广到所有连续 BSDF 顶点；Moonlit 的月灯是 disk，仍按面积采样，水下 sphere 灯直接受益。

第一项的 BSDF/PDF 推导见[第 3 章第 4.1 节](03-materials-and-bsdf.md#41-粗糙介电反射与透射)，第二项的顶点选灯模式和源码见[第 13 章第 5 节](13-hdr-environment-and-importance-sampling.md#5-有限灯也要选择分布)，第三项的圆锥立体角与 PDF 推导见[第 5 章第 1 节](05-direct-lighting-and-mis.md#1-在灯面上取一个随机点)。

对灯方向 $\boldsymbol\omega_i$，反射与透射的物理侧由 $\mathbf n_g$ 判定。直接光估计统一写成

$$
\widehat L_d=
\frac{f_s(\boldsymbol\omega_i,\boldsymbol\omega_o)
|\mathbf n_s^{\mathrm{eff}}\cdot\boldsymbol\omega_i|\,
L_e\,\mathbf T\,V}{p_L(\boldsymbol\omega_i)}w_L.
$$

这里的 $f_s|\mathbf n_s^{\mathrm{eff}}\!\cdot\boldsymbol\omega_i|$ 在代码中融合为 `f_cos`；$p_B$ 是第 3 章推导的 GGX 介电反射或透射 PDF。透射 PDF 已含实际分支采样概率 $1-s_R$ 和半程向量 Jacobian，而物理 BTDF 仍含 $1-F$。令条件方向密度为 $c_i$，则 $p_G=q_G(i)c_i$、$p_U=q_U(i)c_i$、$p_L=p_G+p_U$。对于有下一条 BSDF 射线可竞争的绑定表面灯，两份 direct 样本各自使用 $w_L=p_L/(p_L+p_B)$，BSDF emitter-hit 使用 $w_B=p_B/(p_L+p_B)$，所以三项期望系数满足

$$
\frac{p_G}{p_G+p_U+p_B}+
\frac{p_U}{p_G+p_U+p_B}+
\frac{p_B}{p_G+p_U+p_B}=1.
$$

没有 BSDF 端点竞争者时令 $p_B=0$，两份灯样本仍以 $(q_G+q_U)/(q_G+q_U)=1$ 覆盖有限灯积分，因而始终不需要 0.5 补偿。$\mathbf T$ 只表示当前顶点之后、同一介质连接段上的 Beer 衰减。若灯位于透射侧，代码先在介质栈**副本**中执行本次边界切换，再用副本计算该段衰减；相机路径自己的栈不会被一次 NEE 试探修改。

这种三技术构造使用 balance heuristic，而不是把联合灯密度再套入普通双策略 power heuristic。只有绑定表面灯、存在下一条 BSDF 射线且该方向有灯采样支持时才启用；最后深度、未绑定 emitter、单面灯背面、球内无支持命中、flame、delta 前驱与相机直见都删除不存在的竞争密度。HDR 环境继续使用独立的 NEE/BSDF-miss power MIS。

point/directional 不进入上述 $q_G/q_U$ 分布。每盏灯在当前粗糙水面分别评估反射侧或透射侧 GGX BSDF；透射连接同样先在介质栈副本中跨过当前水界面，再对 point 的有限段或 directional 的无限段应用 Beer 与遮挡。连续 BSDF 没有命中理想 delta 灯的竞争路径，所以无需额外 emitter-hit MIS。

<!-- source-snippet id="water-finite-emitter-balance-path" path="src/device_programs.cu" anchor="use_water_finite_balance" -->
```cpp
        const bool use_water_finite_balance =
            emitter_is_bound_to_light &&
            previous_light_mode == kFiniteLightWaterPowerSample &&
            previous_delta == 0 &&
            light_pdf > 0.0f;
        const float weight = use_water_finite_balance
            ? balance_heuristic(previous_pdf, light_pdf)
            : emitter_hit_mis_weight(
                  previous_pdf, light_pdf, previous_delta != 0,
                  emitter_is_bound_to_light);
        accumulate_path_contribution(
            radiance, mul(mul(throughput, emitted), weight),
            clamp_threshold, clamped_counter);
```

<!-- source-snippet id="water-direct-single-event" path="src/device_programs.cu" anchor="direct_segment_transmittance" -->
```cpp
static __forceinline__ __device__ float3 direct_segment_transmittance(
    const SurfaceHit& hit, const MaterialData& material,
    float3 shadow_origin, float3 shadow_direction, float shadow_distance,
    int target_light, bool transmitted_connection, const MediumState& media,
    unsigned long long& traced_rays, WaterCounters& counters) {
  MediumState shadow_media = media;
  if (params.water_surface_count != 0u &&
      is_rough_dielectric(material) && transmitted_connection) {
    if (!update_medium_after_transmission(
            shadow_media, hit.material_index, material, hit.front_face,
            counters)) {
      return f3(0.0f, 0.0f, 0.0f);
    }
  }
  if (!trace_visible(shadow_origin, shadow_direction, shadow_distance,
                     target_light, traced_rays)) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  return params.water_surface_count != 0u
      ? medium_segment_transmittance(
            shadow_media, shadow_distance, counters)
      : f3(1.0f, 1.0f, 1.0f);
}
```

`transmitted_connection` 最终由定向 $\mathbf n_g$ 对 $\boldsymbol\omega_o$ 和 $\boldsymbol\omega_i$ 的符号关系判定。$\mathbf n_s^{\mathrm{eff}}$ 可以扰动 GGX 波瓣，但不能把一个物理上的反射方向误当作透射，也不能反向修改介质栈。因此通用分类先只读 $\mathbf n_g$，粗糙介电再额外要求着色与几何框架的反射/透射分类一致：

<!-- source-snippet id="water-geometric-side-consistency" path="src/device_programs.cu" anchor="classify_geometric_event" -->
```cpp
// Shading normals shape a rough dielectric lobe, but cannot change which
// medium a direction occupies. Reject events for which the shading and
// geometric frames disagree instead of silently mutating the medium stack.
static __forceinline__ __device__ bool rough_macro_sides_agree(
    float3 shading_normal, float3 geometric_normal, float3 wo, float3 wi,
    bool& transmitted) {
  if (!classify_geometric_event(
          geometric_normal, wo, wi, transmitted)) {
    return false;
  }
  const float shading_outgoing_side = dot3(shading_normal, wo);
  const float shading_incident_side = dot3(shading_normal, wi);
  if (!(fabsf(shading_outgoing_side) > 0.0f) ||
      !(fabsf(shading_incident_side) > 0.0f) ||
      !isfinite(shading_outgoing_side) ||
      !isfinite(shading_incident_side)) {
    return false;
  }
  const bool shading_transmitted =
      (shading_outgoing_side > 0.0f) != (shading_incident_side > 0.0f);
  return shading_transmitted == transmitted;
}
```

shadow origin 与后续 radiance origin 都走同一 helper：偏移轴始终是 $\mathbf n_g$，正负侧由真实新方向决定。这既避免透射连接从错误介质侧立即自交，也防止普通平滑 mesh 被倾斜着色法线推过真实表面：

<!-- source-snippet id="water-signed-direct-offset" path="src/device_programs.cu" anchor="offset_ray_origin" -->
```cpp
static __forceinline__ __device__ float3 offset_ray_origin(
    float3 position, float3 geometric_normal, float3 direction,
    float distance) {
  const float side = dot3(geometric_normal, direction) >= 0.0f
      ? 1.0f : -1.0f;
  return add(position, mul(geometric_normal, side * distance));
}
```

最重要的语义是 `trace_visible`：从当前水面散射一次后，连接线上遇到的**下一层透明边界也算遮挡**。旧实现把 shadow ray 沿直线穿过后续水/玻璃边界，再乘 $1-F$，却没有按 Snell 改变方向；那条路径既不是一条真实折线路径，也不是单顶点 NEE 的合法样本，现已删除。现在相机若要从漫反射面经过水面到灯，必须先由 BSDF 路径实际到达水面，再在这个水面顶点连接灯。该规则消除了直线跨界偏差，同时明确放弃自动求解多界面镜面连接。

## 7. 光滑水面的单次有界 Fresnel 分裂

`roughness: 0` 是严格 delta BSDF，普通灯面或环境方向采样命中其唯一反射/折射方向的概率为零，因此它不执行 NEE。为了不让最重要的首个光滑水面事件仍以 $F$ 与 $1-F$ 随机二选一，每个相机样本第一次命中光滑 `water_surface` 时确定性地产生至多两个子路径：

$$
\boldsymbol\beta_r=\boldsymbol\beta\odot\mathbf c\,F,
\qquad
\boldsymbol\beta_t=\boldsymbol\beta\odot\mathbf c\,(1-F)
\left(\frac{\eta_i}{\eta_t}\right)^2.
$$

$\mathbf c$ 是界面 `base_color`。全反射时 $F=1$，只继续反射，不创建空的透射状态。正常情形下透射分支立刻更新自己的介质栈；反射分支保留原栈。两边的 RNG 从同一父状态确定性 fork，避免分支执行顺序让后续随机数意外相同。

<!-- source-snippet id="water-bounded-split-state" path="src/device_programs.cu" anchor="At most one extra state is needed" -->
```cpp
    // At most one extra state is needed: the first smooth-water event forks
    // into deterministic Fresnel reflection and transmission, and both
    // children carry split_used=1. Keeping a single pending state bounds work
    // and storage to two path states per camera sample.
    int pending_path = 0;
    float3 pending_origin{};
    float3 pending_direction{};
    float3 pending_throughput{};
    float pending_previous_pdf = 0.0f;
    int pending_previous_delta = 1;
    FiniteLightMode pending_previous_light_mode = kFiniteLightPower;
    float3 pending_previous_position{};
    unsigned int pending_bounce = 0u;
    MediumState pending_media{};
    unsigned long long pending_rng_state = 0ull;
    unsigned long long pending_rng_increment = 1ull;
    unsigned int bounce_start = 0u;
```

只有一个 pending slot，且两个孩子都携带 `split_used = 1`，所以每样本同时最多两个路径状态；后续光滑水面或光滑玻璃恢复普通 Fresnel 随机采样，不会指数分叉。pending 状态还保存前驱选灯模式与未偏移的前驱位置，保证恢复分支后命中 emitter 时，MIS 从真实散射顶点而不是数值偏移后的 ray origin 重建灯方向 PDF。

<!-- source-snippet id="water-bounded-split-weights" path="src/device_programs.cu" anchor="++water_counters.delta_splits" -->
```cpp
        pending_path = 1;
        pending_origin = offset_ray_origin(
            hit.position, hit.geometric_normal, reflected);
        pending_direction = reflected;
        pending_throughput = clamp_nonnegative(
            mul(mul(throughput, base_color), reflectance));
        pending_previous_pdf = 1.0f;
        pending_previous_delta = 1;
        pending_previous_light_mode = current_light_mode;
        pending_previous_position = hit.position;
        pending_bounce = bounce + 1u;
        pending_media = media;
        pending_rng_state = reflected_rng.state;
        pending_rng_increment = reflected_rng.increment;
        ++water_counters.delta_splits;

        throughput = clamp_nonnegative(
            mul(mul(throughput, base_color),
                (1.0f - reflectance) * eta * eta));
        previous_pdf = 1.0f;
        previous_delta = 1;
        previous_light_mode = current_light_mode;
        previous_position = hit.position;
```

这个分裂只降低首个光滑水面二选一的方差。它不会寻找“漫反射点—多个光滑界面—灯”的约束路径，也不是 Manifold NEE（MNEE）、双向路径追踪或光子映射；光滑多界面焦散仍在范围外。

## 8. 安全统计、验证与限制

stats 分开记录 height evaluations、tile tests、roots reported、medium segments、rough NEE attempts/contributions 和 delta splits。solver overflows 或 medium errors 任一非零都会让主机拒绝输出。

<!-- source-snippet id="water-host-safety-gate" path="src/optix_renderer.cpp" anchor="water transport safety check failed" -->
```cpp
  if (water_totals.solver_overflows != 0ull ||
      water_totals.medium_errors != 0ull) {
    throw std::runtime_error(
        "water transport safety check failed: solver overflows=" +
        std::to_string(water_totals.solver_overflows) +
        ", medium errors=" + std::to_string(water_totals.medium_errors));
  }
```

定向 GPU fixture 检查固定 seed、粗糙反射/透射、全反射、两侧法线语义、深浅路径 RGB Beer、浸没玻璃的介质栈、depth-1 粗糙 NEE、透明中间边界阻断，以及后续真实水面顶点恢复贡献。绑定 emitter 在 depth 2 已能用 NEE 完成末端连接，未绑定的 BSDF-only 路径需要 depth 3 才能命中同一 emitter；因此对照按**等散射阶数**比较 bound depth 2 / unbound depth 3，其高 spp 线性 PFM 均值必须在 2% 内，三组低 spp seed 的 NEE ROI MSE 至多是 BSDF-only 的 50%。光滑 fixture 检查单次 split、全反射、Fresnel/$\eta$ 权重与确定性。

正式 Moonlit Stepwell 使用 `roughness=0.12`、512 spp、depth 12、direct 64 / indirect 16 贡献钳位，并为 gallery PNG 启用 OptiX AI Denoiser。所有线性均值、无偏性和 MSE 比较都通过 `render(linear_output=..., denoise=False, clamp_direct=0, clamp_indirect=0)` 保存 tone map 前的 PFM；因此降噪和有偏钳位都不参与上述数值结论。tile seam、漏交和构图还需人工检查，统计安全门负责拒绝数值异常。

当前模型仍有以下边界：

- 波浪是确定性静态正弦叠加，不是 CFD、浅水方程或海洋频谱动画；
- `water_surface` 只是有限顶界面，依赖场景的不透明池壁/底部封闭；
- SceneBuilder 强制相机 aperture 从水与玻璃外开始；普通 dielectric 只支持同材质双面、无 alpha 的闭合 sphere，水层加嵌套玻璃合计最多四层；
- 封面不依靠普通 dielectric sphere 表现冰晶；其非透明冷色粗糙 metal 代理是为了在不修改渲染器时保持介质安全门为零错误，不代表真实冰材质；
- 粗糙界面有单顶点 NEE/MIS，光滑首水面有一次有界 split；两者都不求解光滑多界面焦散或 MNEE；
- 网格插值着色法线采用 PBRT 风格的 `AbsDot`，但未实现 shading-normal adjoint correction；极端倾斜法线不保证严格互易性或能量守恒；
- GGX 介电是单次微表面散射，不补偿多次散射能量；RGB Beer 吸收不是波长采样，也没有体散射、悬浮物或泡沫。

Python 调用与约束见 [Python 场景 API](../PYTHON_API.md)，展示构图见 [Moonlit Stepwell](../EXAMPLES.md#moonlit-stepwell)。

[上一章：程序化体积火焰](11-procedural-volumetric-flame.md) · [返回目录](README.md) · [下一章：HDR 环境与重要性采样](13-hdr-environment-and-importance-sampling.md)
