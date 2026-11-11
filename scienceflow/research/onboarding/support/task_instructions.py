"""Store and retrieve task-scoped instruction documents."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
from tempfile import NamedTemporaryFile

from scienceflow.runtime.parallel.control.registry import locked

_START = "<!-- scienceflow:task-instructions:start -->"
_END = "<!-- scienceflow:task-instructions:end -->"
_MAX_BYTES = 32768


@dataclass(frozen=True)
class TaskInstructionSnapshot:
    path: Path
    digest: str
    changed: bool
    content: str


def _atomic_write(path: Path, text: str) -> None:
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def save_task_instructions(
    instance_id: str, workspace: Path, content: str
) -> TaskInstructionSnapshot:
    """Save authored instructions while retaining manual text and content versions."""
    path = task_instruction_path(instance_id, workspace)
    directory = path.parent
    if not content.strip() or _START in content or _END in content or "\x00" in content:
        raise ValueError("Invalid authored task instructions")
    block = f"{_START}\n{content.rstrip()}\n{_END}"
    with locked(directory):
        if path.is_symlink():
            raise ValueError(f"Task instruction file must not be a symlink: {path}")
        before = path.read_text(encoding="utf-8") if path.exists() else ""
        if _START in before or _END in before:
            if before.count(_START) != 1 or before.count(_END) != 1:
                raise ValueError(f"Invalid managed instruction block: {path}")
            start, end = before.index(_START), before.index(_END)
            if end < start:
                raise ValueError(f"Invalid managed instruction block: {path}")
            after = before[:start] + block + before[end + len(_END):]
        else:
            after = before + ("\n\n" if before else "") + block + "\n"
        if len(after.encode("utf-8")) > _MAX_BYTES:
            raise ValueError(f"Task instructions exceed {_MAX_BYTES} bytes: {path}")
        digest = sha256(after.encode("utf-8")).hexdigest()
        if after == before:
            return TaskInstructionSnapshot(path, digest, False, after)
        history = directory / "versions"
        if not history.resolve().is_relative_to(directory.resolve()):
            raise ValueError(f"Instruction history escapes its task directory: {history}")
        history.mkdir(exist_ok=True)
        for text in (before, after):
            if text:
                version = history / f"{sha256(text.encode('utf-8')).hexdigest()}.md"
                if not version.exists():
                    _atomic_write(version, text)
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != before:
            raise ValueError(f"Task instructions changed during generation; retry: {path}")
        _atomic_write(path, after)
    return TaskInstructionSnapshot(path, digest, True, after)


def task_instruction_path(instance_id: str, workspace: Path) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", instance_id):
        raise ValueError("Invalid task instruction instance ID")
    root = Path(workspace).resolve()
    directory = root / ".scienceflow" / "task-instructions" / instance_id
    if not directory.resolve().is_relative_to(root):
        raise ValueError("Task instruction directory escapes the task workspace")
    return directory / "AGENTS.md"


def read_task_instructions(instance_id: str, workspace: Path) -> TaskInstructionSnapshot | None:
    path = task_instruction_path(instance_id, workspace)
    if path.is_symlink():
        raise ValueError(f"Task instruction file must not be a symlink: {path}")
    try:
        with path.open("rb") as handle:
            raw = handle.read(_MAX_BYTES + 1)
    except FileNotFoundError:
        return None
    if len(raw) > _MAX_BYTES:
        raise ValueError(f"Task instructions exceed {_MAX_BYTES} bytes: {path}")
    return TaskInstructionSnapshot(path, sha256(raw).hexdigest(), False, raw.decode("utf-8"))
