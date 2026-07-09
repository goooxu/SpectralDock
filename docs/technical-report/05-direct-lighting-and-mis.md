# 05　直接光照、NEE 与 MIS

仅按 BSDF 随机游走在数学上可行，但一盏小灯在表面半球中只占很小方向范围。随机射线可能经过成千上万次尝试也撞不到灯，画面便出现高方差亮点。SpectralDock 在 Lambert 和 metal 表面**主动连接一个灯面样本**，这叫 Next Event Estimation（NEE）。

## 1. 在灯面上取一个随机点

假设场景有 $N_L$ 盏显式面积灯。算法先等概率选一盏，再在其面积 $A$ 上均匀取点 $\mathbf y$。相对于面积的联合 PDF 是

$$
p_A(\mathbf y)=\frac{1}{N_L A}.
$$

矩形灯按两条边的均匀坐标取点；圆盘灯用 $r=\sqrt\xi$ 均匀采面积；球灯均匀采整个球面。

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

代入 $p_A=1/(N_LA)$，得到

$$
\boxed{
p_L(\boldsymbol\omega_i)=
\frac{r^2}
{N_L A\,|\mathbf n_l\cdot(-\boldsymbol\omega_i)|}
}
$$

这正是第 2 章立体角关系的倒数变换。PDF 中必须有 $1/N_L$ 的选灯概率；漏掉它会让灯越多，估计反而错误地越暗。

例如 $N_L=2$、$A=4$、$r=3$、灯面余弦为 0.5 时，$p_A=1/8$，而 $dA/d\omega=18$，所以 $p_\omega=2.25\ \mathrm{sr}^{-1}$。距离越远，同一面积覆盖的方向范围越小，单位立体角的概率密度反而越大。

当前场景接口中的显式灯都是单面：rectangle/disk 只从法线正面发光，sphere 只向外发光。设备结构预留了 `two_sided` 分支，但加载器未暴露它。球灯在整个球面均匀取点，背向着色点的样本会被余弦条件拒绝；这是正确但不够高效的选择。

## 2. 阴影射线只回答可见性

从 $\mathbf x$ 到 $\mathbf y$ 发一条有限长度阴影射线。若中间没有其他几何体，记可见性 $V(\mathbf x,\mathbf y)=1$；被遮挡则为 0。

一份灯光采样的直接光估计为

$$
\widehat{\mathbf L}_{\text{direct}}=
\frac{
V(\mathbf x,\mathbf y)
\,\mathbf L_e(\mathbf y\rightarrow\mathbf x)
\odot f_s(\mathbf x,\boldsymbol\omega_i,\boldsymbol\omega_o)
\,\max(0,\mathbf n\cdot\boldsymbol\omega_i)
}{p_L(\boldsymbol\omega_i)}.
$$

一个公式同时解释了几个常见现象：

- 遮挡让 $V=0$，形成阴影；
- 面积灯上不同点可能部分可见，形成软阴影；
- $r^2$ 出现在 PDF 分母的倒数中，自然产生距离平方衰减；
- 每次只选一盏灯，但 $1/N_L$ 的概率已被权重补偿。

阴影射线不计算第二个表面的完整材质，只需要判断“是否被挡”。当前实现因此把介电质也视作阴影遮挡物；alpha cutoff 可以让被裁掉的纹素不遮挡。

## 3. 为什么需要两种采样策略

NEE 擅长寻找小而亮的灯，BSDF 采样擅长寻找尖锐材质瓣：

- 粗糙漫反射面对小灯：灯光采样通常更好；
- 很光滑的 GGX 表面：BSDF 采样容易找到高光方向；
- 完美介电反射/折射：只有 delta 方向有贡献，普通面积灯方向采样无法匹配它。

同一条“当前表面到灯”的路径，可能由两种策略生成：

1. NEE 先选灯面点并连接过去；
2. BSDF 先选方向，后续射线恰好命中那个灯面。

若简单把两份完整估计相加，同一路径会被重复计算。Multiple Importance Sampling（MIS）用权重把贡献在两种策略间分配。

![NEE、BSDF 采样与 MIS 权重](figures/path-nee-mis.svg)

*图 4：上方是两种方式生成同一类光路；下方示意两种 PDF 在不同方向上各有优势。*

## 4. Power heuristic

设灯光方向 PDF 为 $p_L$，BSDF 方向 PDF 为 $p_B$。当前实现每种策略各用一个样本，采用指数为 2 的 power heuristic：

$$
w_L=\frac{p_L^2}{p_L^2+p_B^2},
\qquad
w_B=\frac{p_B^2}{p_B^2+p_L^2}.
$$

