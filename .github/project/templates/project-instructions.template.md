---
description: "<Project Name> project rules. Use when editing files under <artifact_root>."
applyTo: "<artifact_root>/**"
---
# <Project Name> (profile: <project-id>)

- Profile: `.github/project/profiles/<project-id>/project-profile.yaml`; rules: `.github/project/profiles/<project-id>/project-knowledge.md`. Read the section for the layer you are changing.
- Platform: <platform>; edit only through the <Platform> Platform Agent workflow and the profile `tooling` commands.
- Commit scope: `<commit_scope>`; protected branches: <protected_branches>; PR base: `<default_pr_base>`.
<!-- 5-10 most important project rules, each with its evidence path, e.g.:
- Load procedures follow `<prefix>`; copy `<reference artifact>` (evidence: <path>).
- Serving objects go to `<schema>` in folder `<folder>` (evidence: <path>).
-->
