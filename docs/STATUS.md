# 实施与验收状态

更新时间：2026-07-11。

## 已完成实现

- schema v2、OBJ 三角化/负索引/group 合并、法线/UV 处理和清晰错误信息，并保持 schema v1 兼容。
- mesh 资源级共享压缩 GAS、IAS 对象变换、对象级 SBT/材质/alpha、真实几何正反面和插值着色法线。
- 设备端 RR/MIS 保持局部 PDF 记账与吞吐量补偿分离；末端深度只为真实存在的竞争策略分配权重。
- 固定 seed Harbor 生成器、五场景共享吉祥物、preview/final 批量接口，以及包含几何、显存、时序和吞吐数据的 stats 输出。
- OBJ/schema/变换与输入语义测试、吉祥物及 Harbor 确定性测试、五场景一致性测试、GPU MIS 对照和共享 mesh fixture。

## 验证范围

v0.1 的完整验证范围仅为：

- Linux 主机；
- Ubuntu 24.04 容器；
- CUDA 13.3；
- OptiX 9.1；
- NVIDIA GeForce RTX 5090（compute capability 12.0）。

没有在 Windows、多 GPU、其他 NVIDIA GPU 或其他 CUDA/OptiX 组合上完成同等级验收。gallery、性能数据和 mesh 像素 golden 都只记录上述 RTX 5090 环境，不能视为跨 GPU golden 或兼容性承诺。

## 自动 host-only 验收

`./scripts/test.sh` 不要求 GPU 或 OptiX SDK，负责：

- 所有 shell 脚本的语法检查；
- `SPECTRALDOCK_ENABLE_GPU=OFF` 的 host-only CMake 构建；
- CTest；
- 全部 Python 测试，包括吉祥物和 Harbor 生成器的确定性检查。

该配置只构建 core 与测试 target，不生成 `spectraldock` 渲染可执行文件，也不执行像素渲染。标准 GitHub 托管 runner 只承担这组 host-only 验收，不承担 GPU 正确性、性能或 sanitizer 结论，也不提供 CPU reference renderer 结论。

## RTX 5090 手工 GPU 验收

维护者在上述唯一完整验证平台上手工执行：

- 官方 OptiX SDK `optixHello`；
- Release 与 Debug clean build，Debug 默认启用 OptiX validation；
- 64×64、4 spp、depth 1、seed 1 的绑定/未绑定灯 MIS 对照；
- Compute Sanitizer 的 memcheck、initcheck 和 racecheck；
- mesh composite fixture 的 UV、平滑法线、alpha、共享 GAS 双实例、几何统计和 RTX 5090 定向像素 golden；
- 五个正式场景的预览检查；发布前再执行一次完整 RTX 5090 验收。

`./scripts/acceptance.sh` 编排环境检查、Release/Debug 构建、host-only C++/Python 测试、MIS GPU 对照和 mesh GPU fixture。它不自动更新五张正式 gallery 图片，也不执行跨 GPU golden 或性能阈值判断。

五张 1920×1080 gallery PNG 及对应 stats 是一次正式 RTX 5090 运行记录。`./scripts/render-examples.sh --preset final` 会直接更新这些受版本控制的文件，只供维护者使用；普通预览写入 `output/examples/`。

发布门槛与仓库公开步骤见[发布检查清单](RELEASE_CHECKLIST.md)。
