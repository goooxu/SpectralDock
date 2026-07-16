# 10　PhysX 刚体模拟与 Python 场景即时构建

Kinetic Foundry 与“熔岩圣殿的机械先知”在普通 OptiX 渲染链之前增加了一段
**物理场景即时构建**：可执行 Python 程序定义 `Renderer` 资源和
`PhysicsWorld`，隔离的 PhysX 5.8.0 GPU worker 求出选定时刻，
`PhysicsResult.apply_to` 再把 typed render attachments 直接加入
SceneBuilder。整个过程不产生、读取或回放场景 JSON。

PhysX 是这两个物理场景的核心组件，但它不链接进 Renderer native extension，
也不在 `optixLaunch` 内运行。画面仍是单帧离线路径追踪；“即时”表示每次执行
物理场景程序都 fresh 求解布局，而不是逐帧交互仿真。

![熔岩圣殿的机械先知在第 24 步的 4K 正式渲染结果](../gallery/lava-temple-oracle.png)

*图 8：预碎裂机械部件、顶石与火星的姿态来自 PhysX；圣殿、解析水面、
体积代理、相机、灯光、材质和最终像素来自 SpectralDock。*

## 1. 从普通 Python 程序到可追踪几何

实际数据流包含一个 Python/OptiX 父进程和一个短生命周期 PhysX 子进程：

~~~mermaid
flowchart LR
    A["scenes/*.py 创建 Renderer handles"] --> B["创建 PhysicsWorld、actors、shapes、attachments"]
    B --> C["TemporaryDirectory 内 private request.sdp"]
    C --> D["CUDA 12.8 / PhysX 5.8 GPU worker"]
    D --> E["private result.sdp：body states 与 attachment 数值"]
    E --> F["PhysicsResult 验证版本、顺序与有限值"]
    F --> G["apply_to：typed handles + 世界空间参数"]
    G --> H["SceneBuilder"]
    H --> I["CUDA 13.3 / OptiX 9.1 路径追踪"]
    F --> J["可选 .physics.json 审计记录"]
~~~

`.sdp` 是内部二进制 IPC，不是 scene format 或公共 API。它只存在于
`tempfile.TemporaryDirectory`，调用结束即删除。这样 PhysX worker 可以链接
CUDA 12.8，而同一条用户命令的父进程加载 CUDA 13.3 Renderer extension；
两个进程不共享 CUDA context、device pointer、PhysX actor 或 SDK handle。
这条 `PhysicsWorld` → private IPC → typed attachments → `SceneBuilder` 链是
本章工程边界的核心。

持久 `.physics.json` 只记录设备、版本、seed、固定时间步、actor 初末状态、
速度、sleeping 和 attachment 数量。它不是 Renderer 场景，也没有把它作为
输入来跳过下次模拟的入口。

<!-- source-snippet id="physx-python-handoff" path="scenes/kinetic-foundry.py" anchor="_populate_physics(physics, materials, mascot)" -->
```python
    _populate_physics(physics, materials, mascot)
    result = physics.simulate(metadata_output=metadata_output, verify=verify,
                            validator=_validate)
    result.apply_to(renderer)
```

这三行展示了边界的核心：场景自己填充 `PhysicsWorld`，`simulate` 返回
`PhysicsResult`，`apply_to` 使用创建 Renderer 材质与网格时得到的 typed
handles。此后相机、灯光与 `renderer.render` 仍是普通 Python 调用。

## 2. 刚体状态与 Newton–Euler 原理

一个动态刚体在时刻 $t$ 的概念状态可写为

$$
\mathcal S(t)=
(\mathbf p(t),\mathbf q(t),\mathbf v(t),\boldsymbol\omega(t)),
$$

其中 $\mathbf p$ 是质心位置，$\mathbf q$ 是单位四元数姿态，$\mathbf v$
和 $\boldsymbol\omega$ 分别是线速度与角速度。局部点 $\mathbf x_l$ 到世界
空间的映射为

$$
\mathbf x_w=\mathbf p+R(\mathbf q)\mathbf x_l.
$$

