# 03　材质与 BSDF：表面怎样改变光

渲染方程中的 $f_s$ 决定光到达表面后去向哪里。本章依次解释 SpectralDock 的四类材质：Lambert 漫反射、GGX 金属、光滑/粗糙介电质和发光表面。

## 1. BSDF 是方向之间的“路由规则”

固定观察方向 $\boldsymbol\omega_o$ 后，BSDF

$$
f_s(\boldsymbol\omega_i,\boldsymbol\omega_o)
$$

描述从 $\boldsymbol\omega_i$ 到达的光，有多少被散射到 $\boldsymbol\omega_o$。可以把它想成画在表面上方的方向分布：

- 分布宽而均匀：外观接近哑光；
- 分布窄且集中：外观接近镜面；
- 只有一个反射或折射方向：理想光滑界面。

![Lambert、两种粗糙度的 GGX 和介电质散射方向](figures/material-scattering.svg)

*图 3：黄色箭头是入射方向，青色箭头是可能的出射方向，轮廓表示 BSDF 的相对集中程度。图中的介电箭头画的是 `roughness = 0` 的离散 delta 情形；非零粗糙度会把反射与折射都展开成连续 GGX 瓣。*

### 1.1 几何法线与有效着色法线

一个平滑网格交点同时保留两根单位法线：

- $\mathbf n_g$ 是朝当前射线一侧的**定向几何法线**，由真实 primitive 表面决定；
- $\mathbf n_s^{\mathrm{eff}}$ 是绕 $\mathbf n_g$ 与出射方向 $\boldsymbol\omega_o$ 定向的**有效着色法线**，mesh 可由顶点法线重心插值得到；没有独立着色法线时它与 $\mathbf n_g$ 相同。

$\mathbf n_s^{\mathrm{eff}}$ 建立 Lambert 和 GGX 的局部坐标、法线分布、BSDF/PDF 与 PBRT 风格的 `AbsDot` 余弦；因此本章后续连续 BSDF 公式中未加下标的 $\mathbf n$ 都表示 $\mathbf n_s^{\mathrm{eff}}$。$\mathbf n_g$ 另外负责 `front_face`、真实反射/透射半空间、介质栈转换和所有表面射线偏移。粗糙介电的微表面瓣由 $\mathbf n_s^{\mathrm{eff}}$ 塑形，但方向必须同时通过 $\mathbf n_g$ 的物理侧别；光滑 delta dielectric/water 的 Fresnel、Snell 反射/折射方向则完全使用 $\mathbf n_g$，不受顶点法线扭曲。

这个实现不乘 Veach 的 shading-normal adjoint correction。它保持相机辐亮路径的一致 `AbsDot` 约定，但不对极端倾斜的插值法线承诺严格互易性或能量守恒。

## 2. Lambert 漫反射

理想漫反射假设表面把光均匀送往上方所有观察方向。BRDF 为

$$
f_r=\frac{\boldsymbol\rho}{\pi},
$$

其中 $\boldsymbol\rho=(\rho_r,\rho_g,\rho_b)$ 是 `base_color`，可理解为每个 RGB 通道的反射比例。

为什么要除以 $\pi$？半球上的余弦积分为

$$
\int_{\mathcal H^2}\cos\theta\,d\omega=\pi.
$$

因此将 $\boldsymbol\rho/\pi$ 代入渲染方程，白色均匀环境下的总反射比例恰好是 $\boldsymbol\rho$，不会凭空多出一个 $\pi$ 倍能量。

### 2.1 余弦加权采样为什么特别合适

渲染方程的被积函数自带 $\cos\theta$。SpectralDock 用同样形状的 PDF 选择方向：

$$
p_B(\boldsymbol\omega_i)=
\frac{\max(0,\mathbf n_s^{\mathrm{eff}}\cdot\boldsymbol\omega_i)}{\pi}.
$$

一次随机样本的路径权重便化简为

$$
\frac{f_r\cos\theta}{p_B}
=\frac{(\boldsymbol\rho/\pi)\cos\theta}{\cos\theta/\pi}
=\boldsymbol\rho.
$$

这就是 [`sample_bsdf`](../../src/device_programs.cu) 的 Lambert 分支把 `evaluation.f_cos / evaluation.pdf` 化简为 `base_color` 的原因。代码不是漏掉了 BRDF、余弦或 PDF；它们在代数上已经约掉。

