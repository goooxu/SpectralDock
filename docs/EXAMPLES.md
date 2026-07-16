# 示例画廊：十个可直接执行的 Python 程序

每幅图都对应 `scenes/` 下一个普通 Python 程序。程序通过 SpectralDock API
构造内容，并在 `render()` 调用中明确给出分辨率、采样数与 `output/` 路径；
渲染器不会接收或解释所谓“场景文件”。两个物理示例还会在同一程序中显式
运行 PhysX，再把当次结果交给 OptiX。本页正式 gallery PNG 是已经验收的
RTX 5090 运行记录，普通示例执行不会覆盖它们。

## Lava Temple Oracle / 熔岩圣殿的机械先知（PhysX 封面）

![熔岩圣殿的机械先知](gallery/lava-temple-oracle.png)

这是项目的 3840×2160 封面场景：破损黑石圣殿中央，一具由 70 个预先分离刚体构成的机械先知在爆发后 0.2 秒凝固于半空；连同 12 块坍塌顶石和 48 颗火星，物理场景共有 130 个动态 actor。24 块深灰外壳板以成对的外侧/内侧 rectangle 暴露金色断面，面罩、眼部、肢体、天线、复合齿轮、连杆、铜金碎片、顶石与火星共同形成径向、四象限展开的时间切片。直接执行 `scenes/lava-temple-oracle.py` 时，程序会先在 PhysX 5.8.0 GPU 上以 `1/120 s` 固定步长运行 24 步，再由 `PhysicsResult.apply_to(renderer)` 把当次位置和姿态应用到 sphere、cylinder、disk 与 rectangle 附件；它是**预碎裂刚体爆发**，不是运行时拓扑 fracture。

三段白炽到橙红的 flame 从祭坛向上照亮断口，一束冷色 directional 从坍塌穹顶切入，四盏辅助 cyan point 由可见符文几何标示；两段近黑吸收体积代理烟层，一段低密度冷色 flame 代理可见神光。封面共使用六个 flame 体积，但没有通用散射、烟流或大气模型。右侧水池是 SpectralDock 的有限解析 `water_surface`，以 RGB Beer 吸收形成由浅至深的幽蓝渐变；它不是 PhysX 流体。穹顶附近 12 个半径 0.11–0.20、大小与位置不规则且互不相交的 sphere 使用冷色粗糙金属形成冰晶外观，明确是不透明视觉代理而非 dielectric 冰；这是因为含解析水面时，dielectric sphere 在高样本近切线路径上会出现稀有介质栈安全错误。粗糙黑石、金铜机械件、水、火与冷光共同展示两个 GPU 子系统在清晰边界上的组合，而不是把物理与路径追踪混称为同一个运行时。

30 颗不发光的金色 dust sphere 沿神光轴不规则散布，用受光亮点加强光束读形；一个蓝色 `oracle_core_emitter` sphere 随第 5 个 PhysX 复合齿轮姿态移动，但与火星一样只是可见 emitter 几何，不注册为显式灯。

正式配置固定为 3840×2160、2048 spp、depth 12、seed 909、AI Denoiser、direct clamp 64 与 indirect clamp 16。仓库只保存同 stem 的正式 PNG、渲染 stats 和当次 physics sidecar；物理与渲染在 Python 层的 typed API 边界汇合，worker 内部只使用随 `TemporaryDirectory` 删除的 private `.sdp` IPC，不生成持久场景中间文件。

## Material Cathedral

![Material Cathedral](gallery/material-cathedral.png)

三个胶囊吉祥物实例共享一份 5,816-triangle GAS，分别使用陶瓷、粗糙金属和玻璃。封闭建筑、矩形主光与圆盘补光用于观察 GGX、Fresnel、MIS、色彩反弹和 `T * Rz * Ry * Rx * S` 实例变换。

## Radiance Pavilion

![Radiance Pavilion](gallery/radiance-pavilion.png)

开放式海岸 look-dev 展台以胶囊吉祥物为中央展品，四件户外观测装置沿非对称弧线展开：漫反射陶土风向标、粗糙青铜日晷、光滑铬抛物面日光镜和玻璃双透镜观测仪。场景没有 emitter，也没有任何显式灯；2048×1024 的程序化 Radiance RGBE 日落海岸环境是唯一光源。环境贴图包含低角度金色夕阳、暖色分层云、冷色天顶、暗青海面、太阳反光带与远岛剪影，使各向异性的高动态热点和大范围天空补光同时出现在背景与材质响应中。Python 程序通过 `renderer.integrator(direct_light_sampling="importance")` 按线性亮度与 texel 立体角选择方向，并与 BSDF 采样进行 MIS，用这个唯一光源直观展示重要性采样如何减少样本浪费。正式配置固定为 1920×1080、512 spp、depth 12、seed 909，并启用 AI Denoiser。

## Neon Koi

![Neon Koi](gallery/neon-koi.png)

透明锦鲤剪影、纹理 emitter、青/洋红面积光、无文字电路墙和湿润金属地面围绕一个深色金属胶囊吉祥物，集中展示 alpha any-hit、图像纹理、共享网格、彩色间接光、景深和 AI 降噪。

## Celestial Archive

![Celestial Archive](gallery/celestial-archive.png)

青铜胶囊吉祥物作为中央展品，配两颗为本项目生成的 2:1 纹理星球、玻璃天体、天空渐变与太阳瓣，展示网格实例、球面 UV、天空照明和反射折射。

## Reflector Laboratory

![Reflector Laboratory](gallery/reflector-laboratory.png)