忽略接触约束时，平移和转动由 Newton–Euler 方程描述：

$$
m\frac{\mathrm d\mathbf v}{\mathrm dt}=\mathbf F,
\qquad
\frac{\mathrm d\mathbf p}{\mathrm dt}=\mathbf v,
$$

$$
\mathbf I\frac{\mathrm d\boldsymbol\omega}{\mathrm dt}
+\boldsymbol\omega\times(\mathbf I\boldsymbol\omega)=\boldsymbol\tau.
$$

$m$ 是质量，$\mathbf F$ 是合力，$\mathbf I$ 是惯量张量，
$\boldsymbol\tau$ 是合力矩。含陀螺项的连续方程是理解刚体的教学基准；
worker 没有设置 `PxRigidBodyFlag::eENABLE_GYROSCOPIC_FORCES`，因此不能把上式
每一项都宣称为本场景显式启用的 PhysX 功能。实际积分和约束求解由 PhysX
完成，项目没有另写 CPU 或 CUDA 刚体积分器。

### 2.1 密度、质量与惯量

均匀密度 $\rho$ 的刚体满足

$$
m=\rho V.
$$

半径为 $r$ 的球，以及半径为 $r$、圆柱半长为 $h$ 的 capsule，其体积为

$$
V_{\mathrm{sphere}}=\frac{4}{3}\pi r^3,
\qquad
V_{\mathrm{capsule}}=2\pi r^2h+\frac{4}{3}\pi r^3.
$$

若 $\mathbf E$ 是三阶单位矩阵，惯量张量的连续定义是

$$
\mathbf I=\int_V\rho
\left(\lVert\mathbf x\rVert^2\mathbf E-\mathbf x\mathbf x^{T}\right)\mathrm dV.
$$

Python 场景只指定 shape 与 density。worker 创建一个或多个 `PxShape` 后调用
`PxRigidBodyExt::updateMassAndInertia`，因此 compound actor 的质量和惯量来自
整组 shape，而不是由 Python 手填。密度是场景单位，报告不把它宣称为真实
千克每立方米。

<!-- source-snippet id="physx-body-properties" path="tools/physx_worker.cpp" anchor="PxRigidBodyExt::updateMassAndInertia" -->
```cpp
      for (const ShapeRequest& shape : input.shapes) add_shape(runtime, *actor, shape);
      if (!PxRigidBodyExt::updateMassAndInertia(*actor, input.density))
        fail("mass/inertia computation failed");
      actor->setSolverIterationCounts(
          static_cast<PxU32>(input.position_iterations),
          static_cast<PxU32>(input.velocity_iterations));
      actor->setLinearDamping(input.linear_damping);
      actor->setAngularDamping(input.angular_damping);
      actor->setSleepThreshold(input.sleep_threshold);
      actor->setLinearVelocity(input.linear_velocity);
      actor->setAngularVelocity(input.angular_velocity);
```

位置/速度求解迭代次数、阻尼和 sleep threshold 都是每个 body 的 request
字段。它们不等于外层 24 或 300 个固定时间步。

## 3. 碰撞、接触与约束

宽相用包围体排除不可能接触的 shape。两个 AABB 成为候选对，至少要在三个
轴上都重叠：

$$
\min A_a\le\max B_a
\quad\text{且}\quad
\min B_a\le\max A_a,
\qquad a\in\{x,y,z\}.
$$

窄相再为候选 shape 产生接触点和法线。设 $g$ 是沿接触法线的间隙，
$\lambda_n$ 是法向冲量，理想刚性非穿透条件为

$$
g\ge0,
\qquad
\lambda_n\ge0,
\qquad
g\lambda_n=0.
$$

库仑摩擦的理想约束为

$$
\lVert\boldsymbol\lambda_t\rVert\le\mu\lambda_n.
$$

若把所有刚体速度拼成 $\mathbf u$，一次约束修正可抽象为

