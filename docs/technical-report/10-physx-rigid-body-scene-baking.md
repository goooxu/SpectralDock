# 10　PhysX 刚体模拟与场景烘焙

前九章从场景 JSON 出发，解释 SpectralDock 怎样得到一张图。Kinetic
Foundry 在这条链之前多了一段**离线场景生成**：PhysX 5.8.0 先计算刚体
姿态，生成器再把一个固定时刻烘焙为普通 schema v4 JSON，最后仍由同一个
SpectralDock/OptiX 路径追踪器渲染。PhysX 不进入渲染器进程，也不在
`optixLaunch` 期间运行。

![Kinetic Foundry 在第 300 步的正式渲染结果](../gallery/kinetic-foundry.png)

*图 8：画面是 300 个固定时间步之后的清晰瞬时快照。钢珠和吉祥物的姿态
来自 PhysX；相机、灯光、材质和最终像素来自 SpectralDock。*

## 1. 从初始布局到一个可渲染场景

完整数据流是一次离线事务：

~~~mermaid
flowchart LR
    A["固定 seed 与初始布局"] --> B["PhysX actor、shape 与接触材质"]
    B --> C["GPU broad phase、接触生成与 TGS 求解"]
    C -->|"300 × 1/120 s"| D["读取位置 p 与四元数 q"]
    D --> E["烘焙 schema v4 JSON"]
    D --> F["写 physics sidecar"]
    E --> G["Python 契约验证"]
    F --> G
    G --> H["SpectralDock / OptiX 路径追踪"]
    H --> I["PNG 与 render stats"]
~~~

这条链有两个互不混用的 GPU 环境。物理生成器位于专用 CUDA 12.8.1、
PhysX 5.8.0 checked 容器；渲染器位于 CUDA 13.3、OptiX 9.1 环境。中间的
schema v4 JSON 是边界：它只描述静态几何、变换、相机、灯和渲染设置，
不携带 PhysX 对象或库句柄。

## 2. 刚体状态与 Newton–Euler 原理

一个动态刚体在时刻 $t$ 的最小概念状态可写为

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

$m$ 是质量，$\mathbf F$ 是合力，$\mathbf I$ 是在刚体坐标中表达的惯量
张量；上式中的 $\boldsymbol\omega$ 与合力矩 $\boldsymbol\tau$ 也在同一
坐标系表达。这个含陀螺项
的式子是经典连续体教学基准。当前生成器没有启用
`PxRigidBodyFlag::eENABLE_GYROSCOPIC_FORCES`，因此不能把该项解读为本场景
逐项启用的 PhysX 力模型。Kinetic Foundry 设置重力、接触、阻尼和初始
姿态；实际时间积分与约束求解由 PhysX 完成，项目没有自己实现上述微分
方程的积分器。

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

若 $\mathbf E$ 表示三阶单位矩阵，惯量张量的连续定义是

$$
\mathbf I=\int_V\rho
\left(\|\mathbf x\|^2\mathbf E-\mathbf x\mathbf x^{T}\right)\mathrm dV.
$$

生成器不手写这些闭式结果，而把 shape 和密度交给
`PxRigidBodyExt::updateMassAndInertia`。吉祥物 capsule 的密度为 2.4，钢珠
球体为 0.85；这些都是项目场景单位，报告不把它们宣称为千克或
千克每立方米。

<!-- source-snippet id="physx-body-properties" path="tools/generate_physx_kinetic_foundry.cpp" anchor="PxRigidBodyExt::updateMassAndInertia" -->
```cpp
    PxRigidDynamic* actor = runtime_.physics->createRigidDynamic(pose);
    if (!actor) fail("dynamic rigid actor creation failed");
    PxShape* shape = PxRigidActorExt::createExclusiveShape(
        *actor, geometry, *runtime_.material);
    if (!shape) {
      actor->release();
      fail("dynamic shape creation failed");
    }
    if (local_pose) shape->setLocalPose(*local_pose);
    if (!PxRigidBodyExt::updateMassAndInertia(*actor, density)) {
      actor->release();
      fail("mass/inertia computation failed");
    }
    actor->setSolverIterationCounts(8, 2);
    actor->setLinearDamping(0.08f);
    actor->setAngularDamping(0.12f);
    remember(actor);
    return actor;
```

