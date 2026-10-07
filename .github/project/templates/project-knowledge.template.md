# Project Knowledge: <Project Name>

Project-specific rules only. Generic engineering rules live in `.github/instructions/`.
Agents read the section for the stage they own. Delete sections that do not apply.

## Lineage
- Where lineage lives and how to read it (document pages, catalog, tool).

## Metadata / Orchestration (orchestrate)
- Control tables or config files and which script/file owns each.
- Reusable pipeline/job families and their parameter contracts.

## Ingest
- Source systems, connection patterns, secret store conventions, landing path conventions.

## Refine
- Standardization rules, file formats, partitioning, dedupe keys, known schema-drift handling.

## Model
- Naming conventions for dims/facts/load procedures or jobs.
- Known-good reference implementations to copy (SCD1, SCD2).
- Platform-specific gotchas (e.g. unsupported functions, row-count patterns).

## Serve
- Target schemas for reporting/semantic outputs; schemas to ignore.
- Consumer contracts and backward-compatibility expectations.
