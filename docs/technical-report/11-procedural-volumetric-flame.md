# 11　程序化体积火焰：吸收、自发光与 Delta Tracking

Ember Forge 增加的不是透明火焰贴图，也不是藏在炉膛中的面积灯，而是三个相互重叠、具有有限支撑的异质参与介质。它们共同构成单座复合炉火，只吸收和自发光而不散射；因此既能从相机直接看见，也能照亮铁匠、铁砧与工坊设施，并会削弱穿过炉火的其他光线。

三段 flame 分别构成宽而明亮的炉芯、向上收尖的主火舌和轻微偏轴的副火舌。不同的支撑范围、渐变、湍流参数与 seed 让同一团炉火呈现黄、橙、暗红的分层和非对称轮廓；这仍不是燃烧模拟：密度来自固定 seed 的程序化噪声，颜色是场景给定的线性 RGB 渐变，没有温度、化学组分、流体速度、烟雾、体积散射、时间或黑体光谱。

深夜封闭锻造工坊采用低机位三分之四构图：砖砌锻炉位于左侧视觉焦点，胶囊 mascot 作为铁匠站在前景铁砧与工件之后，烟罩、工具架、风箱、淬火桶、钢材和梁柱提供遮挡、反射与尺度。环境背景为纯黑，场景不含 emitter、面积灯或任何补光，三段 flame 是唯一辐射源；浅色耐火砖和中等反照率的粗糙金属只通过炉火的直接光与间接反弹保持可读性。

## 1. 无散射体积的传输方程

沿射线距离 $s$，线性 RGB 辐亮度满足

$$
\frac{\mathrm d\mathbf L(s)}{\mathrm ds}
=-\sigma(s)\mathbf L(s)+\mathbf j(s).
$$

$\sigma$ 是标量消光系数，第一项表示吸收；$\mathbf j$ 是单位长度产生的 RGB 发射。当前模型定义

$$
\sigma(s)=\bar\sigma\rho_0(s),
\qquad
\bar\sigma=\texttt{extinction}\,\texttt{density\_scale},
$$

$$
\mathbf j(s)=\sigma(s)\mathbf S(u),
\qquad
\mathbf S(u)=(1-u)\mathbf E_0+u\mathbf E_1.
$$

$\rho_0\in[0,1]$ 是归一化程序密度；$u$ 是火焰根部到末端的轴向坐标；$\mathbf E_0,\mathbf E_1$ 分别对应 `emission_start` 与 `emission_end`。把 $\mathbf j$ 写成 $\sigma\mathbf S$ 后，真实碰撞的源函数就是 $\mathbf S$，既方便抽样，也避免在极稀薄区域除以接近零的密度。

从 $a$ 到 $b$ 的透射率为

$$
T(a,b)=\exp\left(-\int_a^b\sigma(t)\,\mathrm dt\right).
$$

解析解可写成

$$
\mathbf L(b)=T(a,b)\mathbf L(a)
+\int_a^b T(s,b)\mathbf j(s)\,\mathrm ds.
$$

问题在于 $\rho_0$ 是噪声函数，这两个积分没有便宜的闭式解。固定步长 ray marching 会引入步长偏差并可能漏掉细节；本项目改用 null-collision/Delta Tracking 构造随机估计。

## 2. 有界程序密度

flame 支撑是沿 `axis` 的圆柱，半径取两端半径的最大值。名义半径沿轴线线性变化；径向 smoothstep、根部 4% 淡入和末端 15% 淡出消除硬边。三 octave value noise 的频率为 1、2、4，权重为 1、0.5、0.25，再除以 1.75，保证 fBm 仍落在 0–1。

<!-- source-snippet id="volume-three-octave-fbm" path="src/device_programs.cu" anchor="float flame_fbm(" -->
```cpp
static __forceinline__ __device__ float flame_fbm(
    float3 p, unsigned int seed) {
  float value = value_noise(p, seed);
  value += 0.5f * value_noise(mul(p, 2.0f), seed ^ 0xa511e9b3u);
  value += 0.25f * value_noise(mul(p, 4.0f), seed ^ 0x63d83595u);
  return value * (1.0f / 1.75f);
}
```

中心线最多偏移 $0.2\,t\,r(u)$，其中 $t$ 是 `turbulence`。局部半径再减去实际偏移量，所以所有非零密度仍严格位于声明的最大半径圆柱内。最终结果钳制到 0–1，因而 $\bar\sigma$ 是有效的保守 majorant，而不仅是经验上“通常够大”的值。