每个动态刚体还设置 8 次位置迭代、2 次速度迭代，以及 0.08/0.12 的
线性/角阻尼。迭代数是求解器的下界配置，不等于外层的 300 个时间步。

## 3. 碰撞、接触与约束

宽相首先用包围体排除不可能接触的 shape。两个 AABB 成为候选对，至少要
在三个轴上都重叠：

$$
\min A_a\le\max B_a
\quad\text{且}\quad
\min B_a\le\max A_a,
\qquad a\in\{x,y,z\}.
$$

窄相再为候选 shape 产生接触点和法线。设 $g$ 是沿接触法线的间隙，
$\lambda_n$ 是法向冲量，理想刚性非穿透条件可写为

$$
g\ge0,
\qquad
\lambda_n\ge0,
\qquad
g\lambda_n=0.
$$

它表达三件事：物体不能穿透；接触只能推开而不能吸引；存在正间隙时法向
冲量必须为零。库仑摩擦的理想约束为

$$
\|\boldsymbol\lambda_t\|\le\mu\lambda_n,
$$

其中 $\boldsymbol\lambda_t$ 是切向冲量，$\mu$ 是摩擦系数。若把所有刚体
速度拼成 $\mathbf u$，一次约束修正可抽象为

$$
\mathbf u^+=\mathbf u^*+
\mathbf M^{-1}\mathbf J^{T}\boldsymbol\lambda.
$$

$\mathbf J$ 是约束 Jacobian，$\mathbf M$ 是块状质量与惯量矩阵。以上是理解
碰撞响应的教学模型，不是对 PhysX 内部 kernel 的逐行复现；实际离散、
摩擦锥近似、接触缓存与冲量迭代由 PhysX 实现。

### 3.1 本项目选择的 GPU 求解链

<!-- source-snippet id="physx-gpu-scene-contract" path="tools/generate_physx_kinetic_foundry.cpp" anchor="PxSceneFlag::eENABLE_GPU_DYNAMICS" -->
```cpp
    scene_desc.broadPhaseType = PxBroadPhaseType::eGPU;
    scene_desc.solverType = PxSolverType::eTGS;
    scene_desc.flags |= PxSceneFlag::eENABLE_GPU_DYNAMICS;
    scene_desc.flags |= PxSceneFlag::eENABLE_PCM;
    scene_desc.flags |= PxSceneFlag::eENABLE_STABILIZATION;
    // PhysX 5.8 explicitly does not support enhanced determinism on GPU.
    scene_desc.flags &= ~PxSceneFlag::eENABLE_ENHANCED_DETERMINISM;
    if (!scene_desc.isValid()) fail("GPU PxSceneDesc is invalid");
    scene = physics->createScene(scene_desc);
    if (!scene) fail("GPU PhysX scene creation failed; CPU fallback is forbidden");

    const PxSceneFlags flags = scene->getFlags();
    if (!flags.isSet(PxSceneFlag::eENABLE_GPU_DYNAMICS) ||
        !flags.isSet(PxSceneFlag::eENABLE_PCM) ||
        !flags.isSet(PxSceneFlag::eENABLE_STABILIZATION) ||
        flags.isSet(PxSceneFlag::eENABLE_ENHANCED_DETERMINISM) ||
        scene->getBroadPhaseType() != PxBroadPhaseType::eGPU ||
        !cuda_manager->contextIsValid()) {
      fail("created scene does not satisfy the PhysX GPU-only contract");
    }

    material = physics->createMaterial(0.58f, 0.52f, 0.04f);
    if (!material) fail("PxMaterial creation failed");
```

这里同时启用 GPU broad phase、GPU dynamics、PCM 和 stabilization，并选择
TGS。PCM 会跨时间步维护和更新接触流形；TGS 在一个外层时间步内以位置
迭代形成更细的时间分辨率。代码只依赖这些公开语义，不假定未公开的
kernel 排布或浮点执行顺序。

三个接触材质参数依次是静摩擦 0.58、动摩擦 0.52 和恢复系数 0.04。较低
恢复系数让碰撞主要表现为非弹性堆积。所有 PhysX shape 共用这份接触材质；
它和稍后 JSON 中的 Lambert、metal 等外观材质完全独立。

