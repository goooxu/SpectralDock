# 实施与验收状态

更新时间：2026-07-11。

## 已完成实现

- schema v2、OBJ 三角化/负索引/group 合并、法线/UV 处理和清晰错误信息，并保持 schema v1 兼容。
- mesh 资源级共享压缩 GAS、IAS 对象变换、对象级 SBT/材质/alpha、真实几何正反面和插值着色法线。
- 设备端 RR/MIS 保持局部 PDF 记账与吞吐量补偿分离；末端深度只为真实存在的竞争策略分配权重。
- 固定 seed Harbor 生成器、五个内置场景共享吉祥物、preview/final 批量接口，以及包含几何、显存、时序和吞吐数据的 stats 输出。
- 独立的 PhysX 5.8.0 GPU 刚体生成流程；Kinetic Foundry 只保留正式 PNG、渲染 stats 和物理生成 sidecar，不提交临时场景 JSON。
- OBJ/schema/变换与输入语义测试、吉祥物及 Harbor 确定性测试、五个内置场景一致性测试、GPU MIS 对照和共享 mesh fixture。

## 验证范围

v0.1 的完整验证范围仅为：

- Linux 主机；
- Ubuntu 24.04 容器；
- CUDA 13.3；
- OptiX 9.1；
- NVIDIA GeForce RTX 5090（compute capability 12.0）。

Kinetic Foundry 另使用基于 CUDA 12.8.1、固定到 PhysX 5.8.0 源码版本的专用镜像生成。PhysX GPU 模式不支持 enhanced determinism；物理快照只通过固定步长、固定 actor 创建/导出顺序和同机双生成比较验收，不能据此宣称跨 GPU、驱动、PhysX 版本或平台逐字节一致。

没有在 Windows、多 GPU、其他 NVIDIA GPU 或其他 CUDA/OptiX 组合上完成同等级验收。gallery、性能数据和 mesh 像素 golden 都只记录上述 RTX 5090 环境，不能视为跨 GPU golden 或兼容性承诺。

## 自动 host-only 验收

`./scripts/test.sh` 不要求 GPU、OptiX SDK 或 PhysX，负责：

- 所有 shell 脚本的语法检查；
- `SPECTRALDOCK_ENABLE_GPU=OFF` 的 host-only CMake 构建；
- CTest；
- 全部 Python 测试，包括吉祥物和 Harbor 生成器的确定性检查。

该配置只构建 core 与测试 target，不生成 `spectraldock` 渲染可执行文件，也不执行像素渲染。标准 GitHub 托管 runner 只承担这组 host-only 验收，不承担 GPU 正确性、性能或 sanitizer 结论，也不提供 CPU reference renderer 结论。

PhysX 生成器由 `SPECTRALDOCK_ENABLE_PHYSX_SCENE=ON` 的独立构建启用，默认构建和 host-only CI 均保持关闭。`scripts/generate-physx-scene.sh` 输出到被忽略的 `scenes/generated/`；维护者使用 `tools/check_physx_scene.py` 检查临时场景和 sidecar，再通过独立渲染入口更新 Kinetic Foundry 的三件 gallery 记录。具体流程见 [PhysX 场景说明](PHYSX_SCENE.md)。

## RTX 5090 手工 GPU 验收

维护者在上述唯一完整验证平台上手工执行：

- 官方 OptiX SDK `optixHello`；
- Release 与 Debug clean build，Debug 默认启用 OptiX validation；
- 64×64、4 spp、depth 1、seed 1 的绑定/未绑定灯 MIS 对照；
- Compute Sanitizer 的 memcheck、initcheck 和 racecheck；
- mesh composite fixture 的 UV、平滑法线、alpha、共享 GAS 双实例、几何统计和 RTX 5090 定向像素 golden；
- 五个内置正式场景的预览检查，以及 Kinetic Foundry 的独立生成、验证和预览检查；发布前再执行一次完整 RTX 5090 验收。

`./scripts/acceptance.sh` 编排环境检查、Release/Debug 构建、host-only C++/Python 测试、MIS GPU 对照和 mesh GPU fixture。它不生成 PhysX 场景，不自动更新 gallery 图片，也不执行跨 GPU golden 或性能阈值判断。

六张 1920×1080 gallery PNG 及对应 stats 是正式 RTX 5090 运行记录。`./scripts/render-examples.sh --preset final` 只更新五个内置场景；Kinetic Foundry 由独立脚本更新，并额外保留 `.physics.json`。这些受版本控制的记录只供维护者在正式验收时更新；普通内置预览写入 `output/examples/`。

发布门槛与仓库公开步骤见[发布检查清单](RELEASE_CHECKLIST.md)。
