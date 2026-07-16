# 05　直接光照、NEE 与 MIS

仅按 BSDF 随机游走在数学上可行，但一盏小灯或 HDR 环境中的高亮区域在表面半球中只占很小方向范围。随机射线可能经过成千上万次尝试也找不到它，画面便出现高方差亮点。SpectralDock 在 Lambert、metal 和非零粗糙度的 dielectric/water 表面主动连接有限灯与 HDR 环境样本，并逐盏连接 point/directional delta 灯。这叫 Next Event Estimation（NEE）。

## 1. 在灯面上取一个随机点

假设第 $i$ 盏显式面积灯以概率 $q_i$ 被选择，再在其面积 $A_i$ 上均匀取点 $\mathbf y$。相对于面积的联合 PDF 是

$$
p_A(\mathbf y)=\frac{q_i}{A_i}.
$$

矩形灯按两条边的均匀坐标取点；圆盘灯用 $r=\sqrt\xi$ 均匀采面积；球内或距球面很近的回退路径均匀采整个球面。

渲染方程却是对着色点 $\mathbf x$ 周围的方向积分，所以必须把面积 PDF 换成方向 PDF。令

$$
\boldsymbol\omega_i=\frac{\mathbf y-\mathbf x}{\|\mathbf y-\mathbf x\|},
\qquad
r=\|\mathbf y-\mathbf x\|,
$$

灯面法线为 $\mathbf n_l$，则

$$
p_\omega
=p_A\left|\frac{dA}{d\omega}\right|
=p_A\frac{r^2}{|\mathbf n_l\cdot(-\boldsymbol\omega_i)|}.
$$

代入 $p_A=q_i/A_i$，得到

$$
\boxed{
p_L(\boldsymbol\omega_i)=
\frac{q_i r^2}
{A_i\,|\mathbf n_l\cdot(-\boldsymbol\omega_i)|}
}
$$