$$
\mathbf u^+=\mathbf u^*+
\mathbf M^{-1}\mathbf J^{T}\boldsymbol\lambda.
$$

$\mathbf J$ 是约束 Jacobian，$\mathbf M$ 是块状质量与惯量矩阵。这些公式
解释了接触响应的数学含义，但不是 PhysX GPU kernel 的逐行复现；离散、
摩擦锥近似、contact caching 和迭代细节由 PhysX 实现。

### 3.1 项目强制的 GPU 求解链

worker 创建 CUDA context manager，把 scene 的 broad phase 设为 GPU、solver
设为 TGS，并启用 GPU dynamics、PCM 与 stabilization。它随后读取实际 scene
flags 反向验证；任一步失败都终止，没有 CPU fallback。
这里的 GPU-only 指 broad phase 与 rigid-body dynamics 不得静默退回 CPU；
Python 场景描述和 PhysX CPU dispatcher 仍然在宿主侧运行。

<!-- source-snippet id="physx-gpu-scene-contract" path="tools/physx_worker.cpp" anchor="description.broadPhaseType = PxBroadPhaseType::eGPU" -->
```cpp
    PxSceneDesc description(scale);
    description.gravity = request.gravity;
    description.cpuDispatcher = dispatcher_;
    description.filterShader = PxDefaultSimulationFilterShader;
    description.cudaContextManager = cuda_manager_;
    description.broadPhaseType = PxBroadPhaseType::eGPU;
    description.solverType = PxSolverType::eTGS;
    description.flags |= PxSceneFlag::eENABLE_GPU_DYNAMICS;
    description.flags |= PxSceneFlag::eENABLE_PCM;
    description.flags |= PxSceneFlag::eENABLE_STABILIZATION;
    description.flags &= ~PxSceneFlag::eENABLE_ENHANCED_DETERMINISM;
    if (!description.isValid()) fail("GPU PxSceneDesc is invalid");
    scene_ = physics_->createScene(description);
    if (!scene_) fail("GPU PhysX scene creation failed; CPU fallback is forbidden");

    const PxSceneFlags flags = scene_->getFlags();
    if (!flags.isSet(PxSceneFlag::eENABLE_GPU_DYNAMICS) ||
        !flags.isSet(PxSceneFlag::eENABLE_PCM) ||
        !flags.isSet(PxSceneFlag::eENABLE_STABILIZATION) ||
        flags.isSet(PxSceneFlag::eENABLE_ENHANCED_DETERMINISM) ||
        scene_->getBroadPhaseType() != PxBroadPhaseType::eGPU ||
        !cuda_manager_->contextIsValid())
      fail("created scene does not satisfy the PhysX GPU-only contract");
```

PCM 跨时间步维护 contact manifold；TGS 在一个外层时间步内形成更细的求解
更新。代码依赖这些公开语义，不假定未公开的 kernel 排布或浮点执行顺序。
物理接触材质的静/动摩擦和恢复系数，与 Renderer 的 Lambert、metal、water、
emitter 等 BSDF 材质完全独立。

## 4. Kinetic 为什么使用 capsule 碰撞代理

吉祥物 OBJ 有 5,816 个三角形。逐三角形动态碰撞会增加接触生成成本，也会
让手臂、天线和靴子等装饰产生不稳定小接触。因此物理世界用一个 capsule
近似每个吉祥物，视觉世界仍使用完整 OBJ。

设 capsule 中心为 $\mathbf p$，单位轴为 $\mathbf u$，圆柱半长为 $h$，
半径为 $r$。它是轴线段

$$
\{\mathbf p+\alpha\mathbf u\mid-h\le\alpha\le h\}
$$

沿所有方向膨胀半径 $r$。本项目取 $r=0.42$、$h=0.28$，总高度为

$$
2(h+r)=2(0.28+0.42)=1.4.
$$

OBJ 原始高度为 2，渲染缩放 $s=0.7$ 后也为 1.4。碰撞代理不是逐三角形
贴合，但主轮廓高度一致。

