# TUI project instructions

Place a UTF-8 `AGENTS.md` in the project and start a new session with its working directory.

```bash
uv run scienceflow tui --workspace /path/to/project
```

In a Git project, ScienceFlow loads `AGENTS.md` from the nearest Git root down to the selected workspace, in that order. More specific directory guidance takes precedence within its scope. A non-Git workspace loads only its own file.

The existing system prompt is preserved. Loaded instructions include their source paths and SHA256 digests and are saved as a session snapshot. Resuming a session preserves that snapshot. Start a new session to load updated files.

Missing or empty files are skipped. Invalid UTF-8, unreadable files, links outside the project root, and combined content larger than 32768 bytes produce a startup error. Links to the same source file are deduplicated.

This version supports existing `AGENTS.md` files. Task-specific generation and live refresh are planned for a subsequent stage.
