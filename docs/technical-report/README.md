# SpectralDock 渲染技术报告

这组报告解释 SpectralDock **为什么能够把一个场景变成一张图**。重点不是命令怎么运行，而是渲染器所求解的数学问题、随机算法为什么成立，以及这些公式怎样对应到 GPU 实现。

报告不要求计算机图形学先修。正文会从直觉解释所需的向量、微积分和概率概念，再给出可与源码核对的公式。

![SpectralDock 的 benchmark-harbor 正式渲染结果](../gallery/benchmark-harbor.png)

> 上图不是手工绘制的插画，而是本项目路径追踪器的正式输出。报告将沿着一个像素的计算过程，解释它如何产生。

## 核心问题：一个像素如何得到颜色

~~~mermaid
flowchart LR
    A["在像素内随机取样"] --> B["生成相机射线"]
    B --> C["寻找最近交点"]
    C --> D{"命中了什么？"}
    D -->|背景或发光面| E["累积辐亮度"]
    D -->|普通表面| F["估计直接光并随机散射"]
    F --> C
    E --> G["多条样本路径取平均"]
    G --> H["可选降噪"]
    H --> I["曝光、色调映射、sRGB 编码"]
    I --> J["8 bit PNG 像素"]
~~~

路径追踪从相机端反向寻找可能到达相机的光路。这只是求解方向；物理世界中的光仍然从光源传播到相机。

## 推荐阅读顺序

1. [向量、射线与相机](01-vectors-rays-and-camera.md)：建立后面所有几何公式需要的语言。
2. [光的度量与渲染方程](02-light-and-rendering-equation.md)：明确渲染器最终在求什么积分。
3. [材质与 BSDF](03-materials-and-bsdf.md)：解释漫反射、粗糙金属和玻璃如何改变光的方向。
4. [Monte Carlo 路径追踪](04-monte-carlo-path-tracing.md)：把连续积分变成有限条随机路径。
5. [直接光照、NEE 与 MIS](05-direct-lighting-and-mis.md)：解释小光源为何仍能高效采样，以及两种估计如何避免重复计算。
6. [几何、可见性与 BVH](06-geometry-visibility-and-bvh.md)：说明如何找到最近交点和阴影遮挡。
7. [OptiX/GPU 实现](07-optix-gpu-implementation.md)：把上述数学量映射到 SpectralDock 的程序、加速结构和数据流。
8. [降噪、色调映射与输出](08-denoising-color-and-output.md)：从线性 HDR 辐亮度得到可显示 PNG。
9. [边界、性能与验证](09-limitations-performance-and-validation.md)：区分物理模型边界、近似误差、性能指标和软件测试。

如果只想先建立整体认识，可读第 1、2、4、5、8 章，再返回其余章节。

## 全文方向约定

在一个表面点 $\mathbf x$ 上：

- $\mathbf n$ 是朝向当前射线一侧的单位法线；
- $\boldsymbol\omega_o$ 从表面指向上一顶点或相机；
- $\boldsymbol\omega_i$ 从表面指向光源或下一顶点；
- 两个方向都从交点向外。虽然 $\boldsymbol\omega_i$ 叫“入射方向”，光实际沿 $-\boldsymbol\omega_i$ 到达表面。

这是 SpectralDock 源码采用的约定：`wo = -ray_direction`，新射线沿 `wi` 发出。统一方向后，点积、Fresnel、折射和 PDF 公式才不会互相矛盾。

## 常用符号

| 符号 | 含义 | 单位或范围 |
|---|---|---|
| $\mathbf x,\mathbf y$ | 三维空间中的点 | 场景长度单位 |
| $\mathbf v,\boldsymbol\omega$ | 向量；带帽或 $\boldsymbol\omega$ 通常是单位方向 | 无量纲 |
| $\mathbf n$ | 单位表面法线 | 无量纲 |
| $L_i,L_o,L_e$ | 入射、出射、自发光辐亮度 | 本项目用线性 RGB 近似 |
| $f_s$ | BSDF，描述方向之间的散射比例 | sr$^{-1}$，delta 事件除外 |
| $p(\cdot)$ | 概率密度函数 PDF | 随测度而变 |
| $\boldsymbol\beta$ | 一条随机路径当前的 RGB 吞吐量 | 无量纲权重 |
| $\odot$ | RGB 逐分量相乘 | 例如 $(a_r b_r,a_g b_g,a_b b_b)$ |

报告中的 RGB 指**线性 RGB**，除非明确写出 sRGB。公式中的颜色可以大于 1；它们会在最后统一映射到显示范围。

## 数学、实现与验证的关系

~~~text
渲染方程（目标）
    ↓
Monte Carlo、重要性采样、NEE、MIS（数值方法）
    ↓
射线求交、材质模型、路径状态（算法）
    ↓
OptiX、CUDA、BVH、SBT（GPU 实现）
    ↓
测试与基准（检查实现是否符合上述约定）
~~~

因此，测试和验收不是项目主角；它们是保护渲染器数学含义和工程行为不被意外破坏的证据。

## 报告与源码

正文引用稳定的函数或类型名，不依赖容易漂移的行号。主要入口包括：

- 路径积分器：[`__raygen__pathtrace`](../../src/device_programs.cu)
- BSDF 与灯光采样：[`evaluate_bsdf`、`sample_bsdf`、`sample_direct_light`](../../src/device_programs.cu)
- GPU 管线与加速结构：[`create_pipeline`、`build_mesh`、`build_ias`、`make_sbt`](../../src/optix_renderer.cpp)
- 后处理：[`postprocess_kernel`](../../src/postprocess.cu)
- 场景输入：[场景格式说明](../SCENE_FORMAT.md)

这是一份“与当前实现一致”的技术报告，不把 SpectralDock 描述成通用或完整的物理仿真器。每章都会明确当前实现的近似与边界。