<!-- source-snippet id="physx-capsule-proxy" path="scenes/kinetic-foundry.py" anchor="body.capsule(0.42, 0.28, contact" -->
```python
                body = world.rigid_body(
                    f"mascot_body_{index:02d}", category="mascot", position=position,
                    rotation=_quat_degrees(random.symmetric(15.0), (0.0, 1.0, 0.0)),
                    density=2.4, linear_damping=0.08, angular_damping=0.12,
                )
                body.capsule(0.42, 0.28, contact, local_rotation=capsule_rotation)
                material_name = mascot_materials[index % len(mascot_materials)]
                body.attach_mesh(f"mascot_{index:02d}", mascot,
                                 local_translate=(0.0, -0.7, 0.0),
                                 scale=(0.7, 0.7, 0.7),
                                 material=render_materials[material_name])
```

PhysX capsule 默认沿局部 $+X$，`capsule_rotation` 把 collision shape 旋到
actor 的 $+Y$；mesh attachment 的 `local_translate` 则补偿 OBJ 原点位于
脚底这一事实。钢珠无需代理，物理和 Renderer 都直接使用 sphere。

## 5. 固定时间步与两个取景时刻

两个场景都采用

$$
\Delta t=\frac{1}{120}\ \mathrm s.
$$

Kinetic 的步数为 $N_K=300$，封面的步数为 $N_L=24$，所以

$$
T_K=N_K\Delta t=2.5\ \mathrm s,
\qquad
T_L=N_L\Delta t=0.2\ \mathrm s.
$$

<!-- source-snippet id="physx-fixed-step-simulation" path="tools/physx_worker.cpp" anchor="runtime.scene().simulate(request.fixed_dt)" -->
```cpp
void simulate(Runtime& runtime, const Request& request) {
  for (std::uint32_t step = 0; step < request.steps; ++step) {
    runtime.scene().simulate(request.fixed_dt);
    if (!runtime.scene().fetchResults(true))
      fail("PxScene::fetchResults failed at step " + std::to_string(step));
    if (runtime.errors().fatal.load(std::memory_order_relaxed))
      fail("PhysX reported a fatal error during GPU simulation");
  }
}
```

`fetchResults(true)` 等待当前步完成后才提交下一步。固定步长避免墙钟抖动改变
步数，但不自动提供跨 GPU 确定性。“撞击峰值”和“爆发瞬间”是经过候选图
选择的构图时刻，不宣称是总动能、速度或接触冲量的数学最大值。

## 6. 四元数、局部附件与世界空间几何

对 actor pose $(\mathbf p,\mathbf q)$ 与 attachment local pose
$(\mathbf t_a,\mathbf q_a)$，组合变换为

$$
\mathbf p_a=\mathbf p+R(\mathbf q)\mathbf t_a,
\qquad
R_a=R(\mathbf q)R(\mathbf q_a).
$$

局部点 $\mathbf x_l$ 因而变成

$$
\mathbf x_w=\mathbf p_a+R_a\mathbf x_l.
$$

sphere 只需变换中心；rectangle 变换三个局部顶点；cylinder 变换 base 并
旋转 axis；disk 变换中心和 normal。mesh 还要把最终四元数转换成 Renderer
接受的 XYZ 欧拉角。

若

$$
R=R_z(z)R_y(y)R_x(x),
$$

在非万向锁区域可用

$$
y=\sin^{-1}(-R_{20}),
\qquad
x=\mathrm{atan2}(R_{21},R_{22}),
\qquad
z=\mathrm{atan2}(R_{10},R_{00}).
$$

worker 在 $|\cos y|$ 很小时固定 $z=0$，从 $R_{12},R_{11}$ 恢复 $x$。
欧拉角不唯一，但其旋转矩阵仍表示同一姿态。

