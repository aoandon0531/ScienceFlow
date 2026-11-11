"""Project instructions reach real runtime requests without changing factual history."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import click
import pytest
from inquirycraft.events import NullEventSink
from inquirycraft.runtime import RuntimeOptions

from scienceflow.interfaces.ui import llm_cli
from scienceflow.research.state.knowledge.prompt.project_instructions import (
    load_project_instructions,
)


def test_git_chain_uses_workspace_and_skips_unrelated_directories(tmp_path):
    (tmp_path / ".git").write_text("gitdir: /unused/worktree")
    child = tmp_path / "src"
    child.mkdir()
    sibling = tmp_path / "other"
    sibling.mkdir()
    (tmp_path / "AGENTS.md").write_text("root rule")
    (child / "AGENTS.md").write_text("child rule")
    (sibling / "AGENTS.md").write_text("unrelated rule")
    found = load_project_instructions(child)
    assert [item.content for item in found] == ["root rule", "child rule"]
    assert [item.path for item in found] == [tmp_path / "AGENTS.md", child / "AGENTS.md"]
    assert all(len(item.digest) == 64 for item in found)


def test_non_git_workspace_does_not_inherit_parent_rules(tmp_path):
    (tmp_path / "AGENTS.md").write_text("parent rule")
    child = tmp_path / "plain"
    child.mkdir()
    assert load_project_instructions(child) == ()
    (child / "AGENTS.md").write_text("\ufefflocal rule", encoding="utf-8")
    assert load_project_instructions(child)[0].content == "local rule"


def test_empty_and_missing_instructions(tmp_path):
    assert load_project_instructions(tmp_path) == ()
    (tmp_path / "AGENTS.md").write_text(" \n")
    assert load_project_instructions(tmp_path) == ()


def test_combined_instruction_limit_is_explicit(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "AGENTS.md").write_text("12345")
    child = tmp_path / "child"
    child.mkdir()
    (child / "AGENTS.md").write_text("67890")
    with pytest.raises(ValueError, match="exceed 9 bytes"):
        load_project_instructions(child, max_bytes=9)


def test_symlink_deduplication_and_scope_boundary(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "AGENTS.md").write_text("root")
    child = tmp_path / "child"
    child.mkdir()
    link = child / "AGENTS.md"
    link.symlink_to(tmp_path / "AGENTS.md")
    assert len(load_project_instructions(child)) == 1
    link.unlink()
    link.symlink_to(tmp_path.parent / "outside.md")
    with pytest.raises(ValueError, match="escape project root"):
        load_project_instructions(child)


@pytest.mark.parametrize("kind", ["invalid_utf8", "directory", "unreadable"])
def test_bad_instruction_file_has_actionable_diagnostic(tmp_path, monkeypatch, kind):
    path = tmp_path / "AGENTS.md"
    if kind == "directory":
        path.mkdir()
    else:
        path.write_bytes(b"\xff" if kind == "invalid_utf8" else b"rule")
    if kind == "unreadable":
        original = Path.open

        def denied(self, *args, **kwargs):
            if self == path:
                raise PermissionError(f"Permission denied: {self}")
            return original(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", denied)
    from inquirycraft.memory import Conversation

    with pytest.raises(click.ClickException, match="Cannot load project instructions") as error:
        llm_cli.TuiPoolRuntimeFactory()._prepare_options(
            RuntimeOptions(model="test", workspace=tmp_path), Conversation()
        )
    assert str(path) in str(error.value)


@pytest.fixture
def captured_provider(monkeypatch):
    requests = []

    class Provider:
        max_tokens = 512
        _last_finish_reason = "stop"

        async def ask_tool(self, **kwargs):
            requests.append(kwargs["messages"])
            return SimpleNamespace(content="done", tool_calls=[], reasoning_content="")

    monkeypatch.setattr(llm_cli, "build_stage_llm", lambda stage: Provider())
    return requests


def make_runtime(options, factory=llm_cli.TuiPoolRuntimeFactory):
    return factory().create_runtime(
        options, api_key="test-key", base_url="http://example.test/v1",
        event_sink=NullEventSink(),
    )


@pytest.mark.asyncio
async def test_snapshot_reaches_requests_compaction_and_resume(tmp_path, captured_provider):
    path = tmp_path / "AGENTS.md"
    path.write_text("Always store outputs under results/.")
    options = RuntimeOptions(
        model="test", workspace=tmp_path, system_prompt="Custom base prompt.",
        session_log=tmp_path / "session.jsonl", operation_log=tmp_path / "operations.jsonl",
    )
    runtime = make_runtime(options)
    try:
        assert await runtime.run("Prepare a report.") == "done"
        first_system = captured_provider[-1][0]["content"]
        assert first_system.startswith("Custom base prompt.")
        assert "Always store outputs under results/." in first_system
        assert str(path) in first_system and "SHA256:" in first_system
        path.write_text("A changed rule for a future session.")
        await runtime.compact_context()
        await runtime.run("Continue.")
        assert captured_provider[-1][0]["content"] == first_system
        assert sum(row.get("content") == first_system for row in captured_provider[-1]) == 1
    finally:
        await runtime.aclose()
    # Resume must use the saved prompt, even when current files are invalid.
    path.write_bytes(b"\xff")
    runtime = make_runtime(options)
    try:
        await runtime.run("Resume the report.")
        assert captured_provider[-1][0]["content"] == first_system
    finally:
        await runtime.aclose()
    path.write_text("A changed rule for a future session.")
    runtime = make_runtime(replace(options, session_log=None, operation_log=None))
    try:
        await runtime.run("New session.")
        assert "A changed rule for a future session." in captured_provider[-1][0]["content"]
        assert "Always store outputs under results/." not in captured_provider[-1][0]["content"]
    finally:
        await runtime.aclose()


@pytest.mark.asyncio
async def test_missing_rules_and_non_tui_factory_keep_base_prompt(tmp_path, captured_provider):
    options = RuntimeOptions(model="test", workspace=tmp_path, system_prompt="Base.")
    runtime = make_runtime(options)
    try:
        await runtime.run("hello")
        assert captured_provider[-1][0]["content"] == "Base."
    finally:
        await runtime.aclose()
    (tmp_path / "AGENTS.md").write_text("TUI-only project rule.")
    runtime = make_runtime(options, llm_cli.PoolRuntimeFactory)
    try:
        await runtime.run("hello")
        assert captured_provider[-1][0]["content"] == "Base."
    finally:
        await runtime.aclose()
