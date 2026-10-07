---
description: "Commit approved data platform changes on the current safe branch, push it, and raise a pull request only. Uses commit scope and protected branches from the project profile; never approves or merges PRs."
mode: agent
tools: [read, search, execute]
---
# Raise Pull Request

Use the `Pull Request Agent` workflow. Resolve the project profile first (Profile Resolution in `.github/copilot-instructions.md`; prefer the profile whose `artifact_root` contains the changed files).

Commit approved changes on the current safe feature branch, push the branch, and raise a pull request only.

## Inputs
- PR title or summary: `${input:title:PR title or short summary}`
- Base branch: `${input:base:Base branch, default from project profile}`
- Optional scope: `${input:scope:Optional file scope, default repository.commit_scope}`

## Required Guardrails
- Never commit or push on any branch in `repository.protected_branches`.
- Never approve, merge, or auto-merge a pull request.
- Default staged file scope is `repository.commit_scope`; never stage `repository.never_commit` paths unless explicitly included in the user request.
- If edits exist only in `repository.work_dir`, stop and request completion of the platform conversion before committing.

## Execute
1. Check current branch and stop if it is protected.
2. Inspect changed files and stage only allowed files.
3. Validate changed definitions (JSON/YAML parse, `tooling.validate` if set).
4. Commit with a clear message inferred from the title or summary.
5. Push the current branch with upstream tracking if needed.
6. Raise a PR against the requested base branch, defaulting to `repository.default_pr_base`.
7. Report the PR URL and state clearly that no PR approval or merge was performed.