<!-- source-snippet id="physx-attachment-baking" path="tools/physx_worker.cpp" anchor="const PxTransform world = body_pose.transform(local);" -->
```cpp
  } else if (attachment.kind == 5) {
    const PxTransform local(vec3(value, 0), quat(value, 3));
    const PxTransform world = body_pose.transform(local);
    writer.vec3(world.p);
    const auto rotation = euler_degrees(world.q);
    writer.f32(rotation[0]);
    writer.f32(rotation[1]);
    writer.f32(rotation[2]);
    writer.f32(value[7]);
    writer.f32(value[8]);
    writer.f32(value[9]);
  }
```

IPC 不携带 Renderer handles。Python 仍保留原来的 `MaterialHandle` 和
`MeshHandle`，result 只按稳定 attachment index 返回上述数值；`apply_to`
重新结合二者并调用 `renderer.object`。这同时防止把 CUDA/PhysX 指针误当成
跨进程数据。

### 6.1 吉祥物模型原点补偿

吉祥物 OBJ 的包围盒中心位于局部 $(0,1,0)$。缩放后中心偏移为 $(0,s,0)$，
$s=0.7$；物理 actor 原点位于 capsule 中心，所以 mesh 世界平移为

$$
\mathbf t=\mathbf p-R(\mathbf q)(0,s,0)^T.
$$

于是 mesh 中心重新落在

$$
\mathbf t+R(\mathbf q)(0,s,0)^T=\mathbf p.
$$

这正是上一节代码中的 actor-local mesh translation。球体没有模型原点补偿。

## 7. 物理世界与视觉世界不是同一份几何

| 数据 | PhysX 阶段 | Renderer / OptiX 阶段 |
|---|---|---|
| Kinetic 吉祥物 | 单个 capsule 代理 | 完整 5,816 三角形 OBJ |
| Kinetic 钢珠 | sphere | sphere |
| 封面机械部件 | box、capsule、sphere、compound shapes | rectangle、cylinder、disk、sphere |
| 封面水池 | 不存在 | 解析 `water_surface` 与 Beer 吸收 |
| 火、烟、神光 | 不存在 | 六个吸收—自发光 flame volumes |
| 材质 | 摩擦、恢复系数、密度 | BSDF、颜色、粗糙度、IOR、发光 |
| 动态状态 | $\mathbf p,\mathbf q,\mathbf v,\boldsymbol\omega$ | 固定时刻的世界空间几何 |

Kinetic 的不可见挡墙和滑槽护栏参与碰撞却不必全部进入画面。封面的圣殿、
祭坛、符文、水面与灯直接由 Renderer 构建。改变 BSDF 不会改变碰撞；改变
摩擦也不会直接改变颜色。这个边界让每个子系统只宣称自己实际计算的量。

## 8. 封面：预碎裂爆发的数学与工程映射

机械先知从一开始就是 70 个独立 actor：24 块外壳板、2 块面罩、2 只眼、
4 个肢体、3 个天线部件、6 个复合齿轮和 29 个其他机械件；另有 12 块顶石
和 48 颗火星，总计 130 个 dynamic actors。它是
**prefractured rigid-body explosion**，不是运行时 topology fracture。

### 8.1 线性冲量、偏心冲量与角运动

若短时间内施加冲量 $\mathbf J$，则

$$
m(\mathbf v^+-\mathbf v^-)=\mathbf J.
$$

作用点相对质心偏移 $\mathbf r$ 时还产生角冲量

$$
\mathbf L_J=\mathbf r\times\mathbf J,
\qquad
\mathbf I_w(\boldsymbol\omega^+-\boldsymbol\omega^-)=\mathbf L_J.
$$

场景从爆点 $\mathbf c$ 构造带向上 bias 的方向

$$
\mathbf d=
\frac{\mathbf p-\mathbf c+\beta\mathbf e_y+\boldsymbol\epsilon}
{\lVert\mathbf p-\mathbf c+\beta\mathbf e_y+\boldsymbol\epsilon\rVert},
$$

并给出期望速度变化 $\Delta\mathbf v=s\mathbf d$ 与偏心作用点。worker 最终
计算 $\mathbf J=m\Delta\mathbf v$，因此不同质量部件取得近似同类的速度尺度；
`addForceAtPos` 同时产生 $\mathbf r\times\mathbf J$。

