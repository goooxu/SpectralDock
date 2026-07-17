# 06　HDR 环境与重要性采样

Radiance Pavilion 把场景放在一张 2048×1024 的程序化 HDR 日落海岸环境中，Python 程序不注册任何显式灯或 emitter。低角度金色夕阳、暖色分层云、冷色天顶、暗青海面、太阳反光带与远岛剪影既出现在相机 miss 和镜面反射中，也从无限远方向照亮陶瓷胶囊吉祥物、多材质履带机器人 Sparky 这对主角，以及四件采用漫反射、粗糙金属、光滑金属和介电材质的户外观测装置。Sparky 的十个 `usemtl` 槽由 Python typed handles 显式映射，三块屏幕共享 sRGB atlas；`EmitYellow` 槽有意使用 Lambertian 而不是 emitter。夕阳热点集中、天空补光宽广，使 HDR 环境既是场景的唯一光源，也是观察重要性采样收益的教学输入。要让这种照明既正确又低方差，工程上必须同时解决四件事：解码线性辐亮度、在球面与二维图像间一致映射、按亮度和立体角构造 PDF，以及让 NEE 与 BSDF miss 共享同一个 PDF 做 MIS。

同一套 `direct_light_sampling` 还控制有限灯选择。`importance` 是正式默认策略，`uniform` 保留为数学正确性和方差对照；两者应收敛到相同均值，只允许收敛速度不同。

## 1. RGBE 保存的不是显示颜色

Radiance RGBE 为每个像素保存三个 8 bit 尾数 $R,G,B$ 和一个共享指数 $E$。当 $E=0$ 时像素为黑；否则解码为

$$
\mathbf L=(R,G,B)\,2^{E-136}.
$$

这里的 $\mathbf L$ 是线性 Rec.709 RGB 相对辐亮度，可以远大于 1。减去 136 包含 128 的指数偏置和 8 bit 尾数的 $1/256$ 缩放。它不会在读取时执行 sRGB 解码、曝光或色调映射；曝光只在最终显示管线中执行。

<!-- source-snippet id="hdr-rgbe-linear-decode" path="src/sampling.cpp" anchor="std::ldexp" -->
```cpp
Vec3 decode_rgbe(const std::uint8_t* rgbe) {
  if (rgbe[3] == 0) return Vec3{};
  const float scale = std::ldexp(1.0f, static_cast<int>(rgbe[3]) - 136);
  return {static_cast<float>(rgbe[0]) * scale,
          static_cast<float>(rgbe[1]) * scale,
          static_cast<float>(rgbe[2]) * scale};
}
```

加载器只接受 `FORMAT=32-bit_rle_rgbe` 和 `-Y H +X W`。它支持现代逐通道 RLE 与原始 RGBE scanline，并拒绝错误签名、重复或缺失格式、非法 packet、截断数据和分辨率不匹配。宽、高和像素总数分别限制为 8192、4096 和 $2^{25}$，使文件大小在分配前已有确定上界。首版不读取 OpenEXR，也不把线性 beauty 写成 HDR 文件。

## 2. 从世界方向到纬经纹素

令单位世界方向为 $\boldsymbol\omega=(x,y,z)$。先把它绕 `+Y` 轴逆向旋转环境 yaw，得到贴图局部方向 $\boldsymbol\omega'$；这样正的 `rotation_degrees` 等价于把整个环境按右手方向旋转到世界中。设备端再计算

