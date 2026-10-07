---
description: "Use when editing Azure Synapse notebook or SQL script JSON artifacts. Requires JSON to editable roundtrip using the tooling commands in the project profile."
applyTo: "**/notebook/*.json,**/sqlscript/*.json"
---
# Synapse Roundtrip Rules

- Never hand-edit `properties.cells` or `properties.content.query` in raw Synapse JSON.
- Convert only the target artifact with `tooling.to_editable` from the profile whose `repository.artifact_root` contains the file.
- New SQL artifacts start as editable drafts via `tooling.new_sql_artifact`; never hand-author the JSON.
- Edit only the generated file in `repository.work_dir`; validate and show the diff.
- Convert back with `tooling.to_artifact` only after explicit approval.
- Preserve Synapse metadata: pools, folders, connections, sessions, runtime settings.
- Never commit `repository.work_dir` or `repository.index_dir`.
