---
description: "Use when planning or implementing any data engineering change (ingestion, transformation, staging, modeling/SCD, serving/reporting, pipelines) on any platform. Generic engineering standards; project specifics come from the resolved project profile."
---
# Data Engineering Standards

- Resolve the project profile (Profile Resolution in `.github/copilot-instructions.md`) and read the relevant section of its `knowledge_file` before planning. Use the project's layer names; map them to stages `ingest`, `refine`, `model`, `serve`, `orchestrate`.
- For each task identify: source, target, owning layer, lineage result, artifacts, dependencies, and one cheap validation check before editing.
- Upstream first: if a downstream layer needs a table or column that does not exist upstream, onboard it through ingest/refine (and their metadata) before changing downstream objects.
- Schema evidence first: derive DDL from source contracts, schema files, parquet/Delta/Iceberg schema, or catalog metadata. Never generate final DDL from blanket string types; mark drafts provisional when evidence is missing.
- Type mapping must be deliberate per dialect (e.g. timestamp -> `datetime2(7)` in T-SQL, `TIMESTAMP` in Spark/Redshift; long -> `bigint`; decimal precision preserved; boolean -> `bit`/`BOOLEAN`).
- Reuse before create: extend existing pipelines, jobs, metadata rows, and reference implementations rather than duplicating them.
- SCD: default to the profile's `scd_default`; Type 2 only when explicitly requested. Dedupe the source on business key before merge. Hash/checksum, update, and insert paths must include every tracked column.
- Loads must be idempotent and safe to rerun; document watermark/CDC behavior.
- Serve-layer objects are contracts: no breaking renames or grain changes without explicit request.
- No secrets, keys, account IDs, workspace GUIDs, or environment-specific names inline; use the platform secret store and parameters.
- Anchor on one named object; no estate-wide scans unless the user asks for an audit.
- Never deploy, publish, run production jobs, or change grants without explicit approval.
