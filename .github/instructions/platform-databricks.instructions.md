---
description: "Use when editing Databricks notebooks, Asset Bundles, jobs, Lakeflow Declarative Pipelines/DLT, Unity Catalog DDL, or Delta MERGE logic."
applyTo: "**/databricks.yml,**/resources/**/*.yml"
---
# Databricks Rules

- Keep `# Databricks notebook source` headers, `# COMMAND ----------` separators, and `# MAGIC` prefixes intact.
- Never hardcode catalog names; use bundle variables, job parameters, or widgets.
- Secrets only via `dbutils.secrets` / secret scopes.
- Keep job task keys and parameters stable across targets.
- `databricks bundle validate` is allowed; `bundle deploy`/`bundle run` require explicit approval.