### 源码对照：Lambert 采样与化简后的权重

<!-- source-snippet id="lambert-cosine-sampling" path="src/device_programs.cu" anchor="kMaterialLambertian" -->
```cpp
  if (material.type == spectraldock::kMaterialLambertian) {
    const float r1 = rng.next();
    const float r2 = rng.next();
    const float radius = sqrtf(r1);
    const float phi = 2.0f * kPi * r2;
    const float3 local =
        f3(radius * cosf(phi), radius * sinf(phi), sqrtf(1.0f - r1));
    sample.wi = local_to_world(local, n);
    const BsdfEvaluation evaluation = evaluate_bsdf(
        material, base_color, n, geometric_n, wo, sample.wi, 1.0f, 1.0f);
    sample.pdf = evaluation.pdf;
    if (sample.pdf > 0.0f) {
      sample.weight = divv(evaluation.f_cos, sample.pdf);
      sample.valid = max_component(sample.weight) > 0.0f ? 1 : 0;
    }
    sample.delta = 0;
    return sample;
  }
```

`r1`、`r2` 是两个均匀随机数，局部方向的 $z=\sqrt{1-r_1}$ 产生余弦加权半球分布；`local_to_world` 再把它绕有效着色法线 `n` 旋转到世界坐标。`evaluate_bsdf` 返回融合余弦的 `f_cos` 和同一方向 PDF，二者相除对应化简后的 $\boldsymbol\rho$。$\mathbf n_g$ 的半空间检查仍会拒绝穿到真实表面背后的样本；`delta = 0` 明确它是连续分布。

## 3. GGX 粗糙金属

粗糙金属可想成大量方向不同的微小镜面。BSDF 局部宏观法线是 $\mathbf n=\mathbf n_s^{\mathrm{eff}}$，真正完成一次镜面反射的微表面法线是半程向量

$$
\mathbf h=
\mathrm{normalize}(\boldsymbol\omega_o+\boldsymbol\omega_i).
$$

只有法线接近 $\mathbf h$ 的微镜面，才能把一个方向反射到另一个方向。

### 3.1 粗糙度与法线分布

当前实现把用户粗糙度转换为

$$
\alpha=\max(\text{roughness}^2,0.001).
$$

GGX 法线分布函数为

$$
D(\mathbf h)=
\frac{\alpha^2}
{\pi\left[(\mathbf n\cdot\mathbf h)^2(\alpha^2-1)+1\right]^2}.
$$

小 $\alpha$ 让微法线集中在 $\mathbf n$ 附近，高光尖锐；大 $\alpha$ 让它们分散，高光变宽。即使 `roughness = 0`，$\alpha$ 仍被钳到 0.001，所以它不是数学上的完美 delta 镜面。

### 3.2 遮蔽、Fresnel 与完整 BRDF

斜着排列的微表面可能互相遮挡。SpectralDock 使用 Smith 项

$$
G_1(c)=
\frac{2c}{c+\sqrt{\alpha^2+(1-\alpha^2)c^2}},
$$

$$
G=G_1(\mathbf n\cdot\boldsymbol\omega_o)
G_1(\mathbf n\cdot\boldsymbol\omega_i).
$$

四个字母的职责是：$D$ 描述微法线朝向分布，$G$ 描述微表面互相遮挡，$\mathbf F$ 是随角度变化的 Fresnel 反射率，$\mathbf F_0$ 是正入射反射率；$G_1$ 的输入 $c$ 是 $[0,1]$ 内的方向余弦。

Fresnel 效应表示掠射角反射通常更强。Schlick 近似为

$$
\mathbf F=\mathbf F_0+
(\mathbf 1-\mathbf F_0)
(1-\boldsymbol\omega_o\cdot\mathbf h)^5.
$$

### 源码对照：GGX 的 $D$、$G_1$ 与 $\mathbf F$