## 3. Delta Tracking 与 null collision

在 majorant 恒为 $\bar\sigma$ 的一段区间内，候选自由程为

$$
\Delta s=\frac{-\ln(1-\xi)}{\bar\sigma},
\qquad \xi\sim U(0,1).
$$

到达候选点后，以 $\sigma/\bar\sigma$ 接受为真实碰撞；否则它是没有物理作用的 null collision，继续向前抽样。对多个重叠 flame，代码把活动体积的 majorant、$\sigma$ 和 $\mathbf j$ 分别相加。真实碰撞返回混合源函数

$$
\mathbf S_{\mathrm{mix}}
=\frac{\sum_i\sigma_i\mathbf S_i}{\sum_i\sigma_i}.
$$

<!-- source-snippet id="volume-delta-tracking-acceptance" path="src/device_programs.cu" anchor="const float acceptance =" -->
```cpp
        if (sigma_total > majorant) {
          ++counters.majorant_violations;
        }
        const float acceptance =
            fminf(fmaxf(sigma_total / majorant, 0.0f), 1.0f);
        if (rng.next() < acceptance) {
          ++counters.real_collisions;
          result.collided = 1;
          result.distance = candidate_distance;
          result.source = sigma_total > 0.0f
              ? divv(source_numerator, sigma_total)
              : f3(0.0f, 0.0f, 0.0f);
          return result;
        }
```

每个 flame 先用解析包围球求射线区间，最多 8 个 flame 产生 16 个端点；排序后只在活动区间抽样。这样没有体积时路径不额外取随机数，已有场景的确定性像素序列保持不变。体积也不注册为 OptiX primitive：GAS/IAS/SBT 继续只表达表面，体积区间与密度求值是 raygen 中的纯 CUDA 工作。

## 4. 相机、镜面路径与估计器分工

相机射线和 delta 镜面/介质事件后的射线使用首次真实碰撞估计：碰撞时累积 $\boldsymbol\beta\odot\mathbf S_{\mathrm{mix}}$ 并终止；没有碰撞才继续到最近表面或背景。

普通 Lambert/GGX 事件之后，真实体积碰撞只终止路径，不再次累积源函数。这部分发光由前一个表面的体积 NEE 独占。两种情况以 `previous_delta` 分开，因此不会让同一贡献同时进入“沿 BSDF 射线撞到火焰”和“从表面连接火焰”两个估计器，也不需要为这两种体积策略补做 MIS。

<!-- source-snippet id="volume-path-estimator-partition" path="src/device_programs.cu" anchor="const VolumeCollision volume = track_volume(" -->
```cpp
      const VolumeCollision volume = track_volume(
          ray_origin, ray_direction, hit.hit != 0 ? hit.distance : kInfinity,
          rng, volume_counters);
      if (params.water_surface_count != 0u) {
        const float travel_distance = volume.collided != 0
            ? volume.distance
            : (hit.hit != 0 ? hit.distance : kInfinity);
        throughput = mul(
            throughput,
            medium_segment_transmittance(
                media, travel_distance, water_counters));
        if (!(max_component(throughput) > 0.0f)) break;
      }
      if (volume.collided != 0) {
        if (previous_delta != 0) {
          radiance =
              add(radiance, mul(throughput, volume.source));
        }
        break;
      }
```

`max_depth` 仍只计算表面事件；体积候选和 null collision 不占 bounce。这样旧场景的深度语义不变，但一个表面段可能执行多次密度求值。

## 5. 从表面连接体积光

对支持 NEE 的表面，先按第 13 章的顶点模式选择显式灯：普通空气顶点取一份全局功率样本，粗糙水面从全局功率与均匀索引各取一份确定性样本，介质内其他顶点取一份均匀样本。若其中一份选中 flame，就在最大半径支撑圆柱中均匀取点，圆柱体积为

$$
V=\pi R_{\max}^2h,
\qquad q_V=\frac{1}{V}.
$$

令 $r$ 为表面到采样点的距离，$\widehat T$ 是沿连接段进行一次 Delta Tracking 得到的 0/1 透射率估计，贡献为

$$
\widehat{\mathbf L}_{\mathrm{direct}}
=\frac{f_s\,|\mathbf n\cdot\boldsymbol\omega_i|\,
\widehat T\,\mathbf j(\mathbf x)}
{p_{\mathrm{select}}q_Vr^2}.
$$

