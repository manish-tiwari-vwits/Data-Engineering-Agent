---
description: "Gravity O&S project rules. Use when editing files under synapse_artifacts."
applyTo: "synapse_artifacts/**"
---
# Gravity O&S (profile: gravity-os)

- Profile: `.github/project/profiles/gravity-os/project-profile.yaml`; rules: `.github/project/profiles/gravity-os/project-knowledge.md`. Read the section for the layer you are changing.
- Platform: Synapse; edit only through the Synapse Platform Agent workflow and the profile `tooling` commands.
- Commit scope: `synapse_artifacts/**`; protected branches: main, master, develop, devlop, development; PR base: `develop`.
- Metadata-driven onboarding: `dwh_meta_tables_population`, `dwh_meta_tables_population2`, `dwh_meta_tables_population3`; copy the closest existing row.
- Landing pipelines follow `PL_DL_landing_<SOURCE>_ALL/_ANY`; reuse before creating a new family.
- Core loads are `p_stg2core_LOAD_*`; copy `p_stg2core_LOAD_Dim_EUAI_Portfolio` / `p_stg2core_LOAD_Dim_Apps`; no `@@ROWCOUNT`, use labeled DML.
- Reporting views go to `dwh_reporting` on core; ignore `dwh_selfservice_silver*` unless asked.