<!-- source-snippet id="ggx-distribution-geometry-fresnel" path="src/device_programs.cu" anchor="ggx_distribution" -->
```cpp
static __forceinline__ __device__ float ggx_distribution(
    float no_h, float alpha) {
  const float a2 = alpha * alpha;
  const float d = no_h * no_h * (a2 - 1.0f) + 1.0f;
  return a2 / fmaxf(kPi * d * d, 1.0e-20f);
}

static __forceinline__ __device__ float ggx_g1(float no_x, float alpha) {
  const float a2 = alpha * alpha;
  return 2.0f * no_x /
         fmaxf(no_x + sqrtf(a2 + (1.0f - a2) * no_x * no_x), 1.0e-20f);
}

static __forceinline__ __device__ float3 fresnel_schlick(
    float cos_theta, float3 f0) {
  const float x = 1.0f - fminf(fmaxf(cos_theta, 0.0f), 1.0f);
  const float x2 = x * x;
  const float x5 = x2 * x2 * x;
  return add(f0, mul(sub(f3(1.0f, 1.0f, 1.0f), f0), x5));
}
```

`no_h`、`no_x` 和 `cos_theta` 分别承载 $\mathbf n\cdot\mathbf h$、$G_1$ 的余弦 $c$ 与 $\boldsymbol\omega_o\cdot\mathbf h$。实现预先计算 `a2`、`x2`、`x5`，减少重复乘法；分母用 `fmaxf(..., 1.0e-20f)` 防止极端方向产生除零或非有限值，Fresnel 输入则先钳到 $[0,1]$。

于是 GGX BRDF 为

$$
f_r=
\frac{\mathbf F D G}
{4(\mathbf n\cdot\boldsymbol\omega_o)
(\mathbf n\cdot\boldsymbol\omega_i)}.
$$

这里分母中的换行是普通乘法：即 $4\,n_o n_i$，不是加法。

当前 `Renderer.material(type="metal", ...)` 直接构造纯金属材质，等价于把 `metallic` 固定为 1，所以实际的 $\mathbf F_0$ 直接取自 `base_color`。这是一种纯金属镜面微表面模型，不是常见的“金属度工作流”，也不含漫反射与镜面混合。

### 源码对照：完整 BRDF 与方向 PDF

<!-- source-snippet id="ggx-brdf-direction-pdf" path="src/device_programs.cu" anchor="half_vector" -->
```cpp
    const float3 half_vector = mul(add(wo, wi), rsqrtf(half_length2));
    const float no_h = abs_dot(n, half_vector);
    const float vo_h = abs_dot(wo, half_vector);
    if (!(no_h > 0.0f) || !(vo_h > 0.0f)) {
      return result;
    }
    const float alpha =
        fmaxf(material.roughness * material.roughness, 0.001f);
    const float d = ggx_distribution(no_h, alpha);
    const float g = ggx_g1(no_v, alpha) * ggx_g1(fabsf(no_l), alpha);
    const float3 dielectric_f0 = f3(0.04f, 0.04f, 0.04f);
    const float3 f0 =
        lerp3(dielectric_f0, base_color,
              fminf(fmaxf(material.metallic, 0.0f), 1.0f));
    const float3 fresnel = fresnel_schlick(vo_h, f0);
    // Multiplying by abs(dot(ns, wi)) analytically cancels the same factor in
    // the microfacet denominator, including shading-back light directions.
    result.f_cos = mul(
        fresnel, d * g / fmaxf(4.0f * no_v, 1.0e-20f));
    if (no_l > 0.0f) {
      const float half_pdf = ggx_visible_normal_pdf(
          n, wo, half_vector, alpha);
      result.pdf = half_pdf / fmaxf(4.0f * vo_h, 1.0e-20f);
    }
```

`wo`、`wi`、`n` 分别对应 $\boldsymbol\omega_o$、$\boldsymbol\omega_i$、$\mathbf n_s^{\mathrm{eff}}$，而 `no_v`、`no_l` 是两个着色余弦。`result.f_cos` 已把 PBRT 风格的 $|n_i|$ 乘进 BRDF，因此它与微表面分母中的同一项解析约消；`half_pdf` 是观察方向条件下的可见法线密度，最后除以反射映射的 $4|\boldsymbol\omega_o\cdot\mathbf h|$ Jacobian。着色法线负半球上的物理有效灯方向仍可求值，但余弦半球 BSDF 采样不能生成它，所以此时 PDF 为零。粗糙度下限与极小分母共同保护近 delta 情况下的数值稳定性。

### 3.3 GGX 采样密度

