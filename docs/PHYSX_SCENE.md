# PhysX 物理场景：Python 即时构建与 OptiX 交接

PhysX 是 SpectralDock **物理场景的核心构建子系统**。Kinetic Foundry、
“熔岩圣殿的机械先知”（`lava-temple-oracle`）、Atelier 与 Assembly Hall
都是普通、可直接执行的 Python 程序；它们不会读取预烘焙姿态或场景 JSON。
每次运行都显式创建
`PhysicsWorld`，在 PhysX 5.8.0 GPU 上重新模拟，把选定时刻的 typed render
attachments 或经验证 `BodyState` 姿态应用到 `Renderer`，然后才调用 OptiX 渲染。

这里的“即时构建”指一次离线渲染命令内重新求出单帧布局。PhysX 不在
`optixLaunch` 中逐帧执行，项目也没有交互动画、物理 motion blur 或旧物理
状态回放入口。

## 四个物理场景

| Python 程序 | 动态物理构图 | 固定取景时刻 | seed | 正式输出 |
| --- | --- | ---: | ---: | --- |
| `scenes/kinetic-foundry.py` | 24 个 capsule 吉祥物代理与 192 颗钢珠的双滑槽撞击 | 300 × 1/120 s = 2.5 s | 20260711 | 1920×1080、512 spp、depth 12、Denoiser |
| `scenes/lava-temple-oracle.py` | 130 个预碎裂刚体从祭坛上方径向爆发 | 24 × 1/120 s = 0.2 s | 909 | 3840×2160、2048 spp、depth 12、Denoiser |
| `scenes/atelier.py` | 9 块彩砖、2 个外观球和 3 个角色代理落定 | 480 × 1/120 s = 4 s | 20260717 | 2560×1440、1024 spp、depth 12、Denoiser |
| `scenes/assembly-hall.py` | 12 个 Spot 代理从倾斜玩具箱半空倾泻 | 36 × 1/120 s = 0.3 s | 20260718 | 2560×1440、2048 spp、depth 12、Denoiser |

四个程序都通过当前 worker 契约要求 PhysX 5.8.0、固定源码 revision、CUDA
12.8、GPU broad phase、
GPU dynamics、TGS、PCM 与 stabilization。PhysX GPU 不支持 enhanced
determinism，因此该 flag 明确关闭。创建 CUDA context 或 GPU scene 失败时
程序立即报错；不存在 CPU dynamics fallback。

“GPU-only 物理”不等于宿主完全不做工作。Python 仍定义 actor 与视觉资源，
worker 的单线程 CPU dispatcher 仍负责 PhysX 所需的宿主调度；契约所禁止的
是把 broad phase 或 rigid-body dynamics 静默换成 CPU 求解。

## 真实进程和数据流

~~~mermaid
flowchart LR
    A["可执行 scenes/*.py"] --> B["创建 Renderer 资源与 PhysicsWorld"]
    B --> C["写 TemporaryDirectory 内 private request.sdp"]
    C --> D["CUDA 12.8 / PhysX 5.8 GPU worker"]
    D --> E["写 TemporaryDirectory 内 private result.sdp"]
    E --> F["PhysicsResult 验证版本、GPU 契约与 actor 顺序"]
    F --> G["body states / typed attachments 的世界空间参数"]
    G --> H["apply_to 或场景手动实例化 Renderer 几何"]
    H --> I["SceneBuilder → CUDA 13.3 / OptiX 9.1"]
    I --> J["PNG 与 render stats"]
    F --> K["可选、人类可读 .physics.json"]
~~~

上图中 `.sdp` 是内部、版本化的二进制 IPC。它只存在于
`tempfile.TemporaryDirectory`，子进程结束后被删除；它不是场景格式、不是
公共 API、不会提交到仓库，也没有读取任意 `.sdp` 的用户入口。其目的只是让
PhysX worker 使用 CUDA 12.8，而 Python 父进程中的 Renderer native extension
使用 CUDA 13.3，避免两个 CUDA runtime、指针、context 或 SDK 句柄进入同一
地址空间。