<!-- source-snippet id="physx-cover-off-center-impulse" path="scenes/lava-temple-oracle.py" anchor="body.mass_scaled_impulse_at_position" -->
```python
def _apply_explosion(body: Any, initial: tuple[float, ...], speed: float,
                     upward_bias: float, random: _SplitMix64) -> None:
    displacement = _sub(initial, EXPLOSION_CENTER)
    radial = (displacement[0] + random.symmetric(0.16),
              displacement[1] * 0.38 + upward_bias,
              displacement[2] + random.symmetric(0.16))
    radial = _unit(radial, (0.0, 1.0, 0.0))
    tangent = _unit((-radial[2], 0.35, radial[0]), (1.0, 0.0, 0.0))
    application = _add(_add(initial, _mul(tangent, random.symmetric(0.22))),
                       (0.0, random.symmetric(0.12), 0.0))
    body.mass_scaled_impulse_at_position(
        _mul(radial, speed + random.symmetric(0.8)), application)
```

顶石和火星不走爆发 helper，而是设置各自的初始线速度与角速度，形成坠落和
上升轨迹。

### 8.2 复合齿轮与一对多视觉附件

若第 $k$ 个 shape 的 actor-local pose 为 $(\mathbf t_k,R_k)$，局部点为
$\mathbf x_k$，则

$$
\mathbf x_w=\mathbf p+R(\mathbf q)
(\mathbf t_k+R_k\mathbf x_k).
$$

六个齿轮各是一个 actor，但 collision 由中心 sphere 与六个 tooth boxes
组成。同一个 actor 又附着 cylinder、两个 disks、六根辐条、六个齿面；第
5 个齿轮还携带可见 emissive core。

<!-- source-snippet id="physx-compound-gear" path="scenes/lava-temple-oracle.py" anchor="body.sphere(0.35, metal)" -->
```python
        body.sphere(0.35, metal)
        for tooth in range(6):
            angle = 2.0 * math.pi * tooth / 6.0
            body.box((0.18, 0.11, 0.12), metal,
                     local_position=(0.52 * math.cos(angle), 0.52 * math.sin(angle), 0.0),
                     local_rotation=_quat(angle, (0.0, 0.0, 1.0)))
        _apply_explosion(body, position, 2.66 + index * 0.154, 0.24, random)
        render_material = materials["mechanism_gold" if index % 2 == 0 else "mechanism_copper"]
        prefix = f"gear_{index:02d}"
        body.attach_cylinder(prefix + "_body", (0.0, 0.0, -0.12),
                             (0.0, 0.0, 1.0), 0.24, 0.3025, render_material)
        body.attach_disk(prefix + "_front", (0.0, 0.0, 0.12),
                         (0.0, 0.0, 1.0), 0.3025, render_material)
        body.attach_disk(prefix + "_back", (0.0, 0.0, -0.12),
                         (0.0, 0.0, -1.0), 0.3025, render_material)
```

“一个 actor”不等于“一个 Renderer object”。typed attachment 层明确表达
一对多映射，并让 collision proxy 与视觉细节分别选择合适复杂度。

### 8.3 光、水与体积为什么不进入 PhysX

封面有三段祭坛火焰、两段近黑烟代理和一段冷色神光，共六个 flame；另有
一盏 directional 和四盏符文 point lights。48 颗火星与齿轮 core 是可见
emitter geometry，不注册为额外 NEE lights。第 11 章解释 flame 的
吸收—自发光模型；它不包含散射、燃烧化学或流体输运。

右侧水池使用第 12 章的解析波面和 RGB Beer 吸收，不是 PhysX particle、
SPH 或 FLIP。穹顶附近的 12 个霜晶是粗糙 metal sphere 外观代理，不是
dielectric 冰。这些 Renderer-only 元素与刚体附件最终都进入同一个
SceneBuilder，但不进入 worker request。

## 9. 契约怎样检查几何含义

### 9.1 Kinetic 的倾倒判据

令 actor 的局部上轴在世界空间为

