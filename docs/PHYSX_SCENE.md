# PhysX 物理场景：GPU JIT 构建与 OptiX 交接

PhysX 是 SpectralDock **物理场景的核心构建子系统**。Kinetic Foundry 与
“熔岩圣殿的机械先知”（`lava-temple-oracle`）不读取仓库中预存的姿态；
每次物理场景渲染命令都先在 PhysX 5.8.0 GPU 上重新模拟，再把当次结果写成
临时 schema v6 JSON，完成契约检查后立即交给 SpectralDock/OptiX 渲染。

这里的 JIT 指“随一次渲染命令即时生成场景”。PhysX 进程与 OptiX 渲染
进程相邻但分离，二者不共享 actor、CUDA 指针或库句柄，PhysX 也不在
`optixLaunch` 中逐帧执行。默认八个静态 `scenes/*.json` 和
`render-examples.sh` 批处理不会初始化 PhysX。

## 两个物理场景

| scene id | 物理构图 | 固定物理时刻 | 默认 seed | 正式输出 |
| --- | --- | ---: | ---: | --- |
| `kinetic-foundry` | 24 个 capsule 吉祥物代理与 192 颗钢珠的双滑槽撞击 | 300 × 1/120 s = 2.5 s | 20260711 | 1920×1080、512 spp、depth 12、Denoiser |
| `lava-temple-oracle` | 130 个预碎裂刚体从祭坛上方径向爆发 | 24 × 1/120 s = 0.2 s | 909 | 3840×2160、2048 spp、depth 12、Denoiser |

二者都采用 GPU broad phase、GPU dynamics、TGS、PCM 与 stabilization，
禁止 CPU dynamics fallback。PhysX GPU 不支持 enhanced determinism，所以
该 flag 明确关闭。`sleeping_dynamic_actors=0` 是两个选定时刻的契约之一，
说明画面截取运动过程而不是稳定堆积结果。

## 一次渲染命令的数据流

~~~mermaid
flowchart LR
    A["选择 scene、device 与 seed"] --> B["清理旧临时 scene / sidecar"]
    B --> C["PhysX 5.8 GPU 固定步模拟"]
    C --> D["导出姿态与 physics sidecar"]
    D --> E["写临时 schema v6 JSON"]
    E --> F["Python 场景契约检查"]
    F --> G["SpectralDock / OptiX 渲染"]
    G --> H["PNG 与 render stats"]
    D --> I["final 保存同次 physics sidecar"]
    G --> J["清理临时 scene"]
~~~

临时 schema 是明确的 ABI 边界：它只携带静态几何、材质、相机、灯光、
渲染设置，以及从 PhysX 姿态变换而来的 renderer primitive 参数。渲染器
本身不链接 PhysX，物理专用镜像也不包含 OptiX SDK。这样的进程边界让
PhysX 与 OptiX 可以使用各自验证过的 CUDA 环境，同时保证物理结果确实来自
同一条用户命令。

## 固定生成环境

`Dockerfile.physx` 使用 CUDA 12.8.1 开发镜像，在构建镜像时从 NVIDIA
官方仓库获取 PhysX，并固定到：

- repository: `https://github.com/NVIDIA-Omniverse/PhysX`
- tag: `110.0-omni-and-physx-5.8.0`
- commit: `fc1018a3745664a1db2b95ce03fb5e91eb585f2e`
- license: BSD-3-Clause

默认渲染器构建不会查找 PhysX。专用镜像在容器内提供 checked 版
`/opt/physx`，无需在宿主机设置 `PHYSX_ROOT`；渲染阶段仍要求用户自行取得
OptiX 9.1，并通过 `OPTIX_ROOT` 只读挂载。

## 统一生成与渲染入口

首次使用先构建 PhysX 镜像：

```bash
./scripts/build-physx-image.sh
```

只生成并检查临时场景：

```bash
./scripts/generate-physx-scene.sh \
  --scene kinetic-foundry --device 0 --seed 20260711 --verify

./scripts/generate-physx-scene.sh \
  --scene lava-temple-oracle --device 0 --seed 909 --verify
```