持久 `.physics.json` 与 IPC 完全不同。它是人类可读的审计 sidecar，记录
scene、seed、设备、CUDA/PhysX 版本、固定步长、GPU-only flags、actor 初末
姿态/速度、sleeping 状态与 attachment 数量。它不含完整 Renderer 场景，
不能作为下一次渲染输入，也不能跳过 fresh PhysX 模拟。

## 构建边界

渲染器与 PhysX worker 必须使用两个构建目录。根 CMake 会拒绝在一个 target
图中同时启用二者：

| 构建目录 | 关键选项 | 工具链 | 产物 |
| --- | --- | --- | --- |
| `build/Release` | `SPECTRALDOCK_ENABLE_GPU=ON` | CUDA 13.3、OptiX 9.1 | `python/spectraldock/_native` |
| `build/PhysX` | `SPECTRALDOCK_ENABLE_PHYSX_SCENE=ON` | CUDA 12.8、PhysX 5.8.0 | `spectraldock_physx_worker` |

PhysX worker 的 CMake fragment 还会检查 `CUDAToolkit_VERSION` 确实属于 12.8。
Python 默认在 `build/PhysX/spectraldock_physx_worker` 查找它；高级调试可用
`SPECTRALDOCK_PHYSX_WORKER` 指向同协议的可执行文件。没有 worker 时不会
退回另一套物理实现。

准备用户自行取得的 CUDA、OptiX 与 PhysX SDK 后：

```bash
export SPECTRALDOCK_CUDA_ROOT=/absolute/path/to/cuda-13.3
export OPTIX_ROOT=/absolute/path/to/OptiX-SDK-9.1.0
export SPECTRALDOCK_PHYSX_CUDA_ROOT=/absolute/path/to/cuda-12.8
export PHYSX_ROOT=/absolute/path/to/physx-5.8-install

./scripts/configure.sh Release
./scripts/build.sh Release
source ./scripts/activate.sh Release
```

PhysX SDK、CUDA、OptiX 以及它们的构建产物不随仓库分发。项目不提供或要求
容器镜像；路径由宿主环境明确给出。

## 普通 Python 程序入口

四个物理程序和八个静态教学例子使用相同的直接执行方式：

```bash
python3 scenes/kinetic-foundry.py
python3 scenes/lava-temple-oracle.py
python3 scenes/atelier.py
python3 scenes/assembly-hall.py
```

程序中的顺序是可见且不可绕过的：

```python
physics = create_physics_world()
renderer = create_renderer(
    physics,
    metadata_output=output.with_suffix(".physics.json"),
    verify=True,
)
renderer.render(...)
```

原有教学场景和 Atelier 的 `create_renderer` 先创建 Renderer 材质/网格与静态几何，再向传入的
`PhysicsWorld` 添加接触材质、static actors、dynamic rigid bodies、碰撞
shape、初始速度、冲量与 renderer-local attachments；随后显式调用
`physics.simulate(...)`；attachments 可由 `result.apply_to(renderer)` 应用，
完整角色也可像 Atelier/Assembly Hall 那样读取 `BodyState` 后显式创建 mesh
实例。这只是场景自身的普通 helper，不是 loader 协议或隐藏 CLI。

`./scripts/render-examples.sh` 仍只依次执行原有十个教学 `scenes/*.py`。脚本本身不会预加载
PhysX；执行到最后两个程序时，它们各自 fresh 启动 worker。十个程序都在
`output/examples/` 写 PNG 与 `.stats.json`，只有两个物理程序额外写同 stem
的 `.physics.json`。Atelier 与 Assembly Hall 属于独立的 PhysX Gallery
验收组，不加入这个旧教学批处理；其命令默认只在 `output/gallery/` 写运行产物。

## 受限而明确的 Python 物理 API

公共入口位于 `python/spectraldock/physics.py`：

- `PhysicsWorld.material` 创建静摩擦、动摩擦与恢复系数；
- `static_plane`、`static_box` 创建不可动碰撞边界；
- `rigid_body` 创建带位置、四元数、密度、阻尼、sleep threshold 和 solver
  iteration counts 的动态 actor；
- `RigidBody.box`、`sphere`、`capsule` 可在一个 actor 上叠加为 compound；
- `linear_velocity`、`angular_velocity` 和
  `mass_scaled_impulse_at_position` 定义初始运动；