当两侧使用同一对 $p_L,p_B$ 时，$w_L+w_B=1$。更擅长生成该方向的策略得到更大权重，但另一策略并不会被硬切断。实现会先用 $\max(p_L,p_B)$ 归一化两项再平方；这不改变公式，却避免大 PDF 平方溢出、小 PDF 平方同时下溢，或人为截断分母破坏互补性。

- `sample_direct_light` 的 NEE 项乘 $w_L$；
- BSDF 路径稍后命中绑定几何的 emitter 时乘 $w_B$；
- 两个 PDF 都以当前着色点的**方向测度**表示，才能放进同一公式。

例如 $p_L=0.8$、$p_B=0.2$ 时

$$
w_L=\frac{0.64}{0.64+0.04}\approx0.941,
\qquad
w_B\approx0.059.
$$

这并不是说 94.1% 的光来自灯光采样，而是说在该方向上，灯光策略的估计通常更可靠。

## 5. Delta 与不能被另一策略生成的路径

MIS 只应比较两种策略都可能生成的路径：

- 上一事件是光滑介电 delta 时，普通 NEE 不可能生成精确的反射/折射方向，命中 emitter 的权重保持 1；
- 没有可命中几何的解析面积灯只能由 NEE 得到，NEE 权重为 1；
- 发光几何没有绑定到显式灯时，`light_direction_pdf` 为 0，路径命中贡献也保持完整权重；
- 在最后一个 `max_depth` 表面事件，没有下一条 BSDF 射线参与竞争，即使灯绑定了几何，NEE 权重也为 1。

## 6. 统一的 RR/MIS PDF 约定与末端深度

SpectralDock 采用“RR 独立于 MIS”的约定。局部方向采样得到的 $p_B$ 原样保存到 `previous_pdf`，不乘俄罗斯轮盘生存率 $s$。轮盘只对路径吞吐量进行期望补偿：

$$
\boldsymbol\beta\leftarrow\frac{\boldsymbol\beta}{s},
\qquad
\texttt{previous\_pdf}=p_B.
$$

这样，NEE 在当前顶点计算 $w_L$，以及幸存 BSDF 路径稍后命中 emitter 时计算 $w_B$，始终使用相同的原始 $p_L,p_B$，互补关系不随 RR 改变。

末端深度按“策略是否真实存在”处理：最后一个允许的表面事件仍执行完整 NEE，但因为不会追踪下一条 BSDF 射线，直接光权重为 1；累积直接光后立即结束，不再消耗 BSDF 或 RR 随机数。相机直接命中、delta 前驱、未绑定灯和末端 NEE 都由共享策略函数返回完整权重。

## 7. 当前直接光采样的边界

[`sample_direct_light`](../../src/device_programs.cu) 只在 Lambert 和 metal 表面执行。介电质是 delta BSDF，通过继续路径寻找灯光。

显式 NEE 列表仅支持 rectangle、disk、sphere 面积灯。以下光源不被主动采样：

- 天空渐变和太阳瓣；
- mesh emitter；
- 任何绑定纹理的 emitter。

它们仍可由 BSDF 路径命中或 miss 得到，因此不是必然缺失，但小而亮时可能有很高方差。灯的选择目前按数量均匀，而不是按功率加权；这保持估计正确，却不一定达到最低方差。

## 8. 对应实现

设备端采样实现在 [`src/device_programs.cu`](../../src/device_programs.cu)，共享决策在 [`include/spectraldock/integrator_policy.h`](../../include/spectraldock/integrator_policy.h)：

- `sample_light_surface`：矩形、圆盘和球面的面积采样；
- `light_direction_pdf`：面积 PDF 到方向 PDF 的换元；
- `trace_visible`：有限距离阴影射线；
- `sample_direct_light`：NEE、BSDF 评估和 $w_L$；
- `power_heuristic`：数值稳定的平方权重；
- `resolve_continuation`：RR 存活、吞吐量补偿和原始 BSDF PDF；
- `direct_light_mis_weight`、`emitter_hit_mis_weight`：只有竞争策略真实存在时才使用 MIS；
- `__raygen__pathtrace` 的 emitter 分支：使用上一次 `previous_pdf` 计算 $w_B$。

下一章转向另一个基础问题：GPU 怎样快速回答数百万次“最近命中了哪个表面？”

[上一章：Monte Carlo 路径追踪](04-monte-carlo-path-tracing.md) · [返回目录](README.md) · [下一章：几何、可见性与 BVH](06-geometry-visibility-and-bvh.md)