实现按 Heitz 的各向同性 GGX 可见法线分布选择 $\mathbf h$，再把 $-\boldsymbol\omega_o$ 关于 $\mathbf h$ 反射。给定观察方向，半程向量 PDF 是

$$
p_h(\mathbf h)=
\frac{D(\mathbf h)G_1(\mathbf n\cdot\boldsymbol\omega_o)
|\boldsymbol\omega_o\cdot\mathbf h|}
{\mathbf n\cdot\boldsymbol\omega_o},
$$

反射方向 PDF 因而为

$$
p_B(\boldsymbol\omega_i)=
\frac{p_h(\mathbf h)}
{4|\boldsymbol\omega_o\cdot\mathbf h|}.
$$

`sample_ggx_vndf` 先把观察方向按 $\alpha$ 拉伸，在投影圆盘上采样可见区域，再把法线反拉伸到世界空间。与普通 NDF 抽样相比，它减少掠射角下生成不可见微表面、随后被拒绝的样本；BSDF 求值与 MIS 使用 `ggx_visible_normal_pdf` 返回的同一测度。metal 与下一节的粗糙 dielectric/water 共用这个 sampler，不增加随机数数量。

## 4. 介电质：从 delta 界面到粗糙微表面

玻璃、水和空气这类非导体常由折射率 $\eta$ 描述。光从介质 $i$ 进入介质 $t$ 时满足 Snell 定律：

`roughness = 0` 时界面是离散反射/折射；非零时，宏观法线之上存在 GGX 微表面法线分布。无 `water_surface` 的光滑兼容路径仍保留原有的空气外部介质与 Schlick 近似，以维持既有确定性路径与随机数序列；含水光滑路径以及全部粗糙介电路径使用非偏振精确 Fresnel。含水介质栈与有界首水面分裂见[第 12 章](12-runtime-analytic-water.md)。

$$
\eta_i\sin\theta_i=\eta_t\sin\theta_t.
$$

正入射时的反射率为

$$
R_0=\left(\frac{\eta_i-\eta_t}{\eta_i+\eta_t}\right)^2.
$$

无水兼容路径用 Schlick 近似角度变化：

$$
R(\theta)=R_0+(1-R_0)(1-\cos\theta)^5.
$$

空气 $(\eta_i=1)$ 到折射率 1.5 的玻璃有 $R_0=0.04$：正面入射约 4% 反射、96% 折射；越接近掠射角，反射越强。

若

$$
\left(\frac{\eta_i}{\eta_t}\right)^2\sin^2\theta_i>1,
$$

折射方向不存在，发生全反射。否则无水光滑兼容路径以概率 $R$ 选择反射，以概率 $1-R$ 选择折射；含水的光滑随机分支用精确 Fresnel 得到相同含义的概率。对这些光滑事件，分支概率抵消对应 Fresnel 系数，所以路径权重不再显式乘 $R$ 或 $1-R$。折射分支额外乘

$$
\left(\frac{\eta_i}{\eta_t}\right)^2,
$$

这是辐亮度传输穿过折射界面时的测度变换。进入较高折射率介质时它小于 1，离开时大于 1；理想的一进一出会互相抵消。

### 4.1 粗糙介电反射与透射

对非零 `roughness`，仍取

$$
\alpha=\max(\mathrm{roughness}^2,0.001),
$$

但它不再表示“几乎 delta”的替代物，而是明确的连续 GGX 分布。反射半程向量仍为

$$
\mathbf h_r=\mathrm{normalize}(\boldsymbol\omega_o+\boldsymbol\omega_i).
$$

透射两方向位于宏观法线两侧。令 $\eta_p=\eta_t/\eta_i$，Walter 等人的方向约定给出

$$
\mathbf h_t=\mathrm{normalize}
(\boldsymbol\omega_o+\eta_p\boldsymbol\omega_i),
$$

并把 $\mathbf h_t$ 翻到宏观法线同侧。记
$n_o=|\mathbf n\cdot\boldsymbol\omega_o|$、
$n_i=|\mathbf n\cdot\boldsymbol\omega_i|$、
$o_h=\boldsymbol\omega_o\cdot\mathbf h$、
$i_h=\boldsymbol\omega_i\cdot\mathbf h$。反射 BRDF 与透射 BTDF 为