- `attach_sphere`、`attach_rectangle`、`attach_cylinder`、`attach_disk`、
  `attach_mesh` 把 Renderer typed handles 与 actor-local 几何关联；
- `simulate` 启动隔离 worker，`PhysicsResult.apply_to` 通过 Renderer 公共 API
  创建最终世界空间对象。

API 有意不暴露 joints、cloth、particles、vehicles、articulations、cooking、
callbacks 或通用 PhysX 指针。它服务于这四个研究/展示场景，不宣称是完整的
PhysX Python binding。

## typed attachment 怎样跨边界

Python 父进程持有 `MaterialHandle` 与 `MeshHandle`，这些对象不会被序列化，
也不会传入 worker。IPC 只为每个 attachment 发送稳定索引、类型和 actor-local
数值。模拟后 worker 用最终 `PxTransform` 计算：

- sphere 的世界中心；
- rectangle 的三个世界顶点；
- cylinder 的世界 base 与旋转后的单位 axis；
- disk 的世界中心与法线；
- mesh 的世界平移、XYZ 欧拉角与缩放。

Python 按索引把这些数值与原来的 typed handles 重新结合，再调用
`renderer.object(...)`。因此 worker 不认识 BSDF、OBJ 或 SceneBuilder，
Renderer 也不认识 `PxRigidDynamic`；共享的是受验证的纯数值，而不是指针。

## Kinetic Foundry 契约

24 个吉祥物以单个 capsule 参与碰撞，最终姿态再应用到完整
5,816-triangle mascot OBJ。capsule 半径为 0.42、圆柱半长为 0.28；OBJ 缩放
为 0.7，两者主轮廓高度同为 1.4。192 颗钢珠在物理和渲染两侧都使用 sphere。

场景 validator 要求 actor 数量与类别正确，并至少有 12 个吉祥物的局部上轴
相对世界上方向倾斜超过 15°。第 300 步是经过构图选择的撞击瞬间，不是总
动能的数学最大值，也不是最终稳定堆积。

## 熔岩圣殿专题的物理映射

该专题场景恰好包含 130 个 dynamic actors：

| 类别 | 数量 | PhysX 表示 | Renderer attachment |
| --- | ---: | --- | --- |
| 外壳板 | 24 | box | 成对 rectangle：深灰外壳与金色断面 |
| 面罩 / 眼部 | 2 / 2 | box / sphere | rectangle / emissive sphere |
| 肢体 / 天线 | 4 / 3 | capsule / sphere | cylinder、sphere |
| 复合齿轮 | 6 | hub sphere + 6 个 tooth boxes | cylinder、disk、辐条与齿面 |
| 其他机械件 | 29 | capsule 或 box | 铜/金色解析 primitive |
| 坍塌顶石 | 12 | box | 三个可见 rectangle 面 |
| 火星 | 48 | sphere | 小型 emissive sphere |

机械先知从模拟开始时就是 70 个独立、预碎裂部件。偏心质量缩放冲量同时
产生线速度变化和角冲量；顶石与火星另有初始线速度和角速度。PhysX 计算
质量/惯量、碰撞、接触约束和 24 个固定步，但没有动态网格切割、破坏阈值、
裂纹传播或拓扑 fracture。

静态圣殿、祭坛、符文、解析水面和灯光直接由 Renderer 构建，不进入 PhysX。
水面是 SpectralDock 的解析高度场，不是 PhysX 流体；三段火焰、两段烟代理
和冷色神光是吸收—自发光 volume，不是燃烧或流体模拟。场景以不超过 450
个 Renderer objects 作为教学复杂度预算；实际数量以同次 render stats 为准。

熔岩圣殿 validator 要求 130 个 actor 全部在边界内、至少 120 个仍在运动、至少
120 个位移不小于 0.08、水平四象限都有碎片、至少 12 个有显著角速度，并且
没有 actor sleeping。它保护结构与运动语义，但不能代替构图人工审查。

## Atelier 与 Assembly Hall 封面契约

Atelier 恰好创建 14 个 dynamic actors：9 块彩砖、金属球、磨砂外观球、
Capsule、Spot 和 Sparky。彩砖以 box 求接触，两个球以 sphere 求接触，三个
角色使用稳定的简化 proxy；场景读取最终 `BodyState` 后手动实例化完整多材质
网格。第 480 步选择落定构图，validator 检查 actor 数量、相对
初始状态的明显下落、工坊边界、水盆隔离、低速度，以及大多数 actor 已进入
sleeping。它验证“已经落定”的结构语义，不承诺每次 GPU 接触求解得到逐字节
相同的堆叠姿态。