“GPU-only”也不表示整个主机程序没有 CPU 工作。主机仍创建 actor、提交
时间步、读取姿态、序列化 JSON 并运行 Python 验证器；契约要求的是 GPU
broad phase 与 GPU dynamics 有效，且创建失败时禁止静默退回 CPU 模拟。

## 4. 为什么使用 capsule 碰撞代理

吉祥物 OBJ 有 5,816 个三角形。逐三角形动态碰撞会显著增加接触生成成本，
还可能让装饰性的手臂、天线和靴子产生复杂接触。因此物理世界用一个
capsule 近似每个吉祥物，视觉世界仍使用完整 OBJ。

设 capsule 的中心为 $\mathbf p$，单位轴为 $\mathbf u$，圆柱半长为 $h$，
半径为 $r$。它可以理解为轴线段

$$
\{\mathbf p+\alpha\mathbf u\mid-h\le\alpha\le h\}
$$

沿所有方向膨胀半径 $r$。本项目取 $r=0.42$、$h=0.28$，总高度为

$$
2(h+r)=2(0.28+0.42)=1.4.
$$

吉祥物 OBJ 的原始高度为 2，渲染缩放 $s=0.7$ 后同样是 1.4。这不是逐
三角形贴合，但让碰撞代理与主要轮廓具有相同高度。

<!-- source-snippet id="physx-capsule-proxy" path="tools/generate_physx_kinetic_foundry.cpp" anchor="PxCapsuleGeometry(kCapsuleRadius, kCapsuleHalfHeight)" -->
```cpp
    const PxTransform capsule_pose(
        PxVec3(0.0f), PxQuat(PxHalfPi, PxVec3(0.0f, 0.0f, 1.0f)));
    const char* materials[] = {
        "mascot_vermilion", "mascot_gold", "mascot_cyan", "mascot_ivory"};
    for (PxU32 side_index = 0; side_index < 2; ++side_index) {
      const float direction = side_index == 0 ? -1.0f : 1.0f;
      const PxTransform& chute = chute_poses[side_index];
      for (PxU32 row = 0; row < 6; ++row) {
        for (PxU32 lane = 0; lane < 2; ++lane) {
          const PxU32 index = side_index * 12 + row * 2 + lane;
          const PxVec3 local(direction * (2.55f - 1.00f * row),
                             0.97f + random_.symmetric(0.015f),
                             lane == 0 ? -0.52f : 0.52f);
          const PxVec3 position = chute.transform(local);
          const float yaw = random_.symmetric(15.0f) * kPi / 180.0f;
          PxRigidDynamic* actor = add_dynamic(
              PxTransform(position, PxQuat(yaw, PxVec3(0.0f, 1.0f, 0.0f))),
              PxCapsuleGeometry(kCapsuleRadius, kCapsuleHalfHeight), 2.4f,
              &capsule_pose);
          mascots.push_back({actor, materials[index % 4]});
```

PhysX capsule 的局部轴经 `capsule_pose` 旋到 actor 的 $+Y$ 方向；actor 姿态
再把它旋到世界轴 $\mathbf u=R(\mathbf q)(0,1,0)^{T}$。钢珠无需代理映射，
物理和渲染都直接使用球心与半径。

## 5. 固定时间步与第 300 步

物理模拟采用

$$
\Delta t=\frac{1}{120}\ \mathrm s,
\qquad N=300,
$$

因此烘焙时刻是

$$
T=N\Delta t=300\times\frac{1}{120}=2.5\ \mathrm s.
$$

<!-- source-snippet id="physx-fixed-step-simulation" path="tools/generate_physx_kinetic_foundry.cpp" anchor="runtime_.scene->simulate(kFixedDt);" -->
```cpp
  void simulate() {
    for (PxU32 step = 0; step < kSteps; ++step) {
      runtime_.scene->simulate(kFixedDt);
      if (!runtime_.scene->fetchResults(true))
        fail("PxScene::fetchResults failed at step " + std::to_string(step));
      if (runtime_.error_callback.fatal_error.load(std::memory_order_relaxed))
        fail("PhysX reported a fatal error during GPU simulation");
    }
  }
```