$$
f_r=\frac{F D G}{4n_o n_i},
$$

$$
f_t=(1-F)DG\,
\frac{|i_h o_h|}
{n_o n_i(o_h+\eta_p i_h)^2}.
$$

$F$ 是用 $o_h$ 和界面两侧 IOR 求得的精确非偏振 Fresnel；$G=G_1(n_o)G_1(n_i)$。若微表面方向发生全反射，$F=1$，透射瓣和透射选择概率同时归零。`base_color` 最后逐通道乘到 $f_r$ 或 $f_t$。

微表面法线不是按完整 NDF，而是按 Heitz 的各向同性 GGX 可见法线分布（VNDF）抽样。给定观察方向，其半程向量 PDF 为

$$
p_h(\mathbf h)=
\frac{D(\mathbf h)G_1(n_o)|o_h|}{n_o}.
$$

设 $s_R$ 是在抽到微表面法线后选反射分支的采样概率，$s_T=1-s_R$。普通粗糙 dielectric 保持 $s_R=F$。对粗糙 water，当 $F<1$ 时改用

$$
s_R=\max(F,0.5),
$$

全反射 $F=1$ 时仍令 $s_R=1$。这会在垂直入射附近过采样感知上很重要、但 Fresnel 概率很小的水面反射。物理 BSDF 中仍是精确的 $F$ 和 $1-F$；只有抽样 PDF 使用 $s_R,s_T$，因此不改变收敛目标。反射与透射方向 PDF 分别是

$$
p_r(\boldsymbol\omega_i)=
s_R\,\frac{p_h(\mathbf h_r)}{4|o_h|},
$$

$$
p_t(\boldsymbol\omega_i)=
s_T\,p_h(\mathbf h_t)
\left|\frac{\eta_p^2 i_h}
{(o_h+\eta_p i_h)^2}\right|.
$$

最后一项是从半程向量到透射方向的 Jacobian。路径权重仍统一计算为 $f_s n_i/p_B$；因此水面反射样本自动含 $F/s_R$，透射样本含 $(1-F)/s_T$。另外，$p_t$ 的 Jacobian 含 $\eta_p^2$，相除后自然得到辐亮度传输所需的 $(\eta_i/\eta_t)^2$，无需再手工乘第二次。`evaluate_bsdf` 在 NEE/MIS 中返回同一个 $s_R,s_T$ PDF，使灯光采样与 BSDF 采样保持同一测度。

<!-- source-snippet id="rough-water-reflection-oversampling" path="src/device_programs.cu" anchor="rough_reflection_probability" -->
```cpp
static __forceinline__ __device__ float rough_reflection_probability(
    const MaterialData& material, float fresnel) {
  // Moonlit water is reflection-dominated perceptually even when Fresnel is
  // small. Oversample that branch, while evaluate_bsdf keeps the exact F in
  // the BSDF value and uses this same probability only in the direction PDF.
  if (fresnel >= 1.0f) return 1.0f;
  return material.type == spectraldock::kMaterialWater
      ? fmaxf(fresnel, 0.5f)
      : fresnel;
}
```

<!-- source-snippet id="rough-dielectric-btdf-jacobian" path="src/device_programs.cu" anchor="const float jacobian =" -->
```cpp
  const float denominator = wo_h + eta_path * wi_h;
  const float denominator2 = denominator * denominator;
  if (!(denominator2 > 1.0e-20f)) return result;
  // Radiance transport carries the eta_i^2/eta_t^2 factor. It appears in the
  // sample weight through the solid-angle Jacobian below, matching the delta
  // transmission convention used by this renderer.
  result.f_cos = mul(
      base_color,
      (1.0f - fresnel) * d * g * fabsf(wi_h * wo_h) /
          fmaxf(no_v * denominator2, 1.0e-20f));
  const float jacobian =
      fabsf(eta_path * eta_path * wi_h / denominator2);
  result.pdf =
      (1.0f - reflection_probability) * half_pdf * jacobian;
  return result;
```