白色陶瓷胶囊吉祥物置于两面抛物面反射器之间。可见 rectangle 顶灯提供柔和主光，左侧暖色 point 位于反射器焦点附近，冷色 directional 从固定无限远方向形成平行轮廓光；后两者不可见并产生硬阴影。场景同时展示自定义抛物面交点、单面材质、常用 delta 灯的逐灯 NEE，以及默认 direct 64 / indirect 16 钳位对尖锐金属高光离群值的控制。

## Benchmark Harbor

![Benchmark Harbor](gallery/benchmark-harbor.png)

“泡泡海上的吉祥物船队”由 16 个四色胶囊吉祥物实例共享一份 5,816-triangle GAS，并由固定 seed `20260707` 生成 1,024 个互不重叠的球形波浪。该场景覆盖大 IAS、确定性生成、BVH 构建和吞吐率。

## Ember Forge

![Ember Forge](gallery/ember-forge.png)

深夜封闭锻造工坊采用电影化的低机位三分之四构图：砖砌锻炉位于左侧视觉焦点，胶囊 mascot 作为铁匠站在铁砧与灼热工件之后，烟罩、工具架、风箱、淬火桶、钢材和梁柱填充纵深。单座炉火由 Python 程序添加的三段相互重叠程序化异质吸收—自发光体积构成：宽而明亮的炉芯、向上收尖的主火舌与轻微偏轴的副火舌；它们使用线性 RGB 轴向渐变、Delta Tracking 和体积 NEE，并非黑体、CFD、烟雾或动画。环境为纯黑，场景没有 emitter、面积灯或隐藏补光，全部可见照明只来自这组三段 flame；浅色耐火砖与中等反照率的粗糙金属通过直接光和间接反弹呈现暖色明暗层次。正式图固定为 2048 spp、depth 12、无 Denoiser，并使用展示场景默认的有偏贡献钳位；检查原始 Monte Carlo 长尾时应在 `integrator()` 或 `render()` 中显式将两个 clamp 设为 0。

## Moonlit Stepwell

![Moonlit Stepwell](gallery/moonlit-stepwell.png)

月光阶井用 rectangle、disk、cylinder 和同一 mascot OBJ 搭建石阶、池底、墙体与立柱。中央 `renderer.object(type="water_surface", ...)` 是四项确定性解析波浪的有限高度场，并在解析宏观法线上叠加 `roughness=0.12` 的 GGX 微表面：反射与折射使用精确介电 Fresnel、Smith 遮蔽、可见法线采样和 MIS，有限灯、flame、delta 灯与 HDR 环境都能在当前粗糙水面顶点执行 NEE；介质栈和 RGB Beer 吸收负责水下传播。为了不让水面这个视觉主体反而成为最慢收敛的部分，BSDF 以实际 PDF 补偿的方式把反射分支概率提高到至少 50%；有限灯在每个水面顶点分别取得一份全局功率样本和一份均匀索引样本，以二者的联合灯 PDF 与 BSDF 命中组成三技术 balance MIS，同时照顾月光和弱水下灯。所有球外连续 BSDF 顶点选中单面 sphere 灯时都均匀采其可见立体角；月盘本身是 disk，仍按灯面采样。场景固定 seed 808，以月盘粗糙反射、池底折射位移、深水蓝绿色选择性吸收和水下照明展示运行时水传输；它不是流体模拟，也不包含泡沫、动画、MNEE、光滑多界面焦散求解或 motion blur。正式图固定为 512 spp、depth 12，并启用 OptiX AI Denoiser；正式图使用有偏贡献钳位，维护者的线性 PFM 均值/收敛对照必须调用 `render(denoise=False, clamp_direct=0, clamp_indirect=0, linear_output=...)`。

## Kinetic Foundry（PhysX）

![Kinetic Foundry](gallery/kinetic-foundry.png)

该按需场景使用 PhysX 5.8.0 GPU 刚体模拟 24 个采用 capsule 碰撞代理的吉祥物与 192 颗钢珠，并在固定第 300 步（2.5 秒）截取撞击峰值；正式归档 sidecar 的聚合字段记录 `sleeping_dynamic_actors=0`，当前 API 则在每个 body 上记录 `sleeping`，validator 同样要求这些动态 actor 都未休眠。SpectralDock/OptiX 渲染的是这一时刻清晰的静态单帧，不含 motion blur，不应解读为系统的最终静止状态。仓库只保留正式 PNG、渲染 stats 和同 stem 的 `.physics.json` 运行记录，不存在可复用的中间场景文件。PhysX 不参与路径追踪，也不会成为运行八个静态程序时的依赖；`scenes/kinetic-foundry.py` 与封面程序分别直接调用同一套 `PhysicsWorld` API。复现边界见 [PhysX 场景说明](PHYSX_SCENE.md)。

## 运行

```bash
source ./scripts/activate.sh Release

# 每个程序自己指定输出、分辨率和采样参数
python3 scenes/neon-koi.py
python3 scenes/radiance-pavilion.py
python3 scenes/kinetic-foundry.py
python3 scenes/lava-temple-oracle.py

# 依次直接执行十个程序
./scripts/render-examples.sh
```

所有示例都在自己的 `render()` 调用中显式使用 direct 64 / indirect 16
钳位。Radiance Pavilion 使用 512 spp、depth 12 与 AI 降噪；Ember Forge 使用
2048 spp、depth 12、无降噪；Moonlit Stepwell 使用 512 spp、depth 12 与 AI
降噪。没有全局 preset；改变质量或输出位置就是修改或复用普通 Python API
调用。两个 PhysX 程序每次执行都重新运行 GPU 模拟，不支持跳过或复用旧姿态。

正式静态几何统计和 RTX 5090 数据见 [BENCHMARK.md](BENCHMARK.md)。图像/模型来源与 CC0 使用条件见 [ASSETS.md](ASSETS.md)。