`--scene` 省略时为兼容已有命令而默认 `kinetic-foundry`。两个 CMake target
分别是 `spectraldock_physx_scene` 与
`spectraldock_physx_lava_temple_oracle`；只有显式设置
`SPECTRALDOCK_ENABLE_PHYSX_SCENE=ON` 时才构建。对应契约检查器为：

```bash
python3 tools/check_physx_scene.py \
  scenes/generated/kinetic-foundry.json \
  scenes/generated/kinetic-foundry.physics.json

python3 tools/check_physx_lava_temple_oracle.py \
  scenes/generated/lava-temple-oracle.json \
  scenes/generated/lava-temple-oracle.physics.json
```

普通预览写入被忽略的 `output/examples/`：

```bash
OPTIX_ROOT="/absolute/path/to/OptiX-SDK-9.1.0" \
  ./scripts/render-physx-scene.sh \
    --scene lava-temple-oracle --preset preview
```

`final` 会替换该 stem 受版本控制的 PNG、渲染 stats 与**同一次模拟**的
physics sidecar。封面 final 固定 4K；不要把它加入八个静态场景的默认批处理：

```bash
OPTIX_ROOT="/absolute/path/to/OptiX-SDK-9.1.0" \
  ./scripts/render-physx-scene.sh \
    --scene lava-temple-oracle --preset final
```

入口没有复用旧场景或跳过物理的选项。开始时会清理旧临时产物，成功或失败
退出时都不把 `scenes/generated/*.json` 作为仓库输入。`--verify` 生成第二份
独立样本并分别验证两份契约；由于 GPU 非逐字节确定，它不比较姿态字节。

## Kinetic Foundry 契约

Kinetic Foundry 的 24 个动态吉祥物以 capsule 参与碰撞；渲染时再把相同
PhysX 姿态应用到完整 5,816-triangle OBJ。192 颗钢珠在物理和渲染两侧都
直接使用 sphere。契约要求固定 actor/对象顺序、有限姿态、落地区域、无
明显穿地、至少 12 个倾角超过 15° 的吉祥物、300 步与 0 个 sleeping
dynamic actors。它是撞击峰值的清晰静态单帧，不是最终稳定状态，也没有
motion blur。

## 熔岩圣殿封面的物理与渲染映射

封面动态世界恰好包含 130 个 actor：

| 类别 | 数量 | 物理表示与渲染表示 |
| --- | ---: | --- |
| 外壳板 | 24 | box 碰撞；成对 rectangle 显示深灰外侧和金色内侧断面 |
| 面罩板 / 眼部 | 2 / 2 | box 或 sphere；解析 rectangle / sphere |
| 肢体 / 天线部件 | 4 / 3 | capsule 或 box；cylinder、sphere、rectangle |
| 复合齿轮 | 6 | 每个 actor 带多个碰撞 shape；disk/cylinder、齿与辐条组合 |
| 其他机械部件 | 29 | box、capsule 或 sphere；金色/铜色解析 primitive |
| 坍塌顶石 | 12 | box；粗糙黑石 rectangle 组合 |
| 火星 | 48 | sphere；小型 emissive sphere，但不注册为显式灯 |

先知的 70 个部件在模拟开始前已分离；生成器对它们施加从非中心爆点向外并
向上的偏心线性冲量，由作用点产生角冲量。顶石和火星分别取得下落/上升的
初始线速度与角速度。PhysX 负责质量/惯量、碰撞、接触约束和 24 个固定步的姿态。
这构成可信的**预碎裂刚体爆发**，但没有动态网格切割、破坏阈值、裂纹传播
或拓扑 fracture。渲染器不支持通用 primitive transform，所以生成器把
`PxTransform` 直接烘焙到 rectangle 的世界顶点/法线、cylinder 的端点、
disk 的中心/法线与 sphere 的中心。