体积点没有表面法线，因此没有面积光公式中的光源侧余弦。圆柱中落在零密度区的样本直接贡献零；实现没有用隐藏暖色面积灯替代火焰照明。

<!-- source-snippet id="volume-nee-estimator" path="src/device_programs.cu" anchor="const float support_volume =" -->
```cpp
    const float3 surface_transmittance = direct_segment_transmittance(
        hit, material, shadow_origin, shadow_direction, shadow_distance,
        static_cast<int>(light_index), transmitted_connection, media,
        traced_rays, water_counters);
    if (!(max_component(surface_transmittance) > 0.0f)) {
      return f3(0.0f, 0.0f, 0.0f);
    }
    if (track_volume(shadow_origin, shadow_direction, shadow_distance, rng,
                     volume_counters).collided != 0) {
      return f3(0.0f, 0.0f, 0.0f);
    }
    const float maximum_radius =
        fmaxf(light.radius_start, light.radius_end);
    const float support_volume =
        kPi * maximum_radius * maximum_radius * light.height;
    const float3 emission_coefficient =
        mul(flame_source(light, axial), sigma);
    const float3 contribution =
        mul(mul(mul(bsdf, emission_coefficient), surface_transmittance),
            no_l * support_volume /
                (selection_pdf * distance2));
```

连接段还先发出普通 OptiX shadow ray 检查表面遮挡。rectangle/disk/sphere 面积光的连接也增加同样的体积透射测试，所以火焰能衰减从其他灯到表面的光。面积光与 BSDF 的 MIS 结构保持不变，但灯方向 PDF 现在包含实际 $q_i$。

## 6. 安全边界、统计与性能

场景加载器限制 flame 数量为 8，并要求保守光学厚度总和不超过 64。设备端每条跟踪段最多接受 4096 个候选；超过上限或发现 $\sigma>\bar\sigma$ 都会记入计数器。主机汇总后只要任一安全计数非零就拒绝输出，避免把已知有偏或未完成的结果悄悄保存为正式图。

<!-- source-snippet id="volume-host-safety-gate" path="src/optix_renderer.cpp" anchor="volume tracking safety check failed" -->
```cpp
  if (volume_totals.majorant_violations != 0ull ||
      volume_totals.tracking_overflows != 0ull) {
    throw std::runtime_error(
        "volume tracking safety check failed: majorant violations=" +
        std::to_string(volume_totals.majorant_violations) +
        ", tracking overflows=" +
        std::to_string(volume_totals.tracking_overflows));
  }
```

stats 单独记录 density evaluations、real collisions、light samples、majorant violations 和 tracking overflows。`traced_rays` 仍只计 `optixTrace`，所以新增大量纯 CUDA 密度求值可能增加 path trace 时间，却不增加射线数；此时 rays/s 不能单独代表火焰算法效率。

Ember Forge 的正式配置使用 2048 spp、depth 12 且关闭 Denoiser。原因不是 Denoiser 不能处理亮色，而是当前 albedo/normal guide 只描述首次表面，没有体积特征或透射 guide；让正式图保留原始 Monte Carlo 结果，能更直接暴露硬支撑边界、分层和 firefly。

## 7. 当前边界

- 这是线性 RGB 的吸收—自发光模型，不是光谱或黑体辐射。
- 没有体积散射、相函数、烟雾阴影、CFD、时间演化或 motion blur。
- 均匀包围圆柱 NEE 在高度稀疏或极细长火焰上方差可能偏高。
- Delta Tracking 无固定步长偏差，但仍有 Monte Carlo 方差；固定 seed 只在相同 GPU、构建和软件栈范围内提供确定性证据。
- flame 不进入 OptiX BVH；若未来需要大量稀疏体积或网格化模拟数据，应重新评估 NanoVDB、分层 majorant 和更强的重要性采样。

数学上的 null-scattering 形式可进一步参考 Miller、Georgiev 与 Jarosz 的 *A null-scattering path integral formulation of light transport*；工程边界和输入约束见[场景格式](../SCENE_FORMAT.md)。

[上一章：PhysX 刚体模拟与场景烘焙](10-physx-rigid-body-scene-baking.md) · [返回目录](README.md) · [下一章：运行时解析水面](12-runtime-analytic-water.md)
