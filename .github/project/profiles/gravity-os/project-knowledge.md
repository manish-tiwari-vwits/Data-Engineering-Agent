# Project Knowledge: Gravity O&S

Project-specific rules for this profile. Generic agents read the section for the stage they own.
Keep generic engineering rules out of this file; put only facts and conventions unique to this project here.

## Lineage
- `.github/Data Lineage-v1-20260909_120038.pdf` is the lineage source; read it before opening large Synapse JSON artifacts.
- Page `0_Inbound Layer`: source file -> staging table.
- Page `1_Core layer`: staging table -> core table.
- Page `2_Outbound Layer (Views)`: core table -> reporting view.
- If lineage and local artifacts disagree, report both facts and ask one focused question before editing.

## Metadata Framework (orchestrate, ingest, refine)
- Control metadata lives in schema `dwh_meta` and is populated by SQL scripts resolved through the profile's `index_dir` (`sqlscripts.json`):
  - `dwh_meta_tables_population` -> `dwh_meta.etl_inbound_interfaces` (source/interface onboarding, inbound settings).
  - `dwh_meta_tables_population2` -> `dwh_meta.etl_data_lake_entity_attributes` (landing/entity attributes).
  - `dwh_meta_tables_population3` -> `dwh_meta.etl_data_lake_json_to_parquet` (JSON attribute -> parquet column mappings).
- Add rows by copying the closest existing source/interface/entity pattern and changing only required values.
- Landing pipeline families follow `PL_DL_landing_<SOURCE>_ALL` (selects/loops configured interfaces) and `PL_DL_landing_<SOURCE>_ANY` (loads one interface/entity from parent parameters). Reference: `PL_DL_landing_ASDW_ALL` / `PL_DL_landing_ASDW_ANY`.
- Reuse an existing family through metadata; create a new family only when parameter contracts, datasets, linked services, or activity structure cannot support the source.

## Landing (ingest)
- Keep payloads raw and as-is.
- Before adding inbound metadata, compare `interface_name`, source names, REST/file settings, key vault secret, and `interface_extended_settings_json` with existing rows.

## Curated (refine)
- Landing notebooks/curated logic: look for `lnd2crt`, `curated`, or source-specific notebooks.
- `dwh_meta_tables_population2`: follow rows with the same `entity_name`, `data_lake_layer`, `attribute_name`, and next `attribute_id`.
- `dwh_meta_tables_population3`: follow rows with the same `interface_name`, `json_file_name`, `parquet_entity`, `json_root`, `json_attribute`, `parquet_column_name`.
- For CSV/file sources reuse the existing curated file-type flow; for JSON/API sources check JSON-to-parquet metadata first.

## Staging (refine)
- Staging reads curated parquet into dedicated SQL pool staging tables.
- For PolyBase errors such as `HdfsBridge::recordReaderFillBuffer` or `MalformedInputException`, compare external table column types with the parquet schema first.

## Core (model)
- Load procedures are named `p_stg2core_LOAD_*`.
- SCD Type 1 reference procedures: `p_stg2core_LOAD_Dim_EUAI_Portfolio`, `p_stg2core_LOAD_Dim_Apps`. Never rely on generic generated merge code.
- Do not use `@@ROWCOUNT`; use labeled DML plus `sys.dm_pdw_exec_requests` / `sys.dm_pdw_request_steps` for row counts.
- Business key dedupe uses the latest `_lineage_row_id`.
- Preserve transaction and TRY/CATCH logging; ensure DML labels are present.

## Reporting (serve)
- Create Power BI/reporting views in `dwh_reporting` on top of core tables.
- Ignore `dwh_selfservice_silver` and `dwh_selfservice_silver_finance` (POC views on staging) unless explicitly asked.