$$
\mathbf u=R(\mathbf q)(0,1,0)^T.
$$

倾角 $\theta$ 满足 $\cos\theta=u_y$，所以倾倒超过 $15^\circ$ 的判据是

$$
u_y<\cos15^\circ.
$$

<!-- source-snippet id="physx-kinetic-validation" path="scenes/kinetic-foundry.py" anchor="toppled = 0" -->
```python
def _validate(result: PhysicsResult) -> bool:
    mascots = [body for body in result.bodies if body.category == "mascot"]
    if len(mascots) != 24 or len(result.bodies) != 216:
        return False
    threshold = math.cos(math.radians(15.0))
    toppled = 0
    for body in mascots:
        if _rotate(body.rotation, (0.0, 1.0, 0.0))[1] < threshold:
            toppled += 1
    return toppled >= 12
```

通用 `PhysicsResult.validate` 还检查 PhysX 5.8.0 固定 revision、CUDA 12.8、
GPU backend 标识、body 身份/顺序、单位四元数、attachment 数量、类型与归属。
Kinetic scene validator 再增加 24 个 mascot、216 个总 body 与至少 12 个倾倒
mascot 的构图条件。

### 9.2 封面的运动语义

封面不从某个相机角度猜测“像不像爆炸”，而是从 130 个 `BodyState` 计算
位移、速度、角速度和象限覆盖：

<!-- source-snippet id="physx-cover-validation" path="scenes/lava-temple-oracle.py" anchor="moving = radial = rotating = 0" -->
```python
    moving = radial = rotating = 0
    quadrants: set[tuple[bool, bool]] = set()
    maximum_upward = -math.inf
    for body in result.bodies:
        displacement = _sub(body.position, body.initial_position)
        speed = _length(body.linear_velocity)
        angular = _length(body.angular_velocity)
        if speed > 1.0e-3 or angular > 1.0e-3:
            moving += 1
        if _length(displacement) >= 0.08:
            radial += 1
            if abs(displacement[0]) > 1.0e-6 and abs(displacement[2]) > 1.0e-6:
                quadrants.add((displacement[0] > 0.0, displacement[2] > 0.0))
        if angular > 0.02:
            rotating += 1
        maximum_upward = max(maximum_upward, displacement[1])
        if not (-12.0 <= body.position[0] <= 12.0 and
                -0.2 <= body.position[1] <= 15.0 and
                -10.0 <= body.position[2] <= 8.0):
            return False
    return (moving >= 120 and radial >= 120 and rotating >= 12 and
            len(quadrants) == 4 and maximum_upward >= 0.08 and
            not any(body.sleeping for body in result.bodies))
```

因此有效样本必须至少有 120 个 actor 在运动、120 个位移不小于 0.08、四个
水平象限都有碎片、至少 12 个 actor 具有显著角速度、有可读的向上展开，且
没有 actor sleeping。结构契约不能代替人工构图检查，也不能证明真实材料
尺度或每个接触都物理正确。

## 10. 私有 IPC、持久 metadata 与可复现性

Python 用无 shell 的 `subprocess.run` 启动 worker，请求和结果路径都位于同一
`TemporaryDirectory`。worker 失败、没有写结果、协议版本错误、CUDA/PhysX
版本不符或 body 顺序改变都会硬失败。

<!-- source-snippet id="physx-private-ipc" path="python/spectraldock/physics.py" anchor="request_path = directory" -->
```python
    def _run_once(self, worker: Path, request: bytes, expected_seed: int,
                  directory: Path, suffix: str) -> PhysicsResult:
        request_path = directory / f"request-{suffix}.sdp"
        result_path = directory / f"result-{suffix}.sdp"
        request_path.write_bytes(request)
        command = (str(worker), "--request", str(request_path),
                   "--result", str(result_path))
        completed = subprocess.run(command, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, check=False)
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "no diagnostic"
            raise PhysicsError(
                f"GPU PhysX worker failed with exit code {completed.returncode}: {detail}"
            )
        if not result_path.is_file():
            raise PhysicsError("GPU PhysX worker did not create its result file")
```

