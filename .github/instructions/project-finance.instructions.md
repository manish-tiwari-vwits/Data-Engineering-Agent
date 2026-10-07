---
description: "Finance (ITF FROG) project rules. Use when editing files under Synapse-itf-Dev."
applyTo: "Synapse-itf-Dev/**"
---
# Finance (ITF FROG) (profile: finance)

- Profile: `.github/project/profiles/finance/project-profile.yaml`; rules: `.github/project/profiles/finance/project-knowledge.md`. Read the section for the layer you are changing.
- Platform: Synapse (dedicated pool `itf_frog`, Spark `sparkpoolv35`, serverless `it_finance`); edit only via the Synapse Platform Agent workflow and the profile `tooling` commands.
- Commit scope: `Synapse-itf-Dev/**`; protected branches: main, Main-DEV, workspace_publish; PR base: `Main-DEV`.
- Add a `CHANGELOG.md` `[Unreleased]` entry with the GRAVITY key for every artifact change. (evidence: Synapse-itf-Dev/CHANGELOG.md)
- Core (`dbo`) is SCD Type 1; new `P_DIM_*`/`P_IMPORT_*` procs take `@ProcessDate` and must be registered in `dbo.sp_Run_ETL_Driver` with TRY/CATCH -> `dbo.ErrorLog`. (evidence: sp_Run_ETL_Driver.json)
- Staging (`dwh`) and silver notebooks are SCD Type 2: `KeyHash`/`ValueHash`, `IsCurrent`/`ValidTo`. (evidence: sp_Load_T_IMPORT_PAF_WA_Stammdaten_R4.json)
- Core tables: `HASH` distribution, `HEAP`, `PRIMARY KEY NONCLUSTERED ... NOT ENFORCED`. (evidence: T_DIM_43_Kundenkostenstelle_SKST.json)
- Reporting procs `rpt.P_R_*` run via `rpt.SP_Master_Core_to_Reporting`; serverless gold views live in `it_finance.out_gold`. (evidence: README.md)
- Infra changes belong in `itf-frog-infra`; deployment changes in `itf-frog-devops`. (evidence: README.md)
