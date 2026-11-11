# TUI 项目指令加载验收

第一阶段让已有 `AGENTS.md` 进入 TUI 首次模型请求。规则随会话保存，并参与原有上下文压缩与恢复流程。

## 使用方式

在目标工作目录创建 UTF-8 编码的 `AGENTS.md`，例如下面的内容。

```markdown
# 项目约定

回答以 SF_STAGE1_AGENTS_OK 开头。
用中文解释结果。
```

从源码启动 TUI，并指定目标工作目录。

```bash
uv run scienceflow tui --workspace /path/to/project
```

对于已经配置本地模型连接的开发环境，也可以使用已有启动器。

```powershell
wsl -d Ubuntu --cd /mnt/f/Experiment/scienceflow -- /home/aoandon/.local/bin/scienceflow-local --workspace /path/to/project
```

输入“请计算 2 加 3，并遵守项目的回答约定”。检查回答是否以约定标记开头。这个标记只写在规则文件中，提问时不提供标记。

启动输出列出加载文件路径及 SHA256 摘要，完整来源、摘要和正文保存在会话的系统消息中。可以要求模型说明本次采用的项目约定。

## 第一阶段的规则

- Git 项目从最近的 Git 根目录加载到 `--workspace` 指定目录，支持 `.git` 目录和 worktree 的 `.git` 文件。
- 普通目录只加载自身的 `AGENTS.md`，子目录规则按从父到子的顺序排列。兄弟目录及当前工作目录下更深层的规则不会自动载入。
- 通过符号链接指向同一个源文件的规则去重，逃出项目根目录的链接报告错误。
- 文件缺失或为空时正常启动。编码错误、读取失败和总计超过 32768 字节时显示可定位错误，停止本次启动。
- 保留用户显式传入的 `--system-prompt`，随后附加项目约定。
- 新会话固定一份规则快照。修改文件后，新会话读取新内容；`--resume` 继续使用该会话保存的版本，包括压缩后的检查点。
- 没有加载规则的旧会话恢复后也继续使用原来的系统消息。需要采用新规则时启动新会话。
- 本阶段仅识别 `AGENTS.md`。自动生成、任务切换、在线刷新和查看命令属于后续阶段。

## 自动验证

```bash
python -m pytest -q tests/test_tui_project_instructions.py tests/test_inquirycraft_cli_composition.py tests/test_tui_sessions.py tests/test_tui_model_config_isolation.py tests/test_user_config_cli.py
```

新测试使用假模型捕获实际发送的请求，覆盖目录作用域、缺失与空文件、UTF-8 BOM、来源摘要、总大小限制、符号链接、无效编码和读取失败。运行时测试同时检查首次注入、自定义系统提示词、压缩后保留、修改文件后的会话快照、恢复旧版本、新会话更新和普通 Agent 入口的兼容性。

真实模型演示属于合成的功能验收。它验证项目指令能否影响回答，研究任务评测在后续 long research 阶段单独进行。

本阶段在 Qwen3-8B 上使用默认 TUI 系统提示词完成了演示。规则文件单独设置回答前缀，提问只要求计算 2 加 3 并遵守项目约定，实际回答为 `SF_STAGE1_AGENTS_OK 两加三等于五。`。

## Git 检查

功能分支为 `feat/task-instructions`，`origin` 指向个人 fork，`upstream` 指向原仓库。提交包含加载逻辑、测试、CI 和本文。提交前检查暂存区内容以及 `git diff --check`。模型配置、连接密钥和会话产物保存在本地，暂存文件逐项指定。