Assembly Hall 只让从玩具箱倾泻的 12 个 Spot 进入 PhysX；传送带上的四个
Sparky、天窗、桁架、炉火、冷却池与 Capsule 都是 Renderer 构图。Spot 使用
box collision proxy；场景读取最终 `BodyState` 后手动实例化完整纹理网格，
而不把 Spot 网格登记为 attachment。第 36 步刻意选择在半空而非落定时刻。
validator 要求全部 12 个 actor 留在大厅边界内、至少 8 个仍在
空中，并且至少 6 个已经发生明显位移且未 sleeping。

两个封面中的水面、flame、灯光和 alpha 标志都不进入 worker。Atelier 用有限
disk 面灯近似 spotlight；Assembly Hall 用吸收性 flame 近似烟影、粗糙
PBR 肋条安全罩与三个有限 emitter 球近似磨砂安全隔间、现有 PBR 瓣近似 clearcoat，并用同位
rectangle NEE 灯近似纹理屏幕发光采样。这些是场景级视觉替代，不是 PhysX
特性，也没有扩展 Renderer API。

## 独立验证与确定性边界

`verify=True` 会对同一 typed request 启动第二个独立 worker，并分别运行
scene validator。两次都必须满足契约，但不会比较 IPC 字节或最终浮点姿态。
GPU contact generation 与并行求解顺序可能产生微小差异；固定 seed、actor
创建顺序、步长和步数只约束输入，不提供跨 GPU、驱动、CUDA、PhysX、编译器
或操作系统的逐字节确定性。

只有 scene validator 明确拒绝有效 GPU 结果时，`max_attempts` 才允许用同一
seed 再试。worker 启动失败、版本错误、CUDA context 错误或协议错误会立即
失败，不会靠重试掩盖环境问题。

维护者验收应在指定 NVIDIA GPU 测试机完成：Renderer 部分会运行五个纯
Renderer Gallery 程序的 preview；PhysX 部分再运行两个物理教学程序和两个
PhysX Gallery 封面的低成本物理/渲染预览，
人工检查穿透、越界、附件方向、火焰、水池和构图；随后用一次显式
`--target-processes all` memcheck 同时检查 CUDA 13.3 OptiX 根进程与隔离的
CUDA 12.8 PhysX worker，并检查正式分辨率。PhysX 5.8 内部容量缓冲复制会
产生上游 initcheck 诊断，因此项目不宣称对 worker 运行 initcheck 或
racecheck；GPU-only 身份、双运行 validator 与独立渲染帧是结果契约，也不
冒充内存安全检查。标准 GitHub hosted runner 不执行 PhysX 或 OptiX。

## 持久产物与许可

仓库保留旧十个教学程序的正式 gallery PNG 与 render `.stats.json`，
其中两个旧 PhysX 教学场景还保留同次运行的 `.physics.json`。新 Gallery 的
三张综合展示和十二张 OFF/ON 对比图只提交 PNG，不提交测试机 stats 或
physics sidecar，也不建立像素 golden 或性能基准。不得保存 private `.sdp`，
也不存在序列化后的物理场景输入。
`.physics.json` 的代码/数据结构按 Apache-2.0 提供；gallery PNG 属于
明确列出的 CC0-1.0 视觉资产。

现有 gallery sidecar 是正式图片验收时的历史原始记录，因此保留旧聚合字段；
当前 Python API 新运行产生的是 `spectraldock.physics/1`、逐 body 状态和
`render_attachments`。文档不把历史 sidecar 冒充为当前可回放输入，也不会
仅为字段迁移而改写其 provenance。

PhysX 保持上游 BSD-3-Clause 许可，SDK 和构建产物不随仓库分发。NVIDIA、
CUDA、OptiX、PhysX 和 RTX 是 NVIDIA Corporation 的商标或注册商标；
SpectralDock 是独立的非官方项目，与 NVIDIA Corporation 无隶属关系，也未
获得其赞助或背书。