`verify=True` 对同一 request 启动第二个独立 worker，并分别验证两份结果；它
只比较契约，不比较 `.sdp` 字节。只有 scene validator 拒绝一个结构有效的 GPU
样本时才会按 `max_attempts` 重试；环境、worker 或协议错误不会靠重试掩盖。

固定 seed、actor 创建顺序、步长、步数和 attachment 顺序约束输入及结构，
但 PhysX GPU 不支持 enhanced determinism。contact generation 和并行求解
顺序仍可造成微小差异，所以项目不承诺同机或跨 GPU、驱动、CUDA、PhysX、
编译器、操作系统的逐字节相同姿态。

被接受的 primary result 可原子写为同 stem `.physics.json`。数值最多保留六位
小数，包含版本和 actor 状态；private `.sdp` 永不持久化。metadata 是证据，
不是缓存或 scene input。

## 11. 当前能力边界

- 只渲染第 24 或第 300 步的 pose；metadata 保存速度，但 Renderer 不消费
  速度，也不输出接触点、冲量、能量或完整轨迹；
- 没有同进程逐帧 PhysX、交互、动画或 physics motion blur；
- 没有配置 CCD，固定离散步进不是连续碰撞保证；
- Kinetic capsule 是稳定代理，不证明三角网格碰撞正确；
- 封面碎片在模拟前已分离，没有 fracture、裂纹传播或动态 topology；
- 水面不是 PhysX 流体，火焰、烟和神光也不是流体或燃烧模拟；
- API 只暴露本项目需要的 materials、static plane/box、dynamic
  box/sphere/capsule/compound、速度、偏心冲量和 render attachments，不是
  通用 PhysX Python binding；
- host-only CI 不执行 PhysX 或 OptiX；正式验收必须在 NVIDIA GPU 测试机完成。

这种设计把职责分得很清楚：PhysX 为每次物理场景程序生成受约束的复杂单帧
布局，typed attachment 层把结果交给 SceneBuilder，SpectralDock 仍是离线
路径追踪器而不是通用实时物理引擎。

## 12. 对应实现与进一步阅读

- Python 物理 API、IPC、验证、metadata 与 typed handoff：
  [`python/spectraldock/physics.py`](../../python/spectraldock/physics.py)
- CUDA 12.8 / PhysX 5.8 GPU worker：
  [`tools/physx_worker.cpp`](../../tools/physx_worker.cpp)
- Kinetic actors、capsule/mesh mapping 与构图 validator：
  [`scenes/kinetic-foundry.py`](../../scenes/kinetic-foundry.py)
- 封面 130 actors、偏心冲量、复合齿轮和 attachments：
  [`scenes/lava-temple-oracle.py`](../../scenes/lava-temple-oracle.py)
- typed Renderer 与 SceneBuilder facade：
  [`python/spectraldock/_renderer.py`](../../python/spectraldock/_renderer.py)
- 原生 SceneBuilder：[`src/scene_builder.cpp`](../../src/scene_builder.cpp)
- [NVIDIA PhysX 5.8.0 固定源码](https://github.com/NVIDIA-Omniverse/PhysX/tree/fc1018a3745664a1db2b95ce03fb5e91eb585f2e)
- NVIDIA PhysX，[*GPU Rigid Bodies*](https://nvidia-omniverse.github.io/PhysX/physx/5.4.0/docs/GPURigidBodies.html)
- NVIDIA PhysX，[*Rigid Body Dynamics*](https://nvidia-omniverse.github.io/PhysX/physx/5.4.0/docs/RigidBodyDynamics.html)
- NVIDIA PhysX，[*Advanced Collision Detection*](https://nvidia-omniverse.github.io/PhysX/physx/5.1.2/docs/AdvancedCollisionDetection.html)

[上一章：边界、性能与验证](09-limitations-performance-and-validation.md) · [返回目录](README.md) · [下一章：程序化体积火焰](11-procedural-volumetric-flame.md)