静态圣殿不需要进入 PhysX：黑石柱、破损穹顶、祭坛、符文和右侧池体按设计
直接生成。水池的波面由 SpectralDock `water_surface` 解析求交，并用 RGB
Beer 吸收表现深度渐变；它不是 PhysX 粒子、FLIP/SPH 或流体求解。三段
发光 flame 构成祭坛火焰，两段近黑高吸收 flame 代理烟，一段低密度冷色
flame 代理破晓光柱；这些体积只有吸收与自发光，没有散射、流体输运或燃烧
化学。冷色 directional 和四盏由可见符文标示的 cyan point 与火光形成
冷暖对比。低发光神光体积的轴线上另放置 30 颗不发光的金色 dust sphere，
让 directional 与火光照出离散尘点；一个 `oracle_core_emitter` sphere 随
第 5 个 PhysX 复合齿轮移动。核心和火星都是可见 emitter 几何，不加入显式
灯数组。靠近破口的冰晶外观由 12 个半径 0.11–0.20、大小与位置不规则且
彼此分离的 sphere 构成，使用 `frost_ice` 冷色粗糙 metal
（`base_color: [0.65, 0.82, 0.95]`、
`roughness: 0.42`）。它们是非透明视觉代理，不是 dielectric 冰晶。

最初的 dielectric 方案能表达透射外观，但在含 `water_surface` 的高样本
诊断中，稀有近切线路径仍会触发介质栈安全错误。项目没有修改渲染器或放宽
正式 stats 的 `medium_errors == 0` 安全门，而是保留冰晶轮廓和冷色反光、
明确改用不进入介质栈的粗糙金属代理。physics sidecar 以
`opaque_frost_visual_proxy: true` 记录这项边界。

封面检查器同时验证 PhysX 版本/commit、GPU-only flags、seed、`dt`、步数、
130 个 actor 的类别与顺序、有限姿态/速度、六位小数与无负零、无明显穿透
或越界、四象限径向展开、角度与 sleeping 状态，以及上述灯光、六个 flame、
解析水池、12 个半径 0.11–0.20、尺寸不规则且不相交的非透明粗糙金属冰晶
外观代理、
`opaque_frost_visual_proxy: true`，以及材质和 4K render defaults 的精确
场景契约。解析 object 总量采用不超过 450 的教学预算；最终实际数量必须从
同次渲染 stats 读取，而不是把预算上限当作 object 计数。

## 可复现性与安全门

PhysX GPU 模式不支持 enhanced determinism；sidecar 必须记录
`enhanced_determinism=false` 与 GPU 不支持原因。固定 seed、步长、步数以及
actor 创建/导出顺序约束输入和结构，但 GPU 接触生成与并行求解顺序仍可能
使同一设备的最终姿态不同。因此项目不承诺同机或跨 GPU、驱动、CUDA、
PhysX、编译器和操作系统的逐字节一致。

维护者重建记录时应完成：

1. 对两个物理场景分别使用 `--verify`，确认两份独立 scene/sidecar 都通过
   各自契约；允许姿态不同。
2. 先渲染低分辨率 preview，人工检查构图、穿透、越界、材质方向和代理
   边界；封面还要检查碎片径向层次、火焰可读性、水池与冷暖光。
3. 在 RTX 5090 运行低分辨率 Compute Sanitizer，再重建 final；核对 PNG、
   stats 与 physics sidecar 属于同一次命令。
4. 封面 stats 必须报告有效 water/volume 工作量，且 majorant violation、
   tracking overflow、water solver overflow 与 medium error 均为 0。
5. 确认 `scenes/generated/` 仍未被 Git 跟踪，八个静态场景批处理仍不启动
   PhysX。

Host-only CI 只测试检查器及合成契约，不运行 PhysX、OptiX 或像素渲染。
正式物理验收必须在具备 NVIDIA GPU、PhysX 镜像和 OptiX SDK 的机器完成。

## 许可与边界

`docs/gallery/kinetic-foundry.png` 与
`docs/gallery/lava-temple-oracle.png` 属于 CC0-1.0 视觉资产。C++ 生成器、
Python 检查器、临时 scene、渲染 stats 与 `.physics.json` 均按 Apache-2.0
提供。PhysX 保持其上游 BSD-3-Clause 许可，且 SDK、源码构建产物与容器镜像
不随仓库分发。

NVIDIA、CUDA、OptiX、PhysX 和 RTX 是 NVIDIA Corporation 的商标或注册
商标；SpectralDock 是独立的非官方项目，与 NVIDIA Corporation 无隶属
关系，也未获得其赞助或背书。
