"""Read a bounded snapshot of project instructions for an interactive session."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


@dataclass(frozen=True)
class ProjectInstruction:
    path: Path
    content: str
    digest: str


def load_project_instructions(
    workspace: Path, *, max_bytes: int = 32768
) -> tuple[ProjectInstruction, ...]:
    """Load root-to-workspace AGENTS.md files, stopping at the nearest Git root.

    A non-Git workspace reads only its own file. Empty files are skipped.
    Invalid or oversized files fail explicitly instead of dropping instructions.
    """
    workspace = workspace.resolve()
    root = next(
        (path for path in (workspace, *workspace.parents) if (path / ".git").exists()),
        workspace,
    )
    directories = [root]
    for part in workspace.relative_to(root).parts:
        directories.append(directories[-1] / part)
    instructions: list[ProjectInstruction] = []
    seen: set[Path] = set()
    total_bytes = 0
    for directory in directories:
        path = directory / "AGENTS.md"
        if not path.exists() and not path.is_symlink():
            continue
        source = path.resolve()
        if not source.is_relative_to(root):
            raise ValueError(f"Project instructions escape project root: {path}")
        if source in seen:
            continue
        seen.add(source)
        # Bound the read itself, including when an instruction file grows concurrently.
        with path.open("rb") as handle:
            raw = handle.read(max_bytes - total_bytes + 1)
        total_bytes += len(raw)
        if total_bytes > max_bytes:
            raise ValueError(f"Project instructions exceed {max_bytes} bytes at {path}")
        try:
            content = raw.decode("utf-8-sig").strip()
        except UnicodeError as exc:
            raise ValueError(f"Invalid UTF-8 in {path}: {exc}") from exc
        if content:
            instructions.append(ProjectInstruction(path, content, sha256(raw).hexdigest()))
    return tuple(instructions)


def project_instruction_prompt(instructions: tuple[ProjectInstruction, ...]) -> str:
    """Include source and content identity in the persisted system prompt."""
    if not instructions:
        return ""
    sections = [
        "Project instructions (session snapshot). Apply each file within its directory "
        "scope; more specific directories take precedence for conflicting guidance."
    ]
    for instruction in instructions:
        sections.append(
            f"Source: {instruction.path}\nSHA256: {instruction.digest}\n\n"
            f"{instruction.content}"
        )
    return "\n\n".join(sections)
