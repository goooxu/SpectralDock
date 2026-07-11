# 为 SpectralDock 贡献

感谢改进代码、文档、测试、场景或素材。提交前请先开 issue 说明较大的设计变化，并确保贡献中不含凭据、内部路径、未获授权的第三方内容或外部 SDK。

## 开发与测试

1. 从当前分支创建主题分支，保持改动聚焦。
2. 运行 ./scripts/test.sh；它会在不使用 GPU 或 OptiX 的 host-only 容器入口中执行 shell 检查、关闭 GPU 的 CMake、CTest 和全部 pytest。该入口不构建渲染器、不渲染图像，不应称为 CPU renderer 验收。
3. GPU、OptiX、Compute Sanitizer 与像素 golden 由维护者在已记录的 RTX 5090 环境复核。
4. 不要把 build、output、reports 或本地 SDK 加入提交。
5. --preset final 会更新受版本控制的 docs/gallery，仅在维护者明确要求时使用。

## 贡献许可

提交代码、脚本、生成器、文档、场景、SVG 或测试，即表示你有权提交这些内容，并同意按 Apache License 2.0 提供该贡献。

若包含第三方内容，请在 PR 中列出作者、来源、版本、许可证和本地修改；不得仅用链接替代必需的许可证文本。

视觉资产采用更窄的流程。只有在贡献者拥有必要权利并明确作出 CC0 dedication 时，维护者才会接收拟纳入 CC0 范围的 OBJ、manifest、纹理或 gallery PNG。PR 必须明确确认：

> I have the necessary rights and hereby dedicate these visual assets under CC0 1.0 Universal to the extent I hold copyright or related rights.

AI 辅助或生成的视觉资产还必须披露使用的工具、prompt、后处理、最终 SHA-256，以及是否保留 C2PA 或其他来源凭据。CC0 dedication 不构成唯一性、排他性或不侵权保证。

## 提交质量

- 保持场景 schema、CLI 参数和 gallery 路径兼容，除非变更已被明确讨论。
- 新行为应带定向测试；确定性生成器必须与提交产物逐字节一致。
- 不把 RTX 5090 像素 golden 描述为跨 GPU 保证。
- 更新与行为或许可边界直接相关的文档。
