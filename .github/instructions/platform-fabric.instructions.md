---
description: "Use when editing Microsoft Fabric Git-integrated items: notebooks, data pipelines, lakehouses, warehouses, semantic models, dataflows."
applyTo: "**/*.Notebook/**,**/*.DataPipeline/**,**/*.Lakehouse/**,**/*.Warehouse/**,**/*.SemanticModel/**,**/*.Dataflow/**"
---
# Fabric Item Rules

- Never change `logicalId` in an existing `.platform` file, rename item folders, or change item types.
- Notebooks: keep `# CELL` / `# METADATA` markers and the dependency header intact; edit cell code only.
- No workspace/lakehouse GUIDs or credentials inline; use default lakehouse, parameters, `notebookutils`, or `parameter.yml`.
- Lakehouse SQL analytics endpoint is read-only; DML belongs in Spark or the Warehouse.
- Validate (Python syntax / JSON parse) and get approval before treating the change as final; never sync or deploy without approval.
