"""LLM-authored task instructions for chat and research preparation."""

import asyncio
from dataclasses import dataclass, replace
import json
from pathlib import Path
import re

from inquirycraft.runtime import RuntimeOptions
from inquirycraft.tools import ReadTextTool, ToolCollection

from scienceflow.foundation.config.llm.model_registry import load_model_registry
from scienceflow.interfaces.ui.research.control.workspace_tool import WorkspaceInfoTool

_DETECT_PROMPT = """Identify intent in the CURRENT user request. Return one JSON object
with action keep/new/update and a short title for new/update. History is context,
not a fresh instruction. When a task is active, questions about needed materials,
next steps, explanations or progress use keep. For example, "Which materials should
I provide next?" continues the active task. Mere topic mentions also use keep.
Use new only when the current user explicitly starts, restarts or switches tasks.
Use update when the current user changes task requirements or supplies requested
missing task facts. A clarification of an earlier start can use new when no task
is active yet. Do not author instructions in this step.
"""
_AUTHOR_PROMPT = """Write a complete AGENTS.md for the supplied task. Return only
Markdown. Choose suitable headings and adapt the purpose, workflow, constraints,
validation and failure handling to this task. Treat supplied materials as evidence.
Use material_contents as host-read evidence. Read additional relevant materials
with read_text when needed. Respect workspace scope. Mark unknowns
and describe needed clarification. Avoid inventing data, evaluation results or
completed work.
Keep the requested work stage: preparing a plan or protocol calls for drafting and
reviewing that document. Later execution belongs in clearly labeled future work.
Constraints must come from the request, project guidance or supplied materials.
Label optional methods as proposals and unknown technical assumptions as questions.
Preserve confirmed task facts. When confirmed_facts is nonempty, include one fenced
json block containing exactly that object for host validation.
Preserve confirmed task IDs, artifact paths, metric names and dataset paths verbatim.
Use project_guidance as persistent project context when authoring compatible task
instructions. The requested output format governs this authoring response.
Do not include host control markers or wrap the entire document in a code fence.
"""


@dataclass(frozen=True)
class AuthoredInstructions:
    action: str
    title: str = ""
    markdown: str = ""


def _material_context(references):
    materials = []
    remaining = 24000
    for path in references:
        with path.open("rb") as handle:
            raw = handle.read(remaining + 1)
        truncated = len(raw) > remaining
        text = raw[:remaining].decode("utf-8", errors="replace" if truncated else "strict")
        materials.append({"path": str(path), "text": text, "truncated": truncated})
        remaining -= min(len(raw), remaining)
        if not remaining:
            break
    return materials


def _json_response(text):
    raw = text.strip()
    if raw.startswith("```") and raw.endswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(raw)


def validate_authored_instructions(text, facts, *, detect=False, has_current=False):
    if detect:
        row = _json_response(text)
        if not isinstance(row, dict):
            raise ValueError("Expected a task intent JSON object")
        action = row.get("action")
        if action == "keep":
            return AuthoredInstructions("keep")
        if action not in {"new", "update"} or (action == "update" and not has_current):
            raise ValueError("Expected a valid task creation or update action")
        title = row.get("title")
        if not isinstance(title, str) or not title.strip() or len(title) > 160:
            raise ValueError("A task title of 1–160 characters is required")
        return AuthoredInstructions(action, title.strip())
    markdown = text.strip()
    if markdown.startswith(("```markdown\n", "```md\n")) and markdown.endswith("```"):
        markdown = markdown.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    if not markdown or markdown.startswith('{"action"'):
        raise ValueError("Return the complete Markdown document, without a JSON envelope")
    if len(markdown.encode("utf-8")) > 32768 or "\x00" in markdown:
        raise ValueError("Markdown must be valid text within 32768 bytes")
    if "<!-- scienceflow:task-instructions:" in markdown:
        raise ValueError("Markdown must omit host control markers")
    if facts:
        objects = []
        for match in re.finditer(r"```json\s*\n(.*?)```", markdown, re.DOTALL):
            try:
                objects.append(json.loads(match.group(1)))
            except ValueError:
                continue
        if facts not in objects:
            raise ValueError("Include a fenced json block exactly preserving confirmed_facts")
    return AuthoredInstructions("new", markdown=markdown)