`eta_path` 就是 $\eta_p$，`denominator` 是 $o_h+\eta_p i_h$；`result.f_cos` 仍使用物理的 $1-F$ 并已融合 $|\mathbf n_s^{\mathrm{eff}}\cdot\boldsymbol\omega_i|$，`result.pdf` 则使用实际分支概率 $s_T=1-s_R$。实现保留绝对值和极小分母保护，避免掠射或接近退化半程向量时产生负 PDF、除零或非有限数。

<!-- source-snippet id="rough-dielectric-vndf-pdf" path="src/device_programs.cu" anchor="ggx_visible_normal_pdf" -->
```cpp
static __forceinline__ __device__ float ggx_visible_normal_pdf(
    float3 n, float3 wo, float3 half_vector, float alpha) {
  const float no_v = fmaxf(dot3(n, wo), 0.0f);
  const float no_h = fmaxf(dot3(n, half_vector), 0.0f);
  const float vo_h = fmaxf(dot3(wo, half_vector), 0.0f);
  if (!(no_v > 0.0f) || !(no_h > 0.0f) || !(vo_h > 0.0f)) {
    return 0.0f;
  }
  return ggx_distribution(no_h, alpha) * ggx_g1(no_v, alpha) * vo_h /
         no_v;
}
```

这段 PDF 与 metal 和粗糙介电采样器使用同一可见法线测度。`sample_ggx_vndf` 先把观察方向按 $\alpha$ 拉伸，在投影圆盘上取样并混合地平线区域，再反拉伸回宏观法线坐标；这样显著减少掠射角生成不可见微表面的拒绝。当网格插值着色法线与真实几何法线不同时，$\mathbf n_s^{\mathrm{eff}}$ 只塑造 GGX 波瓣并提供 `AbsDot` 余弦；反射/透射的物理介质侧别和所有射线起点偏移由定向 $\mathbf n_g$ 决定。对于粗糙介电，两种法线对样本的侧别不一致时拒绝该样本，防止错误修改介质栈。对应实现见[第 12 章第 6 节](12-runtime-analytic-water.md#6-粗糙水面的-nee只连接当前散射事件)。

### 4.2 光滑兼容分支

### 源码对照：无水兼容分支的离散反射与折射

<!-- source-snippet id="dielectric-reflect-refract" path="src/device_programs.cu" anchor="eta_i" -->
```cpp
    const float eta_i = front_face ? 1.0f : fmaxf(material.ior, 1.0e-3f);
    const float eta_t = front_face ? fmaxf(material.ior, 1.0e-3f) : 1.0f;
    const float eta = eta_i / eta_t;
    const float cos_theta =
        fminf(fmaxf(dot3(wo, geometric_n), 0.0f), 1.0f);
    const float sin2_theta = fmaxf(0.0f, 1.0f - cos_theta * cos_theta);
    const float r0_base = (eta_i - eta_t) / (eta_i + eta_t);
    const float r0 = r0_base * r0_base;
    const float m = 1.0f - cos_theta;
    const float reflectance = r0 + (1.0f - r0) * m * m * m * m * m;
    bool transmitted = false;
    if (eta * eta * sin2_theta > 1.0f || rng.next() < reflectance) {
      sample.wi = normalize3(reflect3(neg(wo), geometric_n));
    } else {
      const float3 perpendicular =
          mul(add(neg(wo), mul(geometric_n, cos_theta)), eta);
      const float3 parallel =
          mul(geometric_n,
              -sqrtf(fmaxf(0.0f, 1.0f - length2(perpendicular))));
      sample.wi = normalize3(add(perpendicular, parallel));
      transmitted = true;
    }
    sample.weight = transmitted ? mul(base_color, eta * eta) : base_color;
    sample.pdf = 1.0f;
```

这段代码只在 `params.water_surface_count == 0` 时执行。`sample_bsdf` 同时收到着色参数 `n` 和几何参数 `geometric_n`，这个光滑分支只使用后者求反射/折射方向。`front_face` 决定空气侧和材质侧折射率，`eta` 就是 $\eta_i/\eta_t$。条件 `eta * eta * sin2_theta > 1` 是全反射判定，否则 `rng.next() < reflectance` 以 Schlick 反射率选择离散反射事件；折射方向拆成法向平行与垂直分量，以 `fmaxf` 保护平方根。`sample.weight` 只在 `transmitted` 为真时乘 `eta * eta`，正好对应测度变换 $(\eta_i/\eta_t)^2$；紧随摘录的实现再把样本标记为有效 delta 事件并记录是否透射。因此改变 mesh 顶点法线不会改变理想界面的反射或折射方向。

代码中的 `sample.pdf = 1` 只是 delta 分支的占位记账值，绝不表示“在整个球面均匀采样”。理想反射和折射只出现在一个方向上，应从离散事件理解。

### 当前介电质边界

- `dielectric` 省略 `roughness` 时默认为 0，`metal` 的省略默认仍是 0.5；只有严格正粗糙度进入连续 GGX 介电模型；
- 不模拟光谱色散、偏振、薄膜或多重微表面散射；粗糙介电模型是单次散射 Walter GGX；
- 无 `water_surface` 的兼容路径把外部介质固定为空气，不维护嵌套介质栈，也没有 Beer–Lambert 距离吸收；
- 含水路径维护最多四层严格 LIFO 介质栈，用 RGB Beer 吸收处理水段，并只允许普通 dielectric 绑定闭合 sphere，详见[第 12 章第 4、5 节](12-runtime-analytic-water.md#4-介质栈与严格嵌套)；
- `base_color` 会乘到每次介电散射事件（反射或折射），透射权重还包含 $(\eta_i/\eta_t)^2$；它是界面着色，不等同于含水路径按传播距离累计的吸收。
- 插值着色法线未实现 adjoint correction；极端 $\mathbf n_s^{\mathrm{eff}}$ 与 $\mathbf n_g$ 偏差下不保证严格能量守恒。

## 5. 发光材质

发光表面直接提供渲染方程中的 $L_e$。路径命中它时，将

$$
\boldsymbol\beta\odot\mathbf L_e
$$

加入像素估计，其中 $\boldsymbol\beta$ 是路径到达这里之前积累的吞吐量。场景中的 `emission` 是线性 RGB 相对辐亮度，没有瓦特或坎德拉等绝对单位标定。

纹理可以改变发光面的外观，但当前只有显式声明的 rectangle、disk 和 sphere 面积灯能把可见 emitter 绑定到直接光采样列表；纹理 emitter 与 mesh emitter 只能被路径偶然命中。flame 是独立的程序化体积发光模型，point/directional 则是没有 emitter 几何的 delta 灯。

命中 emitter 后路径立即结束，因此当前发光材质不会在同一次命中上继续反射或折射。它是“只发光”的终端材质，不是发光与普通 BSDF 的叠加层。

## 6. 实现与输入约束

主要实现都位于 [`src/device_programs.cu`](../../src/device_programs.cu)：

- `evaluate_bsdf`：计算 Lambert、GGX metal 和粗糙介电反射/透射的 BSDF 值与连续方向 PDF；
- `sample_bsdf`：生成 Lambert、GGX 或介电质方向及路径权重；
- `ggx_distribution`、`ggx_g1`、`sample_ggx_vndf`、`dielectric_fresnel`：微表面分布、可见法线采样和精确介电 Fresnel。

Python API 与原生 SceneBuilder 只要求 `base_color` 非负，没有强制每个通道不超过 1。物理上要保持被动表面能量守恒，场景作者仍应让普通反射率处于合理范围。大于 1 的 `emission` 则很常见，因为 HDR 光源本来就需要比显示白色更亮。

上述几何/着色法线分工可对照 [PBRT v4 的 `SurfaceInteraction`](https://www.pbr-book.org/4ed/Geometry_and_Transformations/Interactions)；路径吞吐量中的着色法线 `AbsDot` 见 [PBRT v4 的 Simple Path Tracer](https://www.pbr-book.org/4ed/Light_Transport_I_Surface_Reflection/A_Simple_Path_Tracer)。着色法线为什么可以破坏对称性与能量守恒，以及严格 adjoint BSDF 如何构造，见 Eric Veach 博士论文[ *Robust Monte Carlo Methods for Light Transport Simulation* 第 5 章](https://graphics.stanford.edu/papers/veach_thesis/)。SpectralDock 明确只采用前两项中的法线分工与 `AbsDot` 形式，没有实现 Veach correction。

[上一章：光的度量与渲染方程](02-light-and-rendering-equation.md) · [返回目录](README.md) · [下一章：Monte Carlo 路径追踪](04-monte-carlo-path-tracing.md)
