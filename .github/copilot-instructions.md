# Data Engineering Agent Instructions

- Project specifics (platform, layers, paths, tooling, branches) live in a project profile; project rules live in its `knowledge_file`. Read both before planning or editing. Agents and instructions stay project-agnostic.

## Profile Resolution
Profiles: `.github/project/profiles/<id>/project-profile.yaml`. Several projects can share one workspace. Pick exactly one profile per request:
1. A `Profile:` path passed by the calling agent wins.
2. A file or folder path in the request that starts with a profile's `repository.artifact_root`.
3. A Jira ticket: a ticket label in exactly one profile's `project.jira_labels` wins; otherwise the key prefix, if exactly one profile's `project.jira_project_keys` contains it. Labels come from the Jira agent's ticket summary.
4. `active` in `.github/project/active-profile.yaml`, only when the request has no Jira ticket. If a ticket matches several profiles and no label decides, ask instead.
5. Otherwise ask which project. State the chosen profile id in the output.
6. If no profile exists, or a referenced folder is not claimed by any profile's `artifact_root`, it is an un-onboarded repo: use `Project Setup Agent` (or `/init-project-profile`) before any implementation work.
When delegating, always pass `Profile: <path>` and `Knowledge: <knowledge_file>`.

## Working Rules
- Default to the `Data Engineering Orchestrator` for Jira tickets and data engineering changes on Synapse, Fabric, Databricks, or AWS.
- Architecture: project layers map to stages `ingest`, `refine`, `model`, `serve`, `orchestrate`; route work to the narrowest stage agent, which delegates edits to the platform agent for that layer.
- Inspect orchestration (parameters, activities/tasks, dependencies, config) before changing pipeline/job behavior; prefer configuration reuse over new pipelines.
- Follow the platform agent's edit workflow. On Synapse never hand-edit notebook or SQL script JSON; use the roundtrip commands in `tooling`.
- Restrict implementation changes to `repository.commit_scope` unless the user explicitly asks to change agent, instruction, tooling, or documentation files.
- When preparing commits, never include `repository.never_commit` paths unless explicitly requested.
- Optimize for speed: search by exact ticket keys, object, table, notebook, job, pipeline, and file names before broader scans.
