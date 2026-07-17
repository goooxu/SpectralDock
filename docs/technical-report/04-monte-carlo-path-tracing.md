# 04　Monte Carlo 路径追踪

渲染方程要求对连续方向空间积分，并递归查询更多表面。计算机无法逐一枚举连续方向。SpectralDock 采用 Monte Carlo 方法：**随机选择少量路径，并用概率权重让它们的平均值逼近原积分。**

## 1. 从“所有方向求和”到随机抽样

先看一般积分

$$
I=\int_\Omega g(x)\,dx.
$$

若按概率密度函数 $p(x)$ 生成 $N$ 个独立样本 $X_1,\ldots,X_N$，Monte Carlo 估计量是

$$
\widehat I_N=
\frac1N\sum_{j=1}^{N}\frac{g(X_j)}{p(X_j)}.
$$

除以 $p$ 是关键：高概率区域会被更频繁抽到，所以每次代表的区域应更小；低概率样本罕见，但一旦出现就代表更大区域。只要 $g(x)\ne0$ 的地方都有 $p(x)>0$，任意有限 $N$ 都有 $\mathbb E[\widehat I_N]=I$；当 $N\to\infty$ 时，样本平均再依大数定律收敛到 $I$。增加样本主要降低方差，不是让期望逐渐变正确。

### 1.1 PDF 不是单点概率

PDF 是“单位范围内的概率密度”，其数值可以大于 1。真正的概率来自对一个区域积分：

$$
P(X\in A)=\int_A p(x)\,dx.
$$

方向 PDF 的单位是 sr$^{-1}$，面积 PDF 的单位是场景面积单位$^{-1}$。不同测度下的 PDF 不能直接比较；第 5 章会先把灯面面积 PDF 转成方向 PDF，再进行 MIS。

### 1.2 为什么图像有噪声

估计量方差为

$$
\mathrm{Var}[\widehat I_N]
=\frac1N\left[
\int_\Omega\frac{g(x)^2}{p(x)}\,dx-I^2
\right].
$$

因此标准差大约按 $1/\sqrt N$ 下降。把每像素样本数从 16 提高到 64，计算量约增至四倍，随机误差通常只减半。路径追踪中的颗粒并非算法“算错”，而是有限随机样本的统计波动。

**重要性采样**让 $p$ 的形状接近 $|g|$：把样本集中在贡献大的方向，从而用同样样本数降低方差。Lambert 的余弦加权采样、GGX 的微表面法线采样，以及 PBR 对这两者的显式混合都属于重要性采样。

## 2. 路径吞吐量

令路径吞吐量初值为白色

$$
\boldsymbol\beta_0=(1,1,1).
$$

在第 $k$ 个表面，按 BSDF PDF $p_B$ 选择新方向后，更新

$$
\boldsymbol\beta_{k+1}
=\boldsymbol\beta_k\odot
\frac{
f_s(\boldsymbol\omega_i,\boldsymbol\omega_o)
|\mathbf n_s^{\mathrm{eff}}\cdot\boldsymbol\omega_i|
}{p_B(\boldsymbol\omega_i)}.
$$

对连续的 Lambert/GGX 分支——包括 PBR 的混合瓣和非零粗糙度的 dielectric/water——`sample_bsdf` 返回的 `weight` 正是这个分式。$\mathbf n_s^{\mathrm{eff}}$ 提供 `AbsDot` 余弦；独立的 $\mathbf n_g$ 先验证方向位于真实反射或透射侧，并负责后续介质转换与 ray-origin offset。

只有 `roughness = 0` 的 dielectric/water 是 delta 离散事件，不能用普通有限 BSDF 除以连续方向 PDF。Fresnel 反射率决定选反射或折射的概率，但采样概率与对应的 Fresnel 系数在事件权重中抵消：返回权重不再含这个分支概率，反射为 `base_color`，透射再乘 $(\eta_i/\eta_t)^2$。$\boldsymbol\beta$ 记录路径到当前位置的整体权重；它不是剩余光子数量，也不是概率，所以经过 PDF 或俄罗斯轮盘补偿后可以大于 1。

下面是公式在路径循环中的落点：`scatter.weight` 对应分式，`throughput` 对应 $\boldsymbol\beta$。非负截断只消除浮点或实现错误产生的负分量；若三通道均为零，路径不可能再产生贡献。局部方向 PDF、是否为 delta 事件以及当前顶点的有限选灯模式则留给下一顶点的 MIS 使用。