`simulate` 提交一个时间步，`fetchResults(true)` 阻塞等待该步完成；下一步
不会和未完成的上一步重叠。固定步长避免墙钟抖动改变步数，但不自动带来
跨 GPU 确定性。

项目把第 300 步称为“撞击峰值”，含义是它经过候选图比较后被选为双滑槽
汇聚、物体仍明显处于级联中的构图时刻。生成器没有逐步记录总动能或接触
冲量，也没有搜索它们的数学最大值。

## 6. 从四元数姿态到渲染变换

PhysX 返回位置 $\mathbf p$ 与四元数 $\mathbf q$；schema v4 则保存平移、
XYZ 欧拉角和缩放。生成器先归一化四元数并构造旋转矩阵，然后求满足

$$
R=R_z(z)R_y(y)R_x(x)
$$

的三个角。在非万向锁区域，使用

$$
y=\sin^{-1}(-R_{20}),
\qquad
x=\mathrm{atan2}(R_{21},R_{22}),
\qquad
z=\mathrm{atan2}(R_{10},R_{00}).
$$

<!-- source-snippet id="physx-euler-conversion" path="tools/generate_physx_kinetic_foundry.cpp" anchor="const float y = std::asin" -->
```cpp
std::array<double, 3> euler_degrees(const PxQuat& input) {
  PxQuat q = input;
  q.normalize();
  const PxMat33 matrix(q);
  const float m00 = matrix.column0.x;
  const float m10 = matrix.column0.y;
  const float m20 = matrix.column0.z;
  const float m11 = matrix.column1.y;
  const float m21 = matrix.column1.z;
  const float m12 = matrix.column2.y;
  const float m22 = matrix.column2.z;
  const float y = std::asin(std::max(-1.0f, std::min(1.0f, -m20)));
  float x = 0.0f;
  float z = 0.0f;
  if (std::fabs(std::cos(y)) > 1.0e-6f) {
    x = std::atan2(m21, m22);
    z = std::atan2(m10, m00);
  } else {
    x = std::atan2(-m12, m11);
  }
  const double to_degrees = 180.0 / static_cast<double>(kPi);
  return {rounded(x * to_degrees), rounded(y * to_degrees),
          rounded(z * to_degrees)};
}
```

当 $|\cos y|\le10^{-6}$ 时，代码固定 $z=0$，并从 $R_{12},R_{11}$ 恢复
$x$。欧拉角在万向锁附近不是唯一的，但得到的旋转矩阵仍可表示同一姿态。
渲染器的 `compose_transform` 和 Python 验证器都使用同样的
$R_zR_yR_x$ 顺序。

### 6.1 为什么平移不是直接写入物理中心

吉祥物 OBJ 的原点位于脚底，模型包围盒中心在局部 $(0,1,0)$；缩放后中心偏移为
$(0,s,0)$，其中 $s=0.7$。物理 actor 原点位于 capsule 中心，因此 JSON
平移必须取

$$
\mathbf t=\mathbf p-R(\mathbf q)(0,s,0)^{T}.
$$

这样渲染网格的中心重新落在

$$
\mathbf t+R(\mathbf q)(0,s,0)^{T}=\mathbf p.
$$

<!-- source-snippet id="physx-pose-baking" path="tools/generate_physx_kinetic_foundry.cpp" anchor="pose.q.rotate(PxVec3(0.0f, -kMascotScale, 0.0f))" -->
```cpp
  for (PxU32 index = 0; index < world.mascots.size(); ++index) {
    const MascotRecord& record = world.mascots[index];
    const PxTransform pose = record.actor->getGlobalPose();
    const PxVec3 translate =
        pose.p + pose.q.rotate(PxVec3(0.0f, -kMascotScale, 0.0f));
    const auto rotation = euler_degrees(pose.q);
    char name[32];
    std::snprintf(name, sizeof(name), "mascot_%02u", index);
    objects.push_back(
        {{"name", name},
         {"type", "mesh"},
         {"mesh", "mascot"},
         {"transform",
          {{"translate", vector_json(translate)},
           {"rotate_degrees",
            json::array({rotation[0], rotation[1], rotation[2]})},
           {"scale", json::array({0.7, 0.7, 0.7})}}},
         {"material", record.material}});
```

