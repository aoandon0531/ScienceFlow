# TUI verification quickstart

Use Ubuntu/Linux or Ubuntu under WSL, Python 3.12, Git and uv. The CPU-only
control plane is sufficient for the checks below. A reachable OpenAI-compatible
model service with tool calling is required for live TUI requests.

## Install this delivery branch

```bash
git clone --branch feat/task-instructions https://github.com/aoandon0531/ScienceFlow.git
cd ScienceFlow
git log -5 --oneline
uv sync --frozen --python 3.12
uv run scienceflow config init
uv run scienceflow config path
```

Edit the private model registry reported by `config path`. For a locally forwarded
Qwen3 service on port 18080, use this example (replace the endpoint/key as needed):

```json
{
  "version": 1,
  "models": {
    "qwen3-8b": {
      "model": "qwen3-8b",
      "use_proxy": false,
      "endpoints": [{"url": "http://127.0.0.1:18080/v1", "key": "local-no-auth"}]
    }
  },
  "defaults": {
    "code_models": ["qwen3-8b"],
    "feedback_models": ["qwen3-8b"],
    "selection": "auto"
  }
}
```

The placeholder key works only when the service does not require authentication.
For Qwen3 served by vLLM, automatic tool calls must be enabled on the server
(`--enable-auto-tool-choice --tool-call-parser hermes`). SSH access and credentials
are configured separately by the environment owner. Do not put them in Git.

```bash
curl http://127.0.0.1:18080/v1/models
mkdir -p /tmp/sf-review
uv run scienceflow tui --workspace /tmp/sf-review --models qwen3-8b --max-tokens 4096
```

The installed command is `scienceflow`. If the shorter `sf tui` spelling is needed,
activate the environment and define a shell alias:

```bash
source .venv/bin/activate
alias sf=scienceflow
sf tui --workspace /tmp/sf-review --models qwen3-8b --max-tokens 4096
```

## Task instruction check in the TUI

1. Explicitly start a task, for example: "Start a new task: draft an interview plan
   for five graduate students about literature search. Deliver interview_plan.md.
   Prepare the plan only; do not conduct interviews."
2. The TUI reports the generated instruction path under
   `/tmp/sf-review/.scienceflow/task-instructions/<id>/AGENTS.md`.
3. Ask a continuation question. The current instruction file should remain active.
4. Explicitly switch to a different task. A new task instruction file becomes active,
   while the ordinary conversation remains shared.

Also inspect the generated content. Format and fact checks do not guarantee that
all generated prose faithfully preserves the request. See [instruction behavior](tui-project-instructions.md).

## Skill loading check without a research run

From the repository root, the following uses the same existing registry and read
utility used by research workers. It needs no model API or benchmark dataset:

```bash
uv run python - <<'PY'
import asyncio
from pathlib import Path
from scienceflow.research.state.knowledge.skills.catalog.registry import SkillRegistry
from scienceflow.research.state.knowledge.skills.runtime.tool import SkillTool
registry = SkillRegistry()
registry.load_all(Path("skills"))
tool = SkillTool(registry=registry)
print(asyncio.run(tool.execute(action="list")).output)
print(asyncio.run(tool.execute(action="read", name="tabular_preprocess_speedup")).output)
PY
```

For a live integration check, start a configured task with `/long-research` in the
TUI, confirm its resources and launch a worker. Its first research request includes
the skill catalog, and relevant full text is retrieved through `skill` tool calls.
Skill loading is in research workers, not ordinary chat or task preparation.
Choose a task relevant to the existing skills, such as tabular preprocessing.
The directory/read check above alone does not validate model selection or research
quality. See [skill behavior and switches](long-research-skills.md).

This delivery validates instruction and skill integration. It does not establish
improved MLE-bench scores, runtime speedups or long-research success rates.