<!-- source-snippet id="path-throughput-update" path="src/device_programs.cu" anchor="throughput = clamp_nonnegative" -->
```cpp
      const BsdfSample scatter =
          sample_bsdf(material, base_color, hit.normal,
                      hit.geometric_normal, wo,
                      hit.front_face, hit.material_index, rng,
                      params.water_surface_count != 0u ? &media : nullptr,
                      water_counters);
      if (scatter.valid == 0) {
        break;
      }
      throughput = clamp_nonnegative(mul(throughput, scatter.weight));
      if (max_component(throughput) <= 0.0f) {
        break;
      }
      previous_pdf = scatter.pdf;
      previous_delta = scatter.delta;
      previous_light_mode = current_light_mode;
```

若路径未命中并到达背景，累积

$$
\widehat{\mathbf L}\mathrel{+}=
\boldsymbol\beta_k\odot\mathbf L_{\text{env}}.
$$

若路径命中发光表面，累积

$$
\widehat{\mathbf L}\mathrel{+}=
\boldsymbol\beta_k\odot\mathbf L_e\,w_{\text{hit}}.
$$

相机直接看见灯、delta 事件后命中灯，或不存在可竞争的显式灯采样时，$w_{\text{hit}}=1$；其他情况由 MIS 决定。

命中普通表面时还会加入一份直接光估计：

$$
\widehat{\mathbf L}\mathrel{+}=
\boldsymbol\beta_k\odot
\widehat{\mathbf L}_{\text{direct}}.
$$

## 3. 一条样本路径如何运行

下面的伪代码展示普通单状态表面路径，并省略三类正交细节：NEE/命中端的 MIS；每段射线上的 flame 体积碰撞、自发光与 water 介质 Beer 衰减；以及第一个光滑 water 界面把反射、透射两条确定性 Fresnel 子路径分别放入当前状态和唯一 pending 状态的有界分裂。除这些显式省略外，它与 [`__raygen__pathtrace`](../../src/device_programs.cu) 的主控制流一致：

~~~text
对每个像素样本：
    ray  = 生成相机射线
    beta = (1, 1, 1)
    L    = (0, 0, 0)

    对每次反弹：
        hit = 追踪 ray 的最近交点

        若未命中：
            L += beta × 背景
            结束这条路径

        若命中发光面：
            L += beta × 发光 × MIS 权重
            结束这条路径

        L += beta × 显式直接光估计

        若这是 max_depth 允许的最后一个表面事件：
            结束这条路径

        scatter = 按 BSDF 选择下一方向
        beta *= scatter.weight

        从第五个表面事件起，在继续路径前执行俄罗斯轮盘
        ray = 从交点沿 scatter.wi 发出的新射线

像素线性 RGB = 所有样本 L 的平均值
~~~

这里的“反弹”是一种路径顶点计数，不意味着代码递归调用。raygen 程序用循环保存 `ray_origin`、`ray_direction`、`throughput`、`radiance` 和上一次 PDF；光滑水面的首次分裂最多再保存一个 pending path state，两条子路径都会标记 split 已使用，因此不会继续指数分叉。

## 4. 每像素样本数与随机数

`spp` 是 samples per pixel。每条样本路径有独立的像素内抖动、镜头采样、灯面采样、BSDF 采样和轮盘决策。最终在线性空间中求平均：

$$
\overline{\mathbf L}_{xy}=
\frac1{\mathrm{spp}}
\sum_{s=1}^{\mathrm{spp}}
\widehat{\mathbf L}_{xy,s}.
$$

不能先把每条样本色调映射到 8 bit 再平均，因为色调映射是非线性的，会改变估计目标。

设备端 `Pcg32` 根据全局 `seed`、像素索引和样本索引建立伪随机流。相同程序、设备和参数能够复现随机序列；伪随机不等于真正无规律，它只是为数值积分提供分布良好的确定性样本。

初始化完成后，每次 `next_uint` 先保存旧状态，再用 PCG 的线性同余转移推进状态；`x` 和 `r` 实现 XSH-RR 输出置换。`next` 取输出的高 24 bit 并乘 $2^{-24}$，得到 `float` 可精确表达的 $[0,1)$ 样本。

