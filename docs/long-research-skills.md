# Long-research skill loading

`/long-research` workers automatically discover the built-in Markdown skill library
in `skills/` (or the wheel-installed `share/scienceflow/skills/` directory).
The first research request includes skill names, descriptions and tags. This works
for unregistered tasks and does not require an MLE-bench category mapping.

The model selects relevant guidance and calls the existing `skill` tool:

```json
{"action": "read", "name": "tabular_preprocess_speedup"}
```

Use `{"action": "list"}` to browse. Full skill content enters the conversation only
when read. Reading an executable skill does not execute its code. This stage does
not generate or update skills, and it does not add skills to the preparation chat.

Defaults under `lnr`:

```yaml
lnr_skill_tool_enabled: true
lnr_skill_tool_mode: all
lnr_skill_visible_max: 0  # all metadata entries; positive values limit the catalog
```

Set `lnr_skill_tool_enabled: false` to disable loading. Set
`lnr_skill_tool_mode: category_only` to retain the existing task/category allowlist.
The existing `lnr_skill_auto_read` option applies to compact hints in category mode.
Model selection and use of the guidance remain task dependent.
