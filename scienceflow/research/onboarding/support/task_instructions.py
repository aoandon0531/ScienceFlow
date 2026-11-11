"""Generate task-scoped instructions from resolved onboarding facts."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING

from scienceflow.runtime.parallel.control.registry import locked

if TYPE_CHECKING:
    from scienceflow.research.onboarding.session import LongResearchDraft

_START = "<!-- scienceflow:task-instructions:start -->"
_END = "<!-- scienceflow:task-instructions:end -->"
_MAX_BYTES = 32768


@dataclass(frozen=True)
class TaskInstructionSnapshot:
    path: Path
    digest: str
    changed: bool
    content: str


def _task_requirements(task_text: str) -> str:
    """Promote documented requirements without inferring a new task contract."""
    parts = re.split(r"(?m)^##\s+([^\n]+)\n", task_text)
    requirements = []
    for heading, body in zip(parts[1::2], parts[2::2]):
        if heading.casefold() in {
            "task objective", "target metric (evaluation)", "submission", "local split caveats"
        } or heading.casefold().startswith("implementation note"):
            content = re.sub(r"```.*?```", "", body, flags=re.DOTALL).strip()
            if content:
                requirements.append(f"### {heading}\n\n{content}")
    return "\n\n".join(requirements)


def render_task_instructions(draft: LongResearchDraft) -> str:
    """Keep task evidence verbatim and label unresolved configuration explicitly."""
    direction = {True: "minimize", False: "maximize", None: "unresolved"}[
        draft.lower_is_better
    ]
    if direction == "unresolved":
        direction += ". Use trusted runtime/evaluator evidence before comparing scores"
    fields = {
        "Task ID": draft.exp_id or "unregistered task",
        "Task profile": draft.task_profile or "exploratory",
        "Task instance": draft.instruction_id,
        "Input data": draft.input_data_dir or "unresolved. Ask for the dataset location",
        "Output artifact": draft.artifact_path or "unresolved",
        "Artifact kind": draft.artifact_kind or "unresolved",
        "Metric": draft.metric_name or "unresolved",
        "Optimization direction": direction,
        "Workers": draft.workers if draft.workers is not None else "unresolved",
        "CPU pool": draft.cpu_list or "unresolved",
        "GPU selection": draft.gpu_list or "unresolved",
        "Time budget (seconds)": draft.wall_clock_sec or "unresolved",
    }
    contract = "\n".join(f"- {name}: {value}" for name, value in fields.items())
    sources = "\n".join(f"- {path}" for path in draft.description_sources) or "- User task description"
    requirements = _task_requirements(draft.task_text)
    guidance = f"## Task-specific requirements\n\n{requirements}\n\n" if requirements else ""
    text = (
        f"# Task instructions\n\n{contract}\n\n"
        f"{guidance}"
        "## Working rules\n\n"
        "The resolved configuration above governs runtime settings. Task evidence "
        "preserves the original description and request. Apply the latest confirmed "
        "worker count, resource pools and time budget when they differ from earlier requests.\n"
        "Follow the task evidence below for the target, input structure, metric and "
        "submission schema. Preserve identifiers, row ordering and required output fields.\n"
        "Inspect available inputs and any provided sample submission before selecting a method. "
        "Keep input data read-only and avoid validation leakage.\n"
        "Use the configured evaluator and artifact contract. Report missing inputs or "
        "unresolved settings explicitly. Record actual evaluation results and respect "
        "the allocated compute and time budget.\n\n"
        f"## Task evidence\n\n{draft.task_text.strip() or 'Task objective is unresolved.'}\n\n"
        f"## Sources\n\n{sources}\n"
    )
    if _START in text or _END in text:
        raise ValueError("Task evidence contains reserved instruction markers")
    return text


def _atomic_write(path: Path, text: str) -> None:
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_task_instructions(draft: LongResearchDraft, workspace: Path) -> TaskInstructionSnapshot:
    """Update only the managed block, preserving manual text and content snapshots."""
    if not re.fullmatch(r"[a-f0-9]{32}", draft.instruction_id):
        raise ValueError("Invalid task instruction instance ID")
    root = Path(workspace).resolve()
    directory = root / ".scienceflow" / "task-instructions" / draft.instruction_id
    if not directory.resolve().is_relative_to(root):
        raise ValueError("Task instruction directory escapes the task workspace")
    block = f"{_START}\n{render_task_instructions(draft)}{_END}"
    with locked(directory):
        path = directory / "AGENTS.md"
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
        for content in (before, after):
            if content:
                version = history / f"{sha256(content.encode('utf-8')).hexdigest()}.md"
                if not version.exists():
                    _atomic_write(version, content)
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != before:
            raise ValueError(f"Task instructions changed during generation; retry: {path}")
        _atomic_write(path, after)
    return TaskInstructionSnapshot(path, digest, True, after)
