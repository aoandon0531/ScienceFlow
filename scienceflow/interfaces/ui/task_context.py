"""Replace active task guidance without rewriting the shared conversation."""

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

from inquirycraft.runtime import AgentRuntime

from scienceflow.research.onboarding.support.task_instructions import (
    TaskInstructionSnapshot,
    _atomic_write,
)


class TaskContextRuntime(AgentRuntime):
    """InquiryCraft 0.9.8 host-message adapter, including its budget accounting."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.active_task: TaskInstructionSnapshot | None = None
        self.active_task_title = ""
        self._task_state_path = (
            Path(str(self.options.session_log) + ".instructions.json")
            if self.options.session_log else None
        )
        if self._task_state_path and self._task_state_path.exists():
            try:
                with self._task_state_path.open("rb") as handle:
                    raw = handle.read(262145)
                if len(raw) > 262144:
                    raise ValueError("Active task state exceeds its size limit")
                row = json.loads(raw)
                snapshot = TaskInstructionSnapshot(**{
                    **row["snapshot"], "path": Path(row["snapshot"]["path"])
                })
                self._validate_snapshot(snapshot)
                if not isinstance(row["title"], str) or not 1 <= len(row["title"]) <= 160:
                    raise ValueError("Invalid active task title")
                self.active_task, self.active_task_title = snapshot, row["title"]
            except (OSError, ValueError, TypeError, KeyError) as exc:
                raise ValueError(f"Cannot restore task instructions from {self._task_state_path}: {exc}") from exc

    @staticmethod
    def _validate_snapshot(snapshot: TaskInstructionSnapshot) -> None:
        if not isinstance(snapshot.content, str):
            raise ValueError("Invalid active task instruction content")
        raw = snapshot.content.encode("utf-8")
        if len(raw) > 32768 or sha256(raw).hexdigest() != snapshot.digest:
            raise ValueError("Invalid active task instruction snapshot")

    def activate_task(self, snapshot: TaskInstructionSnapshot, title: str) -> None:
        self._validate_snapshot(snapshot)
        if not isinstance(title, str) or not 1 <= len(title) <= 160:
            raise ValueError("Invalid active task title")
        if self._task_state_path:
            self._task_state_path.parent.mkdir(parents=True, exist_ok=True)
            row = {"snapshot": {**asdict(snapshot), "path": str(snapshot.path)}, "title": title}
            _atomic_write(self._task_state_path, json.dumps(row, ensure_ascii=False))
        self.active_task, self.active_task_title = snapshot, title

    def _ephemeral_message(self):
        # This pinned host hook is included in both provider budget checks and
        # request construction. Task guidance stays outside compacted history.
        host = super()._ephemeral_message()
        if self.active_task is None:
            return host
        text = (
            "Active task instructions for the current request. Earlier tasks remain "
            "conversation history. Apply this snapshot within the current task while "
            "respecting project instructions and the user's latest requirements.\n"
            f"Task: {self.active_task_title}\nSource: {self.active_task.path}\n"
            f"SHA256: {self.active_task.digest}\n\n{self.active_task.content}"
        )
        if host:
            text += "\n\n" + host["content"]
        return {"role": "system", "content": text}