这正是第 2 章立体角关系的倒数变换。PDF 中必须保留对应估计器的灯索引密度；漏掉它就会让改变采样分布也改变收敛能量。普通单样本顶点使用实际 $q_i$。粗糙 water 使用两个提议 $q_G(i)$ 与 $q_U(i)=1/N$，两份样本共用 balance 密度 $m_i=q_G(i)+q_U(i)$。顶点模式的完整构造见[第 13 章第 5 节](13-hdr-environment-and-importance-sampling.md#5-有限灯也要选择分布)。

例如 $q_i=0.5$、$A_i=4$、$r=3$、灯面余弦为 0.5 时，$p_A=1/8$，而 $dA/d\omega=18$，所以 $p_\omega=2.25\ \mathrm{sr}^{-1}$。距离越远，同一面积覆盖的方向范围越小，单位立体角的概率密度反而越大。

所有支持 NEE 的连续 BSDF 顶点都对 **sphere 灯**做一层方差优化。令球心为 $\mathbf c$、半径为 $R$、$d=\|\mathbf c-\mathbf x\|$。当着色点位于球外且 $d>R+\varepsilon$ 时，可见球盖对应一个半角 $\theta_{\max}$ 的圆锥：

$$
\sin^2\theta_{\max}=\frac{R^2}{d^2},\qquad
\cos\theta_{\max}=\sqrt{1-\frac{R^2}{d^2}},\qquad
\Omega=2\pi(1-\cos\theta_{\max}).
$$

在这个圆锥内均匀采方向，并与球求最近正交点，因而每个样本都落在从 $\mathbf x$ 可见的球盖上。包含选灯概率的方向 PDF 直接是

$$
\boxed{p_L(\boldsymbol\omega_i)=
\frac{q_i^*}{2\pi(1-\cos\theta_{\max})}},
$$

其中普通顶点的 $q_i^*=q_i$；粗糙 water 的两份确定性样本使用 $q_i^*=m_i=q_G(i)+q_U(i)$。

这不是把球灯变亮，只是不再把样本浪费在背向顶点的球面上。距离很大时，实现用 $1-\cos\theta_{\max}=\sin^2\theta_{\max}/(1+\cos\theta_{\max})$ 避免相近数相减：

<!-- source-snippet id="water-sphere-visible-solid-angle-pdf" path="src/device_programs.cu" anchor="const float one_minus_cos =" -->
```cpp
  const float sin2_theta_max =
      fminf(fmaxf(radius2 / distance2, 0.0f), 1.0f);
  const float cos_theta_max =
      sqrtf(fmaxf(0.0f, 1.0f - sin2_theta_max));
  // This stable form avoids losing the cone measure for a distant sphere.
  const float one_minus_cos =
      sin2_theta_max / fmaxf(1.0f + cos_theta_max, 1.0e-20f);
  if (!(one_minus_cos > 0.0f) || !isfinite(one_minus_cos)) return 0.0f;
  const float pdf = 1.0f / (2.0f * kPi * one_minus_cos);
  if (!isfinite(pdf)) return 0.0f;
  if (one_minus_cos_out != nullptr) {
    *one_minus_cos_out = one_minus_cos;
  }
  return pdf;
}
```

若顶点在球内或距球面不超过 $\varepsilon$，可见圆锥参数不适用，代码回退到整球面面积采样和前述 Jacobian。rectangle 与 disk 始终保持面积采样。

`light_direction_pdf` 逐项实现了这个换元：`distance2` 是 $r^2$，`cos_light` 是灯面余弦，`area` 对应 $A_i$，`selection_pdf` 对普通顶点是 $q_i$，对两种 water 样本模式都是 $m_i=q_G(i)+q_U(i)$。两面灯先对余弦取绝对值；单面灯背面或退化面积直接返回零。

<!-- source-snippet id="light-area-to-solid-angle-pdf" path="src/device_programs.cu" anchor="finite_light_selection_pdf" -->
```cpp
  const float area =
      light.area > 0.0f ? light.area
                        : length3(cross3(light.edge_u, light.edge_v));
  if (cos_light <= 0.0f || area <= 0.0f) {
    return 0.0f;
  }
  const float selection_pdf = finite_light_selection_pdf(light, mode);
  if (!(selection_pdf > 0.0f)) return 0.0f;
  if (light.type == spectraldock::kLightSphere) {
    const float solid_angle_pdf =
        sphere_visible_solid_angle_pdf(light, from);
    if (solid_angle_pdf > 0.0f) {
      return selection_pdf * solid_angle_pdf;
    }
  }
  return selection_pdf * distance2 / (cos_light * area);
}
```

当前 Python API 中的显式灯都是单面：rectangle/disk 只从法线正面发光，sphere 只向外发光。设备结构预留了 `two_sided` 分支，但 `Renderer.light()` 未暴露它。所有球外连续 BSDF 顶点使用可见立体角，球内或近球路径才均匀采整个球面。Moonlit Stepwell 的月灯是 disk，不使用这个球灯特例；水下 sphere 灯以及其他场景的球灯都会受益。

## 2. 二值可见性与当前介电事件

从 $\mathbf x$ 到 $\mathbf y$ 发一条有限长度阴影射线。若中间没有其他几何体，记可见性 $V(\mathbf x,\mathbf y)=1$；被遮挡则为 0。

一份灯光采样的直接光估计为

$$
\widehat{\mathbf L}_{\text{direct}}=
\frac{
V(\mathbf x,\mathbf y)
\,\mathbf L_e(\mathbf y\rightarrow\mathbf x)
\odot f_s(\mathbf x,\boldsymbol\omega_i,\boldsymbol\omega_o)
\,c_s(\mathbf n,\boldsymbol\omega_i)\,w_L
}{p_L(\boldsymbol\omega_i)}.
$$

对 Lambert/metal，$c_s=\max(0,\mathbf n\cdot\boldsymbol\omega_i)$；粗糙介电质允许透射到法线另一侧，所以 $c_s=|\mathbf n\cdot\boldsymbol\omega_i|$。BSDF 自身再按方向符号选择反射或透射公式。

一个公式同时解释了几个常见现象：

- 遮挡让 $V=0$，形成阴影；
- 面积灯上不同点可能部分可见，形成软阴影；
- $r^2$ 出现在 PDF 分母的倒数中，自然产生距离平方衰减；
- 普通顶点只选一盏有限灯；粗糙 water 各取一份 $q_G$ 与 $q_U$ 样本，并在分母中用 $q_G+q_U$ 补偿。

可见性始终是二值的：从当前顶点完成一次 BSDF 散射后，连接线上任何后续有效表面——包括 dielectric 或 water——都把 $V$ 置零；alpha cutoff 裁掉的纹素仍不遮挡。粗糙介电 NEE 可以在**当前界面**连接反射侧或透射侧的灯：透射连接把起点偏移到另一侧，并在介质栈副本中切换一次当前边界，再沿同介质段乘 RGB Beer 衰减。它不会让一条未弯折 shadow ray 穿过下一层透明界面。完整介质语义见[第 12 章第 6 节](12-runtime-analytic-water.md#6-粗糙水面的-nee只连接当前散射事件)。

直接光函数的末尾把公式各项接在一起：先从表面沿法线偏移起点，再向灯点发有限阴影射线；不可见时贡献为零。可见时返回值依次相乘 $f_s$、$L_e$、$\cos\theta$ 与策略权重，最后除以 $p_L$。普通有限灯与 BSDF-hit 使用 power heuristic；粗糙 water 的两份灯样本与 BSDF-hit 使用第 4 节的三技术 balance。

<!-- source-snippet id="direct-light-visibility-and-estimator" path="src/device_programs.cu" anchor="const float3 contribution =" -->
```cpp
  // Rough water takes one qG and one qU sample. Their shared light density is
  // pL=(qG+qU)c. When a bound surface emitter can also be reached by the next
  // BSDF ray, all three deterministic techniques use balance weights over
  // pL+pB. Flame and unbound lights have no BSDF endpoint competitor.
  const bool water_bsdf_competes =
      is_water_finite_light_mode(light_mode) &&
      light.geometry_index >= 0 && next_bsdf_ray_exists;
  const float mis = water_bsdf_competes
      ? balance_heuristic(light_pdf, bsdf_pdf)
      : direct_light_mis_weight(
            light_pdf, bsdf_pdf,
            !is_water_finite_light_mode(light_mode) &&
                light.geometry_index >= 0,
            next_bsdf_ray_exists);
  const float3 contribution =
      mul(mul(mul(bsdf, light.emission), surface_transmittance),
          no_l * mis / light_pdf);
  if (count_rough_water && max_component(contribution) > 0.0f) {
    ++water_counters.rough_nee_contributions;
  }
  return contribution;
```

`direct_segment_transmittance` 先执行二值 `trace_visible`，只有当前散射是粗糙介电透射时才在栈副本中切换一次并计算 Beer；后续 `track_volume` 再估计 flame 吸收。`surface_transmittance` 因而不再代表“穿过任意透明边界”，只代表当前事件之后的同介质传播。粗糙水面细节见第 12 章，完整 flame 体积推导见第 11 章。

### 2.1 Point 与 directional 的 delta NEE

point 和 directional 没有灯面 PDF。渲染器把它们保存在独立索引表，在每个支持 NEE 的顶点逐盏求值，最多 32 盏。point 的连接向量、距离和衰减为

$$
\boldsymbol\omega_i=\frac{\mathbf p_l-\mathbf x}{r},
\qquad r=\|\mathbf p_l-\mathbf x\|,
\qquad a(r)=\frac{1}{r^2};
$$

directional 的 `direction` 已由原生 SceneBuilder 归一化，直接作为从表面指向光源的 $\boldsymbol\omega_i$，且 $a=1$。源码用有限 shadow distance 连接 point，用 `kInfinity` 连接 directional：

<!-- source-snippet id="delta-light-direction-and-distance" path="src/device_programs.cu" anchor="radiometric_distance2" -->
```cpp
    float3 wi;
    float radiometric_distance2 = 1.0f;
    float radiometric_distance = kInfinity;
    float shadow_distance = kInfinity;
    if (is_point) {
      const float3 displacement = sub(light.p0, hit.position);
      radiometric_distance2 = length2(displacement);
      if (!(radiometric_distance2 > 0.0f) ||
          !isfinite(radiometric_distance2)) {
        continue;
      }
      radiometric_distance = sqrtf(radiometric_distance2);
      wi = divv(displacement, radiometric_distance);
      shadow_distance = radiometric_distance;
    } else {
      if (!(length2(light.axis) > 1.0e-20f)) continue;
      wi = normalize3(light.axis);
    }
```

其直接贡献是 $\boldsymbol\beta f_s L |\mathbf n\cdot\boldsymbol\omega_i|a(r)$，其中 point 的 $L$ 是 `intensity`，directional 的 $L$ 是 `irradiance`。代码继续复用相同的粗糙介电反射/透射侧别、Beer 段、表面可见性与 flame 透射。因为连续 BSDF 不可能命中零立体角 delta 灯，灯侧 MIS 权重恒为 1；逐灯求和也不需要除以离散选灯概率。这让少量常用布光稳定可控，代价是 shadow-ray 数量随 delta 灯数线性增加。

<!-- source-snippet id="shadow-ray-visibility-query" path="src/device_programs.cu" anchor="OPTIX_RAY_FLAG_TERMINATE_ON_FIRST_HIT" -->
```cpp
static __forceinline__ __device__ bool trace_visible(
    float3 origin, float3 direction, float distance, int light_index,
    unsigned long long& traced_rays) {
  unsigned int visible = 0u;
  unsigned int target_light = static_cast<unsigned int>(light_index);
  ++traced_rays;
  optixTrace(params.traversable, origin, direction, params.scene_epsilon,
             fmaxf(distance - params.scene_epsilon, params.scene_epsilon),
             0.0f, OptixVisibilityMask(255),
             OPTIX_RAY_FLAG_TERMINATE_ON_FIRST_HIT |
                 OPTIX_RAY_FLAG_DISABLE_CLOSESTHIT,
             spectraldock::kRayShadow, spectraldock::kRayTypeCount,
             spectraldock::kRayShadow, visible, target_light);
  return visible != 0u;
}
```

## 3. 为什么需要多种采样策略

NEE 擅长寻找小而亮的灯，BSDF 采样擅长寻找尖锐材质瓣：

- 粗糙漫反射面对小灯：灯光采样通常更好；
- 很光滑的 GGX 表面：BSDF 采样容易找到高光方向；
- 完美介电反射/折射：只有 delta 方向有贡献，普通面积灯方向采样无法匹配它。

对普通表面的有限灯和所有环境照明，同一条“当前表面到光源”的路径可能由两种策略生成：

1. NEE 先选灯面点并连接过去；
2. BSDF 先选方向，后续射线恰好命中那个灯面。

若简单把完整估计相加，同一路径会被重复计算。Multiple Importance Sampling（MIS）用权重把贡献在策略间分配。普通表面比较一份 NEE 与一份 BSDF 样本；粗糙 water 的有限灯比较功率选灯、均匀选灯和 BSDF 三种技术。

![NEE、BSDF 采样与 MIS 权重](figures/path-nee-mis.svg)

*图 4：普通表面的单份 NEE 与 BSDF 双策略示意；粗糙 water 的有限灯 G/U/B 三技术 balance 见第 4.1 节。*

## 4. Power heuristic

设灯光方向 PDF 为 $p_L$，BSDF 方向 PDF 为 $p_B$。普通有限灯与 HDR 环境的 NEE/BSDF 策略各用一个样本，采用指数为 2 的 power heuristic：

$$
w_L=\frac{p_L^2}{p_L^2+p_B^2},
\qquad
w_B=\frac{p_B^2}{p_B^2+p_L^2}.
$$

当 $p_L,p_B$ 至少一个为正，且两侧使用同一对 PDF 时，$w_L+w_B=1$。恰好一个 PDF 为零时，可生成该路径的策略权重为 1，另一策略为 0。两者都为零时，`power_heuristic` 返回 0；这个结果不参与有效贡献，因为调用点会先拒绝无效样本，例如 NEE 在 `bsdf_pdf <= 0` 时直接返回。更擅长生成该方向的策略得到更大权重，但另一策略并不会被硬切断。实现会先用 $\max(p_L,p_B)$ 归一化两项再平方；这不改变正 PDF 下的公式，却避免大 PDF 平方溢出、小 PDF 平方同时下溢，或人为截断分母破坏互补性。

源码先用较大 PDF 作为 `scale`。两个 PDF 至少一个为正时，归一化后的 `a`、`b` 至少有一个为 1，二者平方后仍保留原比值；前两个提前返回分别覆盖待求权重的 PDF 非正，以及竞争 PDF 非正的情况。

<!-- source-snippet id="stable-power-heuristic" path="src/device_programs.cu" anchor="float power_heuristic" -->
```cpp
static __forceinline__ __device__ float power_heuristic(
    float pdf_a, float pdf_b) {
  if (!(pdf_a > 0.0f)) return 0.0f;
  if (!(pdf_b > 0.0f)) return 1.0f;
  const float scale = pdf_a > pdf_b ? pdf_a : pdf_b;
  const float a = pdf_a / scale;
  const float b = pdf_b / scale;
  const float aa = a * a;
  const float bb = b * b;
  return aa / (aa + bb);
}
```

- 普通有限灯与环境 NEE 项各自乘对应的 $w_L$；
- 普通 BSDF 路径稍后命中绑定几何的 emitter 时乘 $w_B$；
- 两个 PDF 都以当前着色点的**方向测度**表示，才能放进同一公式。
- 粗糙 water 的有限灯使用下一小节的三技术 balance；环境项仍照常使用上述 power MIS。

例如 $p_L=0.8$、$p_B=0.2$ 时

$$
w_L=\frac{0.64}{0.64+0.04}\approx0.941,
\qquad
w_B\approx0.059.
$$

这并不是说 94.1% 的光来自灯光采样，而是说在该方向上，灯光策略的估计通常更可靠。

### 4.1 粗糙 water 的三技术 balance

对第 $i$ 盏灯，令功率索引、均匀索引与给定灯后的条件方向密度分别为 $q_G(i)$、$q_U(i)$ 和 $c_i(\boldsymbol\omega)$。两份灯技术的密度为

$$
p_G=q_G(i)c_i(\boldsymbol\omega),\qquad
p_U=q_U(i)c_i(\boldsymbol\omega),\qquad
p_L=p_G+p_U.
$$

每个粗糙 water 顶点确定性地从 $G$、$U$ 各取一个样本。若灯绑定到可命中的表面，而且当前深度确实允许下一条 BSDF 射线，则把完整 BSDF 方向密度 $p_B$ 作为第三种技术。两份 direct 样本各自使用

$$
w_L=\frac{p_L}{p_L+p_B},
\qquad
\frac{f}{p_L}w_L=\frac{f}{p_G+p_U+p_B},
$$

而 BSDF continuation 命中同一 emitter 时，路径吞吐量已经含有 $f/p_B$，只需再乘

$$
w_B=\frac{p_B}{p_L+p_B}.
$$

因此三份样本的期望系数为

$$
\frac{p_G}{p_G+p_U+p_B}+
\frac{p_U}{p_G+p_U+p_B}+
\frac{p_B}{p_G+p_U+p_B}=1.
$$

这里必须使用 balance heuristic，而不能把两份灯样本再次当成一个 power-heuristic 样本。若不存在下一条 BSDF 射线、灯没有绑定几何，或 flame 没有可命中的表面端点，则 $p_B$ 不属于可用策略，灯权重退化为 1。单面灯背面、球内无可见锥支持等方向令 $p_L=0$，BSDF-hit 权重自然退化为 1。HDR environment 仍在独立域使用上一节的 power heuristic。

<!-- source-snippet id="water-three-technique-balance" path="src/device_programs.cu" anchor="water_bsdf_competes" -->
```cpp
  const bool water_bsdf_competes =
      is_water_finite_light_mode(light_mode) &&
      light.geometry_index >= 0 && next_bsdf_ray_exists;
  const float mis = water_bsdf_competes
      ? balance_heuristic(light_pdf, bsdf_pdf)
      : direct_light_mis_weight(
            light_pdf, bsdf_pdf,
            !is_water_finite_light_mode(light_mode) &&
                light.geometry_index >= 0,
            next_bsdf_ray_exists);
```

## 5. Delta 与不能被另一策略生成的路径

MIS 只应比较两种策略都可能生成的路径：

- 上一事件是光滑介电 delta 时，普通 NEE 不可能生成精确的反射/折射方向，命中 emitter 的权重保持 1；
- 没有可命中几何的解析面积灯只能由 NEE 得到，NEE 权重为 1；
- 发光几何没有绑定到显式灯时，`light_direction_pdf` 为 0，路径命中贡献也保持完整权重；
- 在最后一个 `max_depth` 表面事件，没有下一条 BSDF 射线参与竞争，即使灯绑定了几何，NEE 权重也为 1。
- 粗糙 water 的绑定表面灯只有在下一条 BSDF 策略真实存在时才纳入三技术 balance；最后一层、背面、球内无支持、未绑定灯和 flame 都删除不存在的竞争密度。
- point/directional 没有可命中的 emitter 端点，只由逐灯 delta NEE 生成，权重固定为 1。

两个设备局部策略函数把这些边界写成布尔条件。NEE 只有在灯可被后继射线命中且下一条 BSDF 射线确实存在时才竞争；emitter-hit 则在前驱为 delta 或 emitter 未绑定显式灯时保留完整贡献。

<!-- source-snippet id="mis-competing-strategy-policy" path="src/device_programs.cu" anchor="direct_light_mis_weight" -->
```cpp
static __forceinline__ __device__ float direct_light_mis_weight(
    float light_pdf, float bsdf_pdf, bool light_can_be_hit,
    bool next_bsdf_ray_exists) {
  return light_can_be_hit && next_bsdf_ray_exists
             ? power_heuristic(light_pdf, bsdf_pdf)
             : 1.0f;
}

static __forceinline__ __device__ float emitter_hit_mis_weight(
    float bsdf_pdf, float light_pdf, bool previous_event_was_delta,
    bool emitter_is_bound_to_light) {
  return previous_event_was_delta || !emitter_is_bound_to_light
             ? 1.0f
             : power_heuristic(bsdf_pdf, light_pdf);
}
```

水面 emitter 端补上三技术 balance 的 BSDF 权重；支持外命中仍走普通策略：

<!-- source-snippet id="water-finite-emitter-balance" path="src/device_programs.cu" anchor="use_water_finite_balance" -->
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
```

## 6. 统一的 RR/MIS PDF 约定与末端深度

SpectralDock 采用“RR 独立于 MIS”的约定。局部方向采样得到的 $p_B$ 原样保存到 `previous_pdf`，不乘俄罗斯轮盘生存率 $s$。轮盘只对路径吞吐量进行期望补偿：

$$
\boldsymbol\beta\leftarrow\frac{\boldsymbol\beta}{s},
\qquad
p_{\mathrm{prev}}=p_B.
$$

这样，普通有限灯或环境 NEE 在当前顶点计算 $w_L$，以及幸存 BSDF 路径稍后命中 emitter 或 miss 时计算 $w_B$，始终使用相同的原始 $p_L,p_B$，互补关系不随 RR 改变。水面的三技术 balance 同样使用 RR 前的局部 $p_B$，不把生存率混入策略密度；轮盘死亡样本的 $1/s$ 期望补偿仍保持整体无偏。

末端深度按“策略是否真实存在”处理：最后一个允许的表面事件仍执行完整 NEE，但因为不会追踪下一条 BSDF 射线，直接光权重为 1；累积直接光后立即结束，不再消耗 BSDF 或 RR 随机数。相机直接命中、delta 前驱、未绑定灯和末端 NEE 都由设备局部策略函数返回完整权重。

## 7. 当前直接光采样的边界

[`sample_finite_direct_light`](../../src/device_programs.cu) 与 [`sample_environment_direct_light`](../../src/device_programs.cu) 在 Lambert、metal 和 `roughness > 0` 的 dielectric/water 表面执行。`roughness = 0` 的介电质仍是 delta BSDF，通过继续路径寻找灯光；首个光滑 water 命中另有一次有界 Fresnel 分裂，但不是普通 NEE。

有限灯 NEE 支持 rectangle、disk、sphere 面积灯和程序化 flame，HDR environment 则通过独立的无限远 NEE 域采样；point/directional 在第三个域逐灯求值。以下光源仍不被主动采样：

- constant、sky 渐变和太阳瓣；
- mesh emitter；
- 任何绑定纹理的 emitter。

它们仍可由 BSDF 路径命中或 miss 得到，因此不是必然缺失，但小而亮时可能有很高方差。`Renderer.integrator(direct_light_sampling="importance")` 使普通空气顶点按亮度与面积/体积代理选择一个有限灯，粗糙水面为了同时照顾强月光与弱水下灯，确定性地各取一个全局分布样本和均匀索引样本，介质内的普通顶点则只用均匀选灯。HDR 环境方向仍按亮度乘 texel 立体角选择，不受有限灯顶点模式影响；delta 灯也不进入这个随机 CDF。完整构造见[第 13 章](13-hdr-environment-and-importance-sampling.md)。

## 8. 对应实现

设备端采样与 RR/MIS 决策都实现在 [`src/device_programs.cu`](../../src/device_programs.cu)。相关 helper 位于该文件的匿名命名空间，与调用点一起编译为 OptiX IR；不存在需要同步维护的 CPU 渲染副本：

- `sample_light_surface`、`sample_visible_sphere_direction`：矩形/圆盘面积采样、球内回退与球外可见锥采样；
- `light_direction_pdf`：面积或球锥 PDF 到统一方向测度的换元；
- `trace_visible`：有限或无限距离阴影射线；
- `direct_segment_transmittance`：当前粗糙透射事件的介质栈副本与 Beer 段，并阻断后续透明边界；
- `sample_finite_direct_light`：有限灯 NEE、BSDF 评估，以及普通顶点的 power 权重或水面的 balance 权重；
- `sample_environment_direct_light`：无限远环境 NEE、透射和 $w_L$；
- `accumulate_delta_direct_lights`：逐盏 point/directional NEE、逆平方或恒定照明，以及固定为 1 的 MIS 权重；
- raygen 调用点：分别累加有限灯、环境和 delta 灯三个 NEE 域；
- `power_heuristic`、`balance_heuristic`：数值稳定的普通双策略权重与水面三技术权重；
- `resolve_continuation`：RR 存活、吞吐量补偿和原始 BSDF PDF；
- `direct_light_mis_weight`、`emitter_hit_mis_weight`：普通域只在竞争策略真实存在时使用 MIS；
- `__raygen__pathtrace` 的 emitter 分支：使用上一次 `previous_pdf` 计算普通 $w_B$，或补齐水面三技术 balance 的 BSDF 端点权重。

下一章转向另一个基础问题：GPU 怎样快速回答数百万次“最近命中了哪个表面？”

[上一章：Monte Carlo 路径追踪](04-monte-carlo-path-tracing.md) · [返回目录](README.md) · [下一章：几何、可见性与 BVH](06-geometry-visibility-and-bvh.md)
