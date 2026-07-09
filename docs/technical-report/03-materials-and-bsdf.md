# 03　材质与 BSDF：表面怎样改变光

渲染方程中的 $f_s$ 决定光到达表面后去向哪里。本章依次解释 SpectralDock 的四类材质：Lambert 漫反射、GGX 金属、光滑介电质和发光表面。

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

*图 3：黄色箭头是入射方向，青色箭头是可能的出射方向，轮廓表示 BSDF 的相对集中程度。介电质的反射和折射是离散 delta 方向。*

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
\frac{\max(0,\mathbf n\cdot\boldsymbol\omega_i)}{\pi}.
$$

一次随机样本的路径权重便化简为

$$
\frac{f_r\cos\theta}{p_B}
=\frac{(\boldsymbol\rho/\pi)\cos\theta}{\cos\theta/\pi}
=\boldsymbol\rho.
$$

这就是 [`sample_bsdf`](../../src/device_programs.cu) 的 Lambert 分支直接令 `sample.weight = base_color` 的原因。代码不是漏掉了 BRDF、余弦或 PDF；它们在代数上已经约掉。

## 3. GGX 粗糙金属

粗糙金属可想成大量方向不同的微小镜面。宏观法线是 $\mathbf n$，真正完成一次镜面反射的微表面法线是半程向量

$$
\mathbf h=
\operatorname{normalize}(\boldsymbol\omega_o+\boldsymbol\omega_i).
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

于是 GGX BRDF 为

$$
f_r=
\frac{\mathbf F D G}
{4(\mathbf n\cdot\boldsymbol\omega_o)
(\mathbf n\cdot\boldsymbol\omega_i)}.
$$

这里分母中的换行是普通乘法：即 $4\,n_o n_i$，不是加法。

当前场景加载逻辑把 `metal` 的 `metallic` 固定为 1，所以实际 $\mathbf F_0=\text{base_color}$。这是一种纯金属镜面微表面模型，不是常见的“金属度工作流”，也不含漫反射与镜面混合。

### 3.3 GGX 采样密度

实现先按普通 GGX NDF 选择 $\mathbf h$，再把 $-\boldsymbol\omega_o$ 关于 $\mathbf h$ 反射。方向 PDF 是

$$
p_B(\boldsymbol\omega_i)=
\frac{D(\mathbf h)(\mathbf n\cdot\mathbf h)}
{4|\boldsymbol\omega_o\cdot\mathbf h|}.
$$

这不是可见法线分布采样（VNDF）。在掠射角，普通 NDF 采样更可能生成被拒绝的方向，结果仍能正确估计当前模型，但方差可能更高。

## 4. 光滑介电质：反射还是折射

玻璃、水和空气这类非导体常由折射率 $\eta$ 描述。光从介质 $i$ 进入介质 $t$ 时满足 Snell 定律：

$$
\eta_i\sin\theta_i=\eta_t\sin\theta_t.
$$

正入射时的反射率为

$$
R_0=\left(\frac{\eta_i-\eta_t}{\eta_i+\eta_t}\right)^2.
$$

角度变化用 Schlick 近似：

$$
R(\theta)=R_0+(1-R_0)(1-\cos\theta)^5.
$$

空气 $(\eta_i=1)$ 到折射率 1.5 的玻璃有 $R_0=0.04$：正面入射约 4% 反射、96% 折射；越接近掠射角，反射越强。

若

$$
\left(\frac{\eta_i}{\eta_t}\right)^2\sin^2\theta_i>1,
$$

折射方向不存在，发生全反射。否则实现以概率 $R$ 选择反射，以概率 $1-R$ 选择折射。分支概率已抵消对应 Fresnel 系数，所以路径权重不再显式乘 $R$ 或 $1-R$。折射分支额外乘

$$
\left(\frac{\eta_i}{\eta_t}\right)^2,
$$

这是辐亮度传输穿过折射界面时的测度变换。进入较高折射率介质时它小于 1，离开时大于 1；理想的一进一出会互相抵消。

代码中的 `sample.pdf = 1` 只是 delta 分支的占位记账值，绝不表示“在整个球面均匀采样”。理想反射和折射只出现在一个方向上，应从离散事件理解。

### 当前介电质边界

- 外部介质固定为空气，没有嵌套介质栈；
- 表面完全光滑，没有粗糙玻璃；
- 没有色散、Beer–Lambert 体吸收或内部参与介质；
- `base_color` 会乘到每次介电散射事件（反射或折射），透射还会另乘 $(\eta_i/\eta_t)^2$；它不是随内部传播距离增长的吸收。

## 5. 发光材质

发光表面直接提供渲染方程中的 $L_e$。路径命中它时，将

$$
\boldsymbol\beta\odot\mathbf L_e
$$

加入像素估计，其中 $\boldsymbol\beta$ 是路径到达这里之前积累的吞吐量。场景中的 `emission` 是线性 RGB 相对辐亮度，没有瓦特或坎德拉等绝对单位标定。

纹理可以改变发光面的外观，但当前只有显式声明的 rectangle、disk 和 sphere 面积灯能进入直接光采样列表；纹理 emitter 与 mesh emitter 只能被路径偶然命中。

命中 emitter 后路径立即结束，因此当前发光材质不会在同一次命中上继续反射或折射。它是“只发光”的终端材质，不是发光与普通 BSDF 的叠加层。

## 6. 实现与输入约束

主要实现都位于 [`src/device_programs.cu`](../../src/device_programs.cu)：

- `evaluate_bsdf`：计算 Lambert/GGX 的 BSDF 值和连续方向 PDF；
- `sample_bsdf`：生成 Lambert、GGX 或介电质方向及路径权重；
- `ggx_distribution`、`ggx_g1`、`fresnel_schlick`：微表面公式。

场景解析只要求 `base_color` 非负，没有强制每个通道不超过 1。物理上要保持被动表面能量守恒，场景作者仍应让普通反射率处于合理范围。大于 1 的 `emission` 则很常见，因为 HDR 光源本来就需要比显示白色更亮。

[上一章：光的度量与渲染方程](02-light-and-rendering-equation.md) · [返回目录](README.md) · [下一章：Monte Carlo 路径追踪](04-monte-carlo-path-tracing.md)
