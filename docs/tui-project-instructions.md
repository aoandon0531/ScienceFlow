# TUI project instructions

Place a UTF-8 `AGENTS.md` in the project and start a new session with its working directory.

```bash
uv run scienceflow tui --workspace /path/to/project
```

In a Git project, ScienceFlow loads `AGENTS.md` from the nearest Git root down to the selected workspace, in that order. More specific directory guidance takes precedence within its scope. A non-Git workspace loads only its own file.

The existing system prompt is preserved. Loaded instructions include their source paths and SHA256 digests and are saved as a session snapshot. Resuming a session preserves that snapshot. Start a new session to load updated files.

Missing or empty files are skipped. Invalid UTF-8, unreadable files, links outside the project root, and combined content larger than 32768 bytes produce a startup error. Links to the same source file are deduplicated.

## Task-specific generation

Starting `/long-research TASK` automatically creates instructions in the allocated task workspace at `.scienceflow/task-instructions/<instance-id>/AGENTS.md`. For example, `/long-research leaf-classification` generates instructions from the registered task package before requesting missing dataset and resource settings.

The generated file records the objective, artifact, metric, compute budget and description sources. Documented task objectives, evaluation requirements, submission formats and implementation constraints are promoted into a task-specific requirements section. The complete task evidence is retained. Unresolved settings are labeled explicitly.

Accepted preparation changes regenerate the managed block. The TUI reports its path and SHA256 digest. Manual guidance outside the marked block is retained, and content versions are saved under the adjacent `versions/` directory. Each task instance has its own directory, including repeated runs of the same benchmark task.

The isolated preparation runtime receives the current instruction content and its digest together. Registered tasks continue to use their package metadata for preparation. Generation follows resolved task facts and does not require an additional model call.

Instruction files have a 32768-byte limit. File locking, atomic replacement and a concurrent-edit check protect updates. An invalid managed block produces a diagnostic so the user can repair it.

Automatic learning from execution failures and adoption of updated instructions by running research workers are later research-resource stages.
