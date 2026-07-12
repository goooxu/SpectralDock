# SpectralDock v0.1 发布检查清单

这是一份顺序清单。第一节是硬性门槛：在权利确认完成前，不得把项目上传到任何 GitHub 仓库，包括私有仓库。

## 1. 权利与授权硬门槛

- [ ] 确认个人拥有代码、文档、场景、SVG、生成器和视觉资产的完整授权权利，或已取得雇主/组织明确的书面发布许可。
- [ ] 保存权利确认或书面许可的可审计记录。
- [ ] 确认所有拟发布内容均可按仓库声明的 Apache-2.0、CC0-1.0 或第三方许可证分发。
- [ ] 在以上项目全部完成前，不上传、推送、镜像或备份到任何 GitHub/远程仓库；私有仓库也不例外。

## 2. 名称、许可与归属

- [ ] 检索 `SpectralDock` 及近似名称在 GitHub、常用软件包注册表和主要商标数据库中的使用情况，并保存检索日期与结果。
- [ ] 复核根目录 `LICENSE`、`NOTICE`、第三方归属和 tinyobjloader MIT 文本。
- [ ] 确认代码、文档、场景、SVG 和生成器按 Apache-2.0 发布。
- [ ] 确认吉祥物 OBJ/manifest、为本项目生成的纹理和 gallery PNG 的 CC0-1.0 范围清晰，且没有把 Python 生成器误列入 CC0。
- [ ] 确认 AI 纹理说明、C2PA/sidecar 记录、按现状提供和不保证唯一性的声明完整。
- [ ] 确认 NVIDIA、CUDA、OptiX、PhysX、RTX 商标归属及非官方、无隶属或背书关系的声明完整。
- [ ] 确认 PhysX 5.8.0 的 BSD-3-Clause 来源、固定 tag/commit 与仓库外部依赖边界记录完整。

## 3. 内容与公开环境卫生

- [ ] 确认旧项目名称的三种大小写形式和旧 include/脚本路径在拟发布文件中为零。
- [ ] 扫描并移除个人绝对路径、用户名、内网 IP、主机名、临时凭据和内部基础设施名称。
- [ ] 再次运行凭据/密钥扫描，并人工复核扫描结果。
- [ ] 确认 CUDA、OptiX、PhysX 和其他外部 SDK 或构建产物未进入仓库。
- [ ] 确认仓库总量低于 20 MiB，没有需要 Git LFS 的文件。
- [ ] 检查 `.gitignore`、`.dockerignore` 和 `.gitattributes`；确认 `build/`、`output/`、`reports/` 不会进入提交。
- [ ] 确认五个内置场景仍引用同一个 `assets/examples/models/capsule-mascot.obj`，场景名、schema、CLI 和 gallery 路径未意外变化。
- [ ] 确认 `scenes/generated/kinetic-foundry.json` 未被跟踪；gallery 中仅保留 Kinetic Foundry 的 PNG、stats 和 `.physics.json`。

## 4. Host-only CI 与确定性

- [ ] 在 Ubuntu 24.04、关闭 GPU 构建的环境运行 shell 检查、CMake、CTest 和全部 pytest。
- [ ] 确认 host-only CI 不构建 `spectraldock` 或 PhysX 场景生成器、不渲染图像，不把它宣传为 CPU renderer 或 GPU 验收。
- [ ] 确认吉祥物生成器输出与提交的 OBJ/manifest 一致。
- [ ] 确认 Harbor 生成器输出与提交场景一致且非重叠检查通过。
- [ ] 确认 GitHub Actions 使用固定主版本，且标准托管 runner 不宣称 GPU 验收。

## 5. 建立干净仓库

仅在第 1 节全部完成后执行：

- [ ] 在装有现代 Git 和 `gh` 的干净环境中初始化新仓库；不要沿用当前异常的旧 `.git` 工作环境或其历史。
- [ ] 将默认分支设为 `main`。
- [ ] 设置仅作用于本仓库的 GitHub noreply 提交邮箱，并核对作者信息。
- [ ] 在第一次提交前逐项检查 staged 文件、权限位和体积。
- [ ] 在 GitHub 创建名为 `spectraldock` 的空私有仓库，不自动添加 README、许可证或 `.gitignore`。
- [ ] 推送 `main`，等待现有 `CPU CI / Ubuntu 24.04 CPU` host-only 检查全部通过；完成公开前检查后再转为 public。

## 6. GitHub 保护设置

- [ ] 启用 push protection。
- [ ] 启用 secret scanning。
- [ ] 为 `main` 配置分支保护，并保留现有 `CPU CI / Ubuntu 24.04 CPU` host-only required check 名称。
- [ ] 启用私有漏洞报告。
- [ ] 核对仓库可见性、Actions 权限和默认分支设置。

## 7. 按需 PhysX 场景验收

- [ ] 确认专用镜像固定到 PhysX tag `110.0-omni-and-physx-5.8.0`、commit `fc1018a3745664a1db2b95ce03fb5e91eb585f2e`，且不把下载的 SDK 源码或二进制复制进仓库。
- [ ] 在同一测试机、设备和软件栈使用 `--verify` 连续生成两次；运行 `tools/check_physx_scene.py`，确认两份 scene JSON 与两份 metadata sidecar 分别逐字节一致。
- [ ] 确认 sidecar 明确记录 PhysX GPU backend、设备、seed、固定步长、步数、scene flags、actor 数和场景摘要，并记录 `enhanced_determinism=false` / GPU 不支持。
- [ ] 人工检查物体没有明显穿透、飞散、悬空或落出构图；不把同机双生成结果描述为跨 GPU、驱动、PhysX 版本或平台的确定性保证。
- [ ] 更新 `kinetic-foundry.png`、`.stats.json` 和 `.physics.json`，并再次确认临时场景 JSON 未跟踪。

## 8. RTX 5090 最终验收

- [ ] 在 Linux、CUDA 13.3、OptiX 9.1、RTX 5090 上完成 Release clean build。
- [ ] 完成 Debug clean build 与 OptiX validation。
- [ ] 完成 MIS 对照。
- [ ] 完成 Compute Sanitizer memcheck、initcheck、racecheck。
- [ ] 验证 mesh composite 的 RTX 5090 定向 golden。
- [ ] 检查五个内置场景预览；需要更新正式 gallery 时，以 `--preset final` 生成并逐张核对 PNG 与 stats。
- [ ] 检查 Kinetic Foundry 的正式 PNG、渲染 stats 和 PhysX sidecar 三者同 stem 且内容对应。
- [ ] 确认没有把 RTX 5090 结果描述为跨 GPU golden 或性能保证。

## 9. 发布 v0.1.0

- [ ] 删除或确认未跟踪 `build/`、`output/`、`reports/` 及其他临时产物。
- [ ] 在最终提交上重新运行凭据扫描、仓库体积检查和 host-only CI。
- [ ] 确认发布说明明确唯一完整验证平台与已知限制。
- [ ] 创建并推送源码标签 `v0.1.0`。
- [ ] 创建 source-only GitHub Release；不附加二进制、容器镜像、CUDA SDK、OptiX SDK 或 PhysX SDK。
- [ ] 最后复核 public 可见内容、许可证识别、保护设置和下载附件。
