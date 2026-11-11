# TUI project instructions

Place a UTF-8 `AGENTS.md` in the project and start a new session with its working directory.

```bash
uv run scienceflow tui --workspace /path/to/project
```

In a Git project, ScienceFlow loads `AGENTS.md` from the nearest Git root down to the selected workspace, in that order. More specific directory guidance takes precedence within its scope. A non-Git workspace loads only its own file.

The existing system prompt is preserved. Loaded instructions include their source paths and SHA256 digests and are saved as a session snapshot. Resuming a session preserves that snapshot. Start a new session to load updated files.

Missing or empty files are skipped. Invalid UTF-8, unreadable files, links outside the project root, and combined content larger than 32768 bytes produce a startup error. Links to the same source file are deduplicated.

## Task-specific generation

The local prototype uses the selected model to author complete Markdown instructions for both ordinary TUI tasks and `/long-research` preparation. The author chooses the document structure for the task and its materials.

For ordinary idle chat submissions, a short model call identifies explicit task starts, switches and requirement updates. Continuation questions keep the current task. A new task receives its own instruction file. An update replaces the current task's authored section. The ordinary conversation remains shared.

For `/long-research`, the author receives task materials and confirmed onboarding facts. Changed facts trigger a new document; unchanged facts reuse the existing version. Referenced local text materials are supplied as bounded raw text, independent of their section structure. Additional workspace text can be read with tools. Missing information must be marked for clarification.

Instructions are saved at `.scienceflow/task-instructions/<instance-id>/AGENTS.md` under the task workspace. The TUI reports the path and digest. Manual guidance outside host markers is retained, and content versions are kept beside the file. Active task instructions are projected into requests separately from shared factual history, counted against the input budget, and restored from a session-side snapshot after restart.

The host validates intent responses, text size and control markers. For confirmed research facts, the model must include an exact JSON facts block within its Markdown. A failed generation or check is fed back for one correction. A second failure keeps the previous active version and displays the reason. Format and supplied-fact checks are automatic. Task strategies are part of document review.

Ordinary submissions incur an intent-check model call. Task creation and updates additionally call the author. These calls use temperature zero. While authoring is active, finish or cancel it before sending another ordinary request.

Instruction files have a 32768-byte limit. File locking, atomic replacement and a concurrent-edit check protect updates. An invalid managed block produces a diagnostic so the user can repair it.

Automatic learning from execution failures and adoption of updated instructions by running research workers are later research-resource stages.

The prototype targets InquiryCraft 0.9.8. Its runtime adapter overrides the pinned host-message projection hook so active task text participates in both budget checks and request construction without rewriting conversation or compaction checkpoints. Embedded research hosts need to supply a preparation runtime factory for model authoring.