def confirmed_task_facts(draft):
    fields = {
        "task_id": draft.exp_id, "artifact_path": draft.artifact_path,
        "metric_name": draft.metric_name, "input_data_dir": draft.input_data_dir,
        "lower_is_better": draft.lower_is_better, "workers": draft.workers,
        "cpu_list": draft.cpu_list, "gpu_list": draft.gpu_list,
        "wall_clock_sec": draft.wall_clock_sec,
    }
    return {key: value for key, value in fields.items() if value is not None and value != ""}


async def _model_call(owner, host, options, resolved, payload, *, detect):
    options = replace(options, system_prompt=_DETECT_PROMPT if detect else _AUTHOR_PROMPT,
                      max_tokens=512 if detect else 4096, max_turns=1 if detect else 6,
                      temperature=0.0)
    tools = ToolCollection() if detect else ToolCollection((ReadTextTool(), WorkspaceInfoTool()))
    runtime = owner.preparation_runtime_factory.create_runtime(
        options, api_key=",".join(resolved.api_keys), base_url=",".join(resolved.base_urls),
        event_sink=None, tools=tools,
    )
    try:
        reply = await asyncio.wait_for(
            host.run_host_task(json.dumps(payload, ensure_ascii=False), show_response=False, runtime=runtime),
            timeout=95,
        )
        if getattr(runtime.llm.backend, "_last_finish_reason", "stop") == "length":
            raise ValueError("Model output was truncated. Produce a shorter complete document")
        return reply
    finally:
        await runtime.aclose()


async def author_task_instructions(owner, host, request, *, facts, current=None, detect=False):
    """Allow one correction across intent recognition and Markdown generation."""
    registry = load_model_registry(owner._model_config_path)
    aliases = owner._selected_model_aliases or registry.default_aliases("code_models")[:1]
    resolved = registry.resolve(aliases, role="code")
    chat = getattr(host, "runtime", None)
    options = getattr(chat, "options", None) or RuntimeOptions(model=resolved.models[0], workspace=owner.workspace)
    options = replace(options, model=",".join(resolved.models), workspace=owner.task_workspace,
                      session_id="", run_id="", agent_id="instruction-author",
                      session_log=None, operation_log=None, stream_llm=False)
    payload = {
        "request": request, "confirmed_facts": facts,
        "current_title": getattr(chat, "active_task_title", ""),
        "current_instructions": (
            current.content.replace("<!-- scienceflow:task-instructions:start -->", "")
            .replace("<!-- scienceflow:task-instructions:end -->", "") if current else ""
        ),
    }
    workspace = owner.task_workspace
    references = []
    for index, path in enumerate(workspace.iterdir()):
        if index >= 200:
            break
        if not path.name.startswith(".") and path.is_file() and path.name in request:
            if not path.resolve().is_relative_to(workspace.resolve()):
                raise ValueError(f"Referenced material escapes the workspace: {path}")
            references.append(path)
    for name in re.findall(r"[/\w.-]+/[/\w.-]+", request):
        path = (workspace / name).resolve()
        if path.is_relative_to(workspace.resolve()) and path.is_file() and path not in references:
            references.append(path)
    payload["supplied_materials"] = [str(path.relative_to(workspace)) for path in references]
    if detect:
        payload["recent_conversation"] = [
            {"role": row["role"], "content": str(row.get("content") or "")[-2000:]}
            for row in host.conversation_snapshot()[-6:]
            if row.get("role") in {"user", "assistant"}
        ]
    decision = None if detect else AuthoredInstructions("update" if current else "new")
    error = reply = ""
    for attempt in range(2):
        try:
            context = {**payload, "previous_error": error, "previous_output": reply[-6000:] if error else ""}
            if decision is None:
                reply = await _model_call(owner, host, options, resolved, {**context, "phase": "detect"}, detect=True)
                decision = validate_authored_instructions(reply, facts, detect=True, has_current=current is not None)
                if decision.action == "keep":
                    return decision
            context["material_contents"] = await asyncio.to_thread(_material_context, references)
            context["project_guidance"] = options.system_prompt
            reply = await _model_call(owner, host, options, resolved, {**context, "phase": "write"}, detect=False)
            authored = validate_authored_instructions(reply, facts)
            heading = re.search(r"(?m)^#{1,6}\s+(.+)$", authored.markdown)
            title = decision.title or (heading.group(1)[:160] if heading else "Research task")
            return AuthoredInstructions(decision.action, title, authored.markdown)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if not attempt:
                await host.notice("Task instruction generation needs correction. Retrying once.")
    raise ValueError(f"Task instruction generation failed after one correction: {error}")