球体没有模型原点补偿：生成器直接把 actor 的 $\mathbf p$ 写成 sphere
`center`，并沿用物理半径。

## 7. 物理世界与视觉世界不是同一份几何

物理场景包含地面、四周挡墙，以及每条滑槽的底板和两侧护栏；渲染场景只
保留地面、后墙和两块可见滑槽面。护栏和侧墙仍能改变碰撞结果，但不必全部
出现在相机中。反过来，相机、背景、三盏灯、颜色和金属粗糙度只存在于
渲染 JSON，不参与 PhysX。

| 数据 | PhysX 阶段 | 渲染阶段 |
|---|---|---|
| 吉祥物形状 | 单个 capsule 代理 | 完整 5,816 三角形 OBJ |
| 钢珠形状 | sphere | sphere |
| 材质 | 静/动摩擦与恢复系数 | BSDF、颜色与粗糙度 |
| 输出状态 | $\mathbf p,\mathbf q$，内部还有速度与接触 | 只消费烘焙后的位置与姿态 |
| 时间 | 300 个固定物理步 | 单张静态图片 |

因此，改变 BSDF 不会改变碰撞；改变摩擦系数也不会直接改变物体的颜色。

## 8. 契约怎样检查几何含义

烘焙后的 JSON 已不再含 capsule 对象，验证器必须从 mesh 变换重建物理中心
和朝上方向。令

$$
\mathbf u=R(\mathbf q)(0,1,0)^{T}.
$$

竖直方向上的 capsule 最低点为

$$
y_{\min}=p_y-r-h|u_y|.
$$

倾角 $\theta$ 满足 $\cos\theta=u_y$，因此倾倒超过 $15^\circ$ 的判据是

$$
u_y<\cos15^\circ.
$$

<!-- source-snippet id="physx-baked-scene-validation" path="tools/check_physx_scene.py" anchor="lowest = center[1] - CAPSULE_RADIUS" -->
```python
    toppled = 0
    for index, obj in enumerate(mascots):
        _require(obj.get("mesh") == "mascot", "mascot {} has wrong mesh".format(index))
        transform = obj.get("transform", {})
        translate = _finite_vector(transform.get("translate"), 3, "mascot translate")
        rotation = _finite_vector(transform.get("rotate_degrees"), 3, "mascot rotation")
        scale = _finite_vector(transform.get("scale"), 3, "mascot scale")
        _require(all(abs(value - MASCOT_SCALE) <= 1.0e-6 for value in scale), "mascot scale changed")
        matrix = _rotation_xyz(rotation)
        up = _mul(matrix, (0.0, 1.0, 0.0))
        center = _add(translate, _mul(matrix, (0.0, MASCOT_SCALE, 0.0)))
        _require(
            all(bound_min[axis] <= center[axis] <= bound_max[axis] for axis in range(3)),
            "mascot center is outside the pool bounds",
        )
        lowest = center[1] - CAPSULE_RADIUS - CAPSULE_HALF_HEIGHT * abs(up[1])
        _require(lowest >= -0.08, "mascot capsule penetrates the ground")
        if up[1] < math.cos(math.radians(15.0)):
            toppled += 1
```

完整契约还要求 24 个吉祥物、192 颗钢珠、4 个可见 rectangle、220 个
objects、固定命名与顺序、有限数值、落地区域、GPU-only flags，以及至少
12 个倾倒吉祥物。当前正式 sidecar 记录 24 个倾倒吉祥物。

`sleeping_dynamic_actors=0` 只说明截帧时没有动态 actor 进入 PhysX 的
sleeping 状态。awake actor 仍可能在某一瞬间速度很小，因此这个字段不能
证明每个物体速度非零，更不能证明总动能达到最大值。

## 9. 可复现输出与确定性边界

生成器固定 SplitMix64 seed、actor 创建顺序、导出顺序、步长和步数；浮点
输出统一舍入到最多六位小数，并通过临时文件加 rename 原子替换目标。这些
约束固定了输入和输出结构，却不能固定 GPU 接触生成与并行求解顺序。生成
入口最多尝试八次；PhysX 子进程异常，或穿地、越界、结构不合约的样本都会
进入下一次尝试，而不是放宽安全门：

