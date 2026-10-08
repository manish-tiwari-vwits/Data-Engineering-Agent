# Workspace Agent Map

Project configuration: one folder per project in `.github/project/profiles/<id>/` (profile + `knowledge_file`); default in `.github/project/active-profile.yaml` (local copy of `active-profile.example.yaml`); selection rules in `.github/copilot-instructions.md`. Onboard a cloned repo with `/init-project-profile`; rescan with `/refresh-project-profile`.

| Tier | Agent | Role |
|---|---|---|
| Entry | `Data Engineering Orchestrator` | Plans and routes; never edits. Starts onboarding for un-onboarded folders. |
| Entry | `Project Setup Agent` | Scans a cloned repo; generates profile, project rules, and `project-<id>.instructions.md` from evidence. |
| Entry | `Jira` | Fetches tickets; description shown before analysis. |
| Entry | `Confluence` | Docs read/search; writes need explicit approval of exact page and change. |
| Stage | `Ingestion Agent` | `ingest` layers (landing/raw/bronze). |
| Stage | `Transformation Agent` | `refine` layers (curated/staging/silver). |
| Stage | `Data Modeling Agent` | `model` layers (core/gold, SCD). |
| Stage | `Serving Agent` | `serve` layers (reporting/semantic). |
| Stage | `Orchestration Agent` | Pipelines/jobs/DAGs, config metadata, source onboarding, reuse vs create. |
| Cross | `Lineage Impact Agent` | Read-only lineage and impact. |
| Platform | `Synapse Platform Agent` | Synapse JSON artifacts via roundtrip tooling. |
| Platform | `Fabric Platform Agent` | Fabric Git items. |
| Platform | `Databricks Platform Agent` | Notebooks, bundles, jobs, Lakeflow, Unity Catalog. |
| Platform | `AWS Platform Agent` | Glue, Step Functions, Airflow, Redshift/Athena, IaC. |
| Delivery | `Pull Request Agent` / `/raise-pr` | Commit within `commit_scope` on a safe branch and open a PR; never approve or merge. |

- Flow: Jira -> Orchestrator -> Lineage -> Stage agent(s) -> Platform agent (edit, validate, approval) -> Pull Request Agent.
- Platform agent per layer: `layer.platform` override, else `platform.primary`.
- Keep outputs compact: impacted layer, target files, edit plan, validation, blockers.