$$
u=\mathrm{fract}\left(\frac{\mathrm{atan2}(z',x')}{2\pi}+\frac12\right),
\qquad
v=\frac{\arccos(\mathrm{clamp}(y',-1,1))}{\pi}.
$$

因此第 0 行是北极 `+Y`，U 在接缝处环绕，V 在南北极截断。查背景、镜面反射、环境 PDF 和环境采样都调用同一映射，避免“看见的位置”和“被采样的位置”错开。

<!-- source-snippet id="environment-direction-to-uv" path="src/device_programs.cu" anchor="atan2f" -->
```cpp
static __forceinline__ __device__ float2 environment_uv(float3 direction) {
  const float3 local = rotate_environment_to_local(normalize3(direction));
  float u = atan2f(local.z, local.x) / (2.0f * kPi) + 0.5f;
  u -= floorf(u);
  const float v = acosf(fminf(fmaxf(local.y, -1.0f), 1.0f)) / kPi;
  return f2(u, fminf(fmaxf(v, 0.0f), 1.0f));
}
```

反向采样时令 $\theta=\pi v$、$\phi=2\pi(u-1/2)$，贴图局部方向为

$$
\boldsymbol\omega'(u,v)=
(\sin\theta\cos\phi,\ \cos\theta,\ \sin\theta\sin\phi),
$$

然后把 yaw 正向旋转回世界。两个变换互为逆，因此旋转只改变方向，不改变概率密度或辐亮度值。

## 3. 为什么不能只按像素亮度抽样

纬经图每个像素覆盖相同的 $(u,v)$ 面积，却不覆盖相同立体角。靠近极点的行在球面上更窄；若只按亮度抽像素，极区会被错误地过度采样。

宽为 $W$、高为 $H$ 时，第 $j$ 行从 $\theta_j=\pi j/H$ 延伸到 $\theta_{j+1}$。一个 texel 的精确立体角是

$$
\boxed{
\Omega_j=\frac{2\pi}{W}
\left(\cos\theta_j-\cos\theta_{j+1}\right)
}.
$$

把同一行的 $W$ 项相加得到球带立体角，再对全部行求和恰好是 $4\pi$。实现使用边界余弦之差，而不是行中心的近似 $\sin\theta$。

<!-- source-snippet id="environment-texel-solid-angle" path="src/sampling.cpp" anchor="const double solid_angle =" -->
```cpp
  for (std::uint32_t y = 0; y < image.height; ++y) {
    const double theta0 = static_cast<double>(kPi) * y / image.height;
    const double theta1 = static_cast<double>(kPi) * (y + 1u) / image.height;
    const double solid_angle =
        (2.0 * static_cast<double>(kPi) / image.width) *
        (std::cos(theta0) - std::cos(theta1));
    for (std::uint32_t x = 0; x < image.width; ++x) {
      const std::size_t pixel = static_cast<std::size_t>(y) * image.width + x;
      const Vec3 rgb{image.pixels[pixel * 3], image.pixels[pixel * 3 + 1],
                     image.pixels[pixel * 3 + 2]};
      if (!finite(rgb) || rgb.x < 0.0f || rgb.y < 0.0f || rgb.z < 0.0f)
        throw std::invalid_argument(
            "environment image contains a non-finite or negative sample");
      importance[pixel] = luminance(rgb) * solid_angle;
      sphere_mass[pixel] = solid_angle / (4.0 * static_cast<double>(kPi));
      importance_sum += static_cast<long double>(importance[pixel]);
```

亮度使用 Rec.709 系数

$$
Y=0.2126R+0.7152G+0.0722B.
$$

若 texel 索引为 $(i,j)$，亮度重要性质量与均匀球面质量分别为

$$
m_{ij}=Y_{ij}\Omega_j,
\qquad
s_{ij}=\frac{\Omega_j}{4\pi}.
$$

importance 模式使用

$$
P_{ij}=0.99\frac{m_{ij}}{\sum_{k,l}m_{kl}}+0.01s_{ij}.
$$

1% 均匀混合保证每个方向都有严格正概率，避免黑暗 texel 对 BSDF miss 的竞争 PDF 变成零。全黑环境没有可归一化的重要性质量，直接令 $P_{ij}=s_{ij}$；uniform 模式也使用这个均匀球面分布。

## 4. 二维 CDF 与方向 PDF

把 $P_{ij}$ 先对列求和得到行概率 $P_j$，再在选中的行内使用条件概率 $P_{i|j}=P_{ij}/P_j$。主机建立一个长度 $H+1$ 的行 CDF 和 $H$ 个长度 $W+1$ 的条件 CDF。设备用两个独立随机数先二分行、再二分列。

为了在选中 texel 内保持立体角均匀，不能线性插值 $\theta$；应在线性区间内插值 $\cos\theta$，再恢复方向。选中 texel 后的方向密度为

$$
p_E(\boldsymbol\omega)=\frac{P_{ij}}{\Omega_j}
=\frac{P_jP_{i|j}}{\Omega_j}.
$$

CDF 在 double 质量上构造目标位置，最终却上传 float。量化可能改变很小区间的宽度，因此实现强制每个 float 边界严格递增，再把相邻边界之差保存为权威概率。采样、环境方向 PDF 和 MIS 都使用这些实际区间，而不是原始 double 质量。

设备反演环境二维 CDF 时把两次 PCG32 输出组合成 53 bit 的 $[0,1)$ double 随机数。只用普通 24 bit float，甚至只用一次 32 bit 输出，都可能无法落入高分辨率环境极区的微小条件区间；若采样永远到不了这些区间而 PDF 仍报告正值，MIS 就会产生真实偏差。有限灯的 1% 均匀混合与 4096 灯上限保证每个 $q_i$ 都远大于 float 的采样分辨率，因此灯索引继续使用单次 `rng.next()`；uniform 模式由此还保留旧有限灯 fixture 的随机数消费顺序。

<!-- source-snippet id="sampling-realized-float-probabilities" path="src/sampling.cpp" anchor="result.boundaries[i + 1] - result.boundaries[i]" -->
```cpp
  for (std::size_t i = 0; i < count; ++i) {
    result.probabilities[i] =
        result.boundaries[i + 1] - result.boundaries[i];
    if (!(result.probabilities[i] > 0.0f))
      throw std::runtime_error("failed to construct a strictly increasing float CDF");
  }
  return result;
}
```

## 5. 有限灯也要选择分布

若有 $N$ 个可随机采样的有限灯，先在主机构造一个全局基础分布 $q_i^G$。这里的集合只含 rectangle、disk、sphere 与 flame；point/directional 属于独立 delta 域，不进入这个 CDF。uniform 模式令 $q_i^G=1/N$。importance 模式先为每个灯计算非负功率代理 $w_i$：

$$
w_i=\pi A_iY(\mathbf L_{e,i})
$$

用于 rectangle、disk 和 sphere；其中 $A_i$ 分别是平行四边形面积、$\pi r^2$ 和 $4\pi r^2$。flame 是各向同性无散射发光体，使用

$$
w_i=4\pi V_i\,\sigma_{t,i}\,d_i\,
Y\!\left(\frac{\mathbf L_{0,i}+\mathbf L_{1,i}}{2}\right),
\qquad
V_i=\pi r_{max,i}^2h_i.
$$

这些只是与发光规模相关的方差优化代理，不是校准后的物理瓦特值。最终选择概率为

$$
\boxed{
q_i^G=0.99\frac{w_i}{\sum_k w_k}+\frac{0.01}{N}
}.
$$

全零代理退化为均匀选择。场景最多有 4096 个显式灯，其中 point/directional 合计最多 32 盏；最终 $q_i^G$ 只对非 delta 子集构造，并取自 float CDF 的实际区间。主机同时上传这个子集到原场景灯索引的映射，保证 CDF 槽位与设备灯表一致。

<!-- source-snippet id="finite-light-power-mixture" path="src/sampling.cpp" anchor="const double floor =" -->
```cpp
  const std::size_t count = indices.size();
  std::vector<double> masses(count, 1.0 / static_cast<double>(count));
  if (mode == DirectLightSampling::Importance) {
    std::vector<double> proxies(count);
    long double proxy_sum = 0.0L;
    for (std::size_t i = 0; i < count; ++i) {
      proxies[i] = finite_light_proxy(lights[indices[i]]);
      if (!std::isfinite(proxies[i]) || proxies[i] < 0.0)
        throw std::invalid_argument("finite light has an invalid power proxy");
      proxy_sum += static_cast<long double>(proxies[i]);
    }
    const double floor = 0.01 / static_cast<double>(count);
    if (proxy_sum > 0.0L && std::isfinite(proxy_sum)) {
      for (std::size_t i = 0; i < count; ++i) {
        masses[i] = 0.99 * static_cast<double>(
                               static_cast<long double>(proxies[i]) / proxy_sum) +
                    floor;
      }
    }
  }
```

全局 PMF 只是各顶点选灯模式的基础：普通空气顶点使用 $q_G$，任意介质内的普通顶点使用均匀索引分布 $q_U=1/N$，粗糙 water 则确定性地从 $q_G$ 与 $q_U$ 各取一份样本。选中灯之后的面积域或球面可见锥条件采样仍遵循第 5 章的通用方向 PDF。water 的双提议、三技术 balance 和源码集中在[第 11 章第 6 节](11-runtime-analytic-water.md#6-粗糙水面的-nee只连接当前散射事件)；flame 使用实际选灯概率但保留互斥体积估计器，见[第 10 章第 5 节](10-procedural-volumetric-flame.md#5-从表面连接体积光)。

### 5.1 Delta 灯不参加重要性 CDF

point 与 directional 的方向分布是 delta，没有面积或体积功率代理可与上述 $w_i$ 放在同一有限测度中。主机把它们的原场景索引上传到独立数组；设备在每个支持 NEE 的连续 BSDF 顶点遍历全部 delta 灯，不抽灯索引，也不消耗选灯随机数。

point 对第 $i$ 盏灯使用 $I_i/r_i^2$，directional 使用恒定 $E_i$；每份贡献还乘 BSDF、余弦、可见性、介质 Beer 与 flame 透射。它们没有可命中的 emitter 端点，所以 MIS 权重为 1。这种设计用最多 32 次确定性连接换取常用布光的稳定性；`direct_light_sampling` 的 `uniform`/`importance` 切换不会改变 delta 域。

## 6. 环境 NEE、无穷远可见性与 MIS

在一个 Lambert、GGX metal、metallic-roughness PBR 或粗糙 GGX dielectric/water 表面上，环境 NEE 抽取方向 $\boldsymbol\omega_i$，估计

$$
\widehat{\mathbf L}_{E}=
\frac{
\mathbf T(\boldsymbol\omega_i)
\odot\mathbf L_E(\boldsymbol\omega_i)
\odot f_s(\boldsymbol\omega_i,\boldsymbol\omega_o)
|\mathbf n_s^{\mathrm{eff}}\cdot\boldsymbol\omega_i|
}{p_E(\boldsymbol\omega_i)}w_E.
$$

所有连续 BSDF 的 `f_cos` 都融合 $|\mathbf n_s^{\mathrm{eff}}\cdot\boldsymbol\omega_i|$；真实反射/透射侧由 $\mathbf n_g$ 判定。对几何上合法、却落在有效着色法线背面的 Lambert/metal/PBR 方向，NEE 求值仍可非零而 BSDF 竞争 PDF 为 0，MIS 因而把完整权重交给灯策略。$\mathbf T$ 包含二值几何/alpha 可见性、flame 吸收，以及当前粗糙透射事件之后同一介质到无穷远的 Beer 衰减。环境 shadow 使用无限 `tmax`；任何后续透明边界都阻断当前连接，不再沿直线穿界。

<!-- source-snippet id="environment-infinite-nee" path="src/device_programs.cu" anchor="direct_segment_transmittance" -->
```cpp
  const float3 shadow_origin = offset_ray_origin(
      hit.position, hit.geometric_normal, wi);
  const float3 surface_transmittance = direct_segment_transmittance(
      hit, material, shadow_origin, wi, kInfinity, -1,
      transmitted_connection, media,
      traced_rays, water_counters);
  if (!(max_component(surface_transmittance) > 0.0f)) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  if (track_volume(shadow_origin, wi, kInfinity, rng,
                   volume_counters).collided != 0) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  const float mis = direct_light_mis_weight(
      light_pdf, evaluation.pdf, true, next_bsdf_ray_exists);
  const float3 contribution =
      mul(mul(mul(evaluation.f_cos, environment_radiance(wi)),
                  surface_transmittance),
          mis / light_pdf);
  if (count_rough_water && max_component(contribution) > 0.0f) {
    ++water_counters.rough_nee_contributions;
  }
```

同一条“表面到环境”路径也可能由 BSDF 先选方向、随后 miss 生成。因此非 delta 前驱使用 power heuristic：

$$
w_E=\frac{p_E^2}{p_E^2+p_B^2},
\qquad
w_B=\frac{p_B^2}{p_B^2+p_E^2}.
$$

NEE 使用 $w_E$，BSDF miss 使用同一方向上的 $p_E$ 和 $w_B$。相机直接 miss、delta 反射/折射后的 miss，以及末端没有下一条 BSDF 射线时，竞争策略不存在，保留完整权重 1。

<!-- source-snippet id="environment-miss-mis" path="src/device_programs.cu" anchor="environment_direction_pdf" -->
```cpp
      if (hit.hit == 0) {
        const float environment_pdf =
            previous_delta == 0 ? environment_direction_pdf(ray_direction)
                                : 0.0f;
        const float miss_weight =
            previous_delta != 0 || !(environment_pdf > 0.0f)
                ? 1.0f
                : power_heuristic(previous_pdf, environment_pdf);
        accumulate_path_contribution(
            radiance,
            mul(mul(throughput, background(ray_direction)), miss_weight),
            clamp_threshold, clamped_counter);
        break;
      }
```

## 7. 三个 NEE 域不是一个混合大灯表

环境、随机有限灯与 delta 灯是三个独立积分域。普通表面在前两个存在的域各产生一个样本：没有 delta 灯时仍是至多两个 connection；有 point/directional 时再对第三个域逐盏求值。粗糙 water 在有限灯域固定产生功率索引与均匀索引两份样本。三个域之间不再选一次类别，也不把各自 PDF 乘一个类别概率。

理论 connection 上限不等于固定的 OptiX 射线数。没有对应域、材质为 delta、方向落到不受支持的半球、PDF 无效或局部条件提前失败时不会追踪 shadow；成功进入可见性阶段的每份样本各发一次二值查询，后续透明边界直接遮挡。delta 灯的最坏 shadow 数随灯数线性增长。stats 中的 `traced_rays` 记录实际调用次数，而不是理论 connection 数。

`direct_light_sampling` 选择两个全局基础分布：

- HDR 环境使用亮度立体角分布或均匀球面分布；
- 有限灯的 $q_i^G$ 使用功率代理分布或均匀灯索引分布。

point/directional 不受该开关影响，始终逐灯求值。

粗糙水面的 $q_G/q_U$ 确定性双样本和介质内均匀覆盖是上述 $q_i^G$ 之上的固定设备端规则。粗糙水面的 BSDF 方向采样还会把 Fresnel 反射分支过采样到至少 50%，但会用实际 PDF 补偿；metal 与 PBR 的 GGX 瓣使用同一 VNDF 测度而不使用这条分支过采样。stats 的 `render.direct_light_sampling` 保存全局基础模式，`render.clamp_direct`/`render.clamp_indirect` 保存实际贡献阈值；结合固定规则与 seed 才能复现 gallery、基准和回归结果。

## 8. 验证边界

Host 测试覆盖 RGBE 原始/RLE scanline、坏 packet、尺寸上限、CDF 单调归一、最终 float 区间概率、全黑退化和有限灯代理。程序化环境生成器还必须逐字节重建 tracked HDR 资产。

GPU 定向测试检查环境唯一照明、`intensity=0` 精确黑场、旋转响应、固定 seed 确定性和 depth 1 环境 NEE；高 spp 的 uniform/importance 均值必须收敛，低 spp 下热点环境与强弱多灯的 ROI MSE 必须由 importance 明显降低。有限灯测试还用两盏不等功率且绑定可见 emitter 几何的面积灯，在 depth 2 同时触发 NEE 与 BSDF-hit 路径，验证两侧 MIS 都使用同一 $q_i$；sphere 对所有连续表面验证可见锥。delta fixture 检查 point 逆平方、directional 距离不变、遮挡和不扰动有限灯 RNG。水面 fixture 另按等散射阶数验证确定性双选灯、可见立体角和反射分支过采样后的收敛均值不变。所有均值/MSE 对照都用 clamp 0/0。

重要性采样不是“画面增强”开关：它不能改变正确极限，也不能修复错误 HDR、缺失遮挡、错误材质或截断偏差。亮度分布也不是对任意 BSDF 都最优；极光滑 GGX 仍可能主要依赖 BSDF 采样。所有球外连续 BSDF 顶点对 sphere 使用可见立体角，球内/近球才回退整球面积。默认贡献钳位能减少 firefly，但它与本章的无偏重要性采样不同，会改变正确极限；定量比较必须设为 0/0。

[上一章：直接光照、NEE 与 MIS](05-direct-lighting-and-mis.md) · [返回目录](README.md) · [下一章：几何、可见性与 BVH](07-geometry-visibility-and-bvh.md)