<!-- source-snippet id="physx-contract-verification" path="scripts/generate-physx-scene.sh" anchor="for ((attempt = 1; attempt <= max_attempts; ++attempt))" -->
```bash
generate_valid() {
  local scene_path="$1"
  local metadata_path="$2"
  local attempt
  for ((attempt = 1; attempt <= max_attempts; ++attempt)); do
    if run_simulation "${scene_path}" "${metadata_path}" &&
       physx_container python3 tools/check_physx_scene.py \
        "${scene_path}" "${metadata_path}"; then
      printf 'accepted GPU sample on attempt %d/%d\n' \
        "${attempt}" "${max_attempts}"
      return 0
    fi
    printf 'retrying failed or rejected GPU sample (%d/%d)\n' \
      "${attempt}" "${max_attempts}" >&2
  done
  rm -f "${ROOT}/${scene_path}" "${ROOT}/${metadata_path}"
  die "PhysX GPU produced no valid scene after ${max_attempts} attempts"
}
```

普通生成调用该函数一次；`--verify` 再调用一次，要求得到两份独立的合约
样本，但不比较姿态字节。PhysX GPU 不支持 enhanced determinism，所以相同
测试机、GPU、镜像、seed 与固定步长仍可能产生不同的有效姿态；sidecar 明确
记录这一限制。项目不承诺同机或跨 GPU、驱动、CUDA、PhysX、编译器、操作
系统得到逐字节相同的 JSON。

## 10. 烘焙方案的能力边界

- 只导出第 300 步的 $\mathbf p$ 与 $\mathbf q$，不导出线速度、角速度、
  接触点、冲量、能量或完整轨迹；
- 没有运行时 PhysX、交互、动画或物理 motion blur；画面是锐利的单帧；
- 没有 CCD 配置，报告不把离散步进描述为连续碰撞保证；
- capsule 只是吉祥物外形的稳定近似，不是逐三角形物理正确性证明；
- Python 契约能发现越界、明显落地穿透和结构漂移，不能证明每个接触都符合
  现实材料或真实世界尺度；
- host-only CI 不执行 PhysX。物理检查依赖专用镜像、两次独立 GPU 生成、
  两组契约检查和人工构图审查。

这些边界正是烘焙设计的取舍：PhysX 只负责生成一个受约束、可复查的
复杂布局；SpectralDock 仍是一个离线静态路径追踪器，而不是通用物理引擎。

## 11. 对应实现与进一步阅读

- PhysX runtime、actor、固定步与烘焙：
  [`generate_physx_kinetic_foundry.cpp`](../../tools/generate_physx_kinetic_foundry.cpp)
- scene/sidecar 契约：[`check_physx_scene.py`](../../tools/check_physx_scene.py)
- 双生成与容器入口：[`generate-physx-scene.sh`](../../scripts/generate-physx-scene.sh)
- 生成后渲染入口：[`render-physx-scene.sh`](../../scripts/render-physx-scene.sh)
- 渲染 transform 顺序：[`compose_transform`](../../src/scene.cpp)
- [NVIDIA PhysX 5.8.0 固定源码](https://github.com/NVIDIA-Omniverse/PhysX/tree/fc1018a3745664a1db2b95ce03fb5e91eb585f2e)。
- NVIDIA PhysX，[*GPU Rigid Bodies*](https://nvidia-omniverse.github.io/PhysX/physx/5.4.0/docs/GPURigidBodies.html)。
- NVIDIA PhysX，[*Rigid Body Dynamics*](https://nvidia-omniverse.github.io/PhysX/physx/5.4.0/docs/RigidBodyDynamics.html)，包括 TGS、质量属性、摩擦与 sleeping。
- NVIDIA PhysX，[*Advanced Collision Detection*](https://nvidia-omniverse.github.io/PhysX/physx/5.1.2/docs/AdvancedCollisionDetection.html)，包括 PCM。

[上一章：边界、性能与验证](09-limitations-performance-and-validation.md) · [返回目录](README.md) · [下一章：程序化体积火焰](11-procedural-volumetric-flame.md)