<!-- source-snippet id="pcg32-output-sequence" path="src/device_programs.cu" anchor="unsigned int next_uint()" -->
```cpp
  __forceinline__ __device__ unsigned int next_uint() {
    const unsigned long long old = state;
    state = old * 6364136223846793005ull + increment;
    const unsigned int x =
        static_cast<unsigned int>(((old >> 18u) ^ old) >> 27u);
    const unsigned int r = static_cast<unsigned int>(old >> 59u);
    return (x >> r) | (x << ((0u - r) & 31u));
  }

  __forceinline__ __device__ float next() {
    return static_cast<float>(next_uint() >> 8) * 0x1.0p-24f;
  }
```

## 5. 俄罗斯轮盘：随机终止低贡献路径

无限反弹不可能实际计算。除了硬性的 `max_depth`，SpectralDock 从 `bounce >= 4` 的散射之后，也就是第五个或更晚的表面事件且仍允许生成下一事件时，使用俄罗斯轮盘。末端事件不执行没有后继射线的轮盘。

生存概率为

$$
s=\mathrm{clamp}
\left(
\max(\beta_r,\beta_g,\beta_b),
0.05,0.95
\right).
$$

路径以概率 $1-s$ 终止；若生存，则

$$
\boldsymbol\beta\leftarrow\frac{\boldsymbol\beta}{s}.
$$

路径循环直接把公式翻译为 `survival`，并从第五个事件开始调用设备局部策略。`continuation.bsdf_pdf` 原样写回，只有幸存路径才用 `throughput_scale` 缩放吞吐量。

<!-- source-snippet id="path-russian-roulette-call" path="src/device_programs.cu" anchor="if (bounce >= 4u)" -->
```cpp
      if (bounce >= 4u) {
        const float survival =
            fminf(fmaxf(max_component(throughput), 0.05f), 0.95f);
        const ContinuationResolution continuation =
            resolve_continuation(previous_pdf, survival, rng.next());
        previous_pdf = continuation.bsdf_pdf;
        if (!continuation.survived) {
          break;
        }
        throughput = mul(throughput, continuation.throughput_scale);
      }
```

其期望保持不变：

$$
\mathbb E[\boldsymbol\beta']
=s\frac{\boldsymbol\beta}{s}+(1-s)\mathbf0
=\boldsymbol\beta.
$$

所以轮盘**单独看**不会系统性把画面变暗，而是用较高方差换取较少平均工作量。例如 $s=0.2$ 时，平均五条路径只有一条继续，但幸存者权重乘 5，期望仍相同。

SpectralDock 将 RR 与 MIS 分离：轮盘只决定路径是否继续，幸存时仅将 `throughput` 除以 $s$；`previous_pdf` 始终保存未乘生存率的局部立体角 BSDF PDF $p_B$。因此 NEE 与 BSDF-hit 两侧比较同一对 PDF。

这个约定集中在 `device_programs.cu` 匿名命名空间内的 `resolve_continuation`：随机样本小于生存概率才继续，幸存缩放正是 $1/s$，返回的 `bsdf_pdf` 则不乘 $s$。它和调用点由同一份 OptiX IR 一起编译，不再维护或测试一份平行的 CPU 渲染策略副本。

<!-- source-snippet id="resolve-path-continuation" path="src/device_programs.cu" anchor="ContinuationResolution resolve_continuation" -->
```cpp
static __forceinline__ __device__ ContinuationResolution resolve_continuation(
    float bsdf_pdf, float survival_probability, float roulette_sample) {
  const bool survived = survival_probability > 0.0f &&
                        roulette_sample < survival_probability;
  return {survived,
          survived ? 1.0f / survival_probability : 0.0f,
          bsdf_pdf};
}
```

## 6. Firefly 与两级贡献钳位

低概率路径若同时带有很大的 $f_s/p$、俄罗斯轮盘补偿或尖锐间接高光，会在有限样本图像中形成少量极亮像素，即 firefly。仅增加 spp 能按统计规律缓慢降低它们，但布光预览往往更需要一个可控的稳定输出。因此 `Renderer.integrator()` 提供 `clamp_direct` 与 `clamp_indirect`；默认分别是 64 和 16，`Renderer.render()` 也可逐次覆盖，0 表示关闭。

对已经乘过 throughput、可见性、介质透射和 MIS 权重的一份完整 RGB 路径贡献 $\mathbf C$，令

$$
M=\max(C_r,C_g,C_b).
$$

若 $T>0$ 且 $M>T$，渲染器执行

$$
\mathbf C'=\mathbf C\frac{T}{M};
$$

否则保持 $\mathbf C'=\mathbf C$。三个通道使用同一缩放，因而不会像逐通道截断那样直接改变色相。bounce 0 的背景、发光端点、体积端点和 NEE 使用 direct 阈值，bounce 1 以后使用 indirect 阈值。有限灯域中的每份提议、环境样本和每盏 delta 灯都是独立估计，分别钳位后才累加；已经相加的最终像素允许超过阈值。

<!-- source-snippet id="path-firefly-contribution-clamp" path="src/device_programs.cu" anchor="clamp_path_contribution" -->
```cpp
static __forceinline__ __device__ float3 clamp_path_contribution(
    float3 contribution, float threshold,
    unsigned long long* clamped_counter) {
  if (!(threshold > 0.0f)) return contribution;
  const float maximum = max_component(contribution);
  if (!(maximum > threshold) || isnan(maximum)) return contribution;
  if (clamped_counter != nullptr) {
    atomicAdd(clamped_counter, 1ull);
  }
  if (!isfinite(maximum)) {
    // This is the limiting max-RGB normalization for overflowed positive
    // components; finite components vanish relative to an infinite maximum.
    return f3(isinf(contribution.x) && contribution.x > 0.0f
                  ? threshold : 0.0f,
              isinf(contribution.y) && contribution.y > 0.0f
                  ? threshold : 0.0f,
              isinf(contribution.z) && contribution.z > 0.0f
                  ? threshold : 0.0f);
  }
  return mul(contribution, threshold / maximum);
}
```

这个顺序很重要：钳位发生在每像素样本平均、PFM 下载和 OptiX Denoiser 之前，所以 PFM 不会绕过它。stats 分别记录 direct/indirect 的有效阈值和实际触发次数。阈值为 0 时 helper 精确返回输入，不消耗随机数；正无穷通道按最大 RGB 归一化的极限映射到阈值，避免产生无穷乘零。没有 delta 灯且各独立项都不需要钳位时，路径还保留原来的分组加法树，便于旧场景逐字节比较。

钳位把长尾样本压小，必然改变期望，因此是明确的**有偏展示策略**，不能写成重要性采样或 Denoiser 的数学等价物。所有能量、均值、MSE 与收敛实验都必须调用 `render(clamp_direct=0, clamp_indirect=0, ...)`；只有这时下面关于 Monte Carlo 估计量的无偏讨论才不包含该额外偏差。

## 7. “无偏”需要谨慎使用

Monte Carlo 采样和正确补偿的俄罗斯轮盘，可以对各自设定的积分保持期望正确。但 SpectralDock 仍有确定性截断和建模近似：

- `max_depth` 会丢弃最后一个已处理表面事件之后的更长路径，产生截断偏差；
- 默认 direct 64 / indirect 16 的贡献钳位会压低高能长尾并引入偏差；两者设为 0 才能关闭；
- HDR 环境与有限灯的重要性采样降低方差，但有限样本仍可能产生噪声；简化 sky 和太阳瓣仍只能由 BSDF 路径到达；
- BSDF、RGB、表面光输运本身是对现实的模型近似；
- 可选 AI 降噪是后续重建，不是无偏积分步骤。

因此不能笼统宣称最终 PNG 完全无偏或完全物理正确；第 5 章会说明统一的 MIS PDF 约定及只有一种策略存在时的边界。

## 8. 常见混淆

- 增加 `spp` 只减少随机误差，不能修复错误材质、缺失的散射介质或过小 `max_depth`。
- 更亮的孤立噪点可能来自低概率、高权重路径；默认两级钳位用保色相缩放降低这类 firefly，但不能恢复被截断的能量，也不能用于无偏参考。
- `max_depth = 12` 表示最多处理 12 个表面事件；第 12 个事件仍完整估计显式直接光，但不会生成第 13 个事件的 BSDF 射线。它不等于 OptiX 的调用栈深度；后者在本项目中是 1。

下一章会研究有限灯与环境 NEE：为什么还要主动连接光源，以及它们如何与 BSDF 路径共同估计同一个积分。

[上一章：材质与 BSDF](03-materials-and-bsdf.md) · [返回目录](README.md) · [下一章：直接光照、NEE 与 MIS](05-direct-lighting-and-mis.md)
