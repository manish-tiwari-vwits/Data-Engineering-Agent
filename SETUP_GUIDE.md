# Setup Guide

One-time setup for developers using the data engineering agents (Synapse, Fabric, Databricks, AWS) with Jira and Confluence.

## 1. Prerequisites
- Windows, PowerShell, Git, Python 3.10+
- VS Code with GitHub Copilot Chat (agent mode enabled)
- Access to the Azure DevOps project repos and your Jira/Confluence tokens

## 2. Clone and open the agents workspace
```powershell
git clone <agents-workspace-repo-url> standard-agent
cd standard-agent
code .
```

## 3. Python environment
```powershell
python -m venv .verify_env
.\.verify_env\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```
`.vscode/mcp.json` expects `.verify_env\Scripts\python.exe`. If you use another folder name, update that path.

## 4. Jira and Confluence credentials
```powershell
Copy-Item .env.example .env
notepad .env
```
Fill `JIRA_URL`, `JIRA_TOKEN`, `CONFLUENCE_URL`, `CONFLUENCE_TOKEN`. Never commit or share `.env`.

## 5. Clone your project repo(s) into the workspace
Use exactly these folder names; the profiles in `.github/project/profiles/` depend on them.
```powershell
# Gravity O&S
git clone https://Volkswagen-AG@dev.azure.com/Volkswagen-AG/IT-RA/_git/synapse_artifacts synapse_artifacts
# Finance (ITF FROG)
git clone https://Volkswagen-AG@dev.azure.com/Volkswagen-AG/gravity-development/_git/Synapse-itf-Dev Synapse-itf-Dev
```

## 6. Build local index and lineage (once per project)
Commands are also listed under `tooling:` in each profile and as VS Code tasks (**Terminal -> Run Task**).
```powershell
# Finance
python tools/build_synapse_index.py --root Synapse-itf-Dev --out .synapse_index/finance
python tools/build_lineage.py --root Synapse-itf-Dev --out .lineage/finance --title "Finance (ITF FROG)" --layers "raw;landing;curated;staging=dwh_stg,dwh;core=dbo;reporting=rpt;bronze;silver;gold;out_gold=out_gold"

# Gravity O&S
python tools/build_synapse_index.py --root synapse_artifacts --out .synapse_index
```

## 7. Reload and enable tools
1. `Ctrl+Shift+P` -> **Developer: Reload Window**.
2. In Copilot Chat, open **Configure Tools** and enable file read/edit and the terminal tool.

## 8. Verify
- **Jira** agent: `Fetch GRAVITY-1234 read-only and show the description`
- **Confluence** agent: `Fetch <page-url> read-only and summarize it`
- **Data Engineering Orchestrator** appears in the agent picker.

## New project not yet onboarded?
1. Clone its repo into the workspace (any folder name).
2. In Copilot Chat run `/init-project-profile` and enter the project name.
3. Answer the questions (Jira key, Jira label that identifies the project, PR branch, CONFIRM items) and approve.
4. Reload VS Code.

## Daily use
| Task | How |
|---|---|
| Implement a ticket | **Data Engineering Orchestrator**: `Implement GRAVITY-1234` |
| Approve Synapse edits | Review the diff, reply `yes` to convert back to JSON |
| Raise a PR | On a feature branch (never `main`, `Main-DEV`, `develop`, `workspace_publish`): `/raise-pr` |
| Impact of a table | **Lineage Impact Agent**: `Downstream of <schema.table>` |
| Refresh lineage PDF | Run Task -> **Lineage: build table-level lineage PDF** |
| Project repo changed a lot | `/refresh-project-profile` |

Finance: every artifact change also needs a `CHANGELOG.md` entry with the Jira key.

## Examples
Pick the agent in the Copilot Chat agent picker, then type the prompt. Mentioning the project folder (`Synapse-itf-Dev`, `synapse_artifacts`) makes the agent pick the right project immediately.

**1. Implement a Jira ticket end to end**
- Agent: **Data Engineering Orchestrator**
- Prompt: `Implement GRAVITY-3101 in Synapse-itf-Dev`
- What happens: shows the ticket description -> checks lineage -> routes to the layer agent -> converts the target script to an editable `.sql`/`.ipynb` -> shows the diff -> asks `Approve conversion back to Synapse JSON? (yes/no)`.

**2. Add a column through the layers**
- Agent: **Data Engineering Orchestrator**
- Prompt: `Add column Projektleiter from dwh_stg.T_IMPORT_PAF_WA_Stammdaten_R4 to dbo.T_DIM_10_Werksauftrag and its load procedure in Synapse-itf-Dev`
- What happens: verifies the column exists in staging (otherwise proposes the upstream change first) -> updates core DDL and `P_DIM_10_Werksauftrag` -> lists reporting objects that may need it.

**3. Create a new reporting object**
- Agent: **Data Engineering Orchestrator**
- Prompt: `Create rpt.P_R_Project_Budget_Summary on dbo.T_IMPORT_PAF_Projekteinnahmen_neuesteDaten, following P_R_WA_Dashboard, and register it in rpt.SP_Master_Core_to_Reporting`
- What happens: checks for an existing object -> drafts a new SQL script in the project's folder convention -> asks for approval before creating the JSON.

**4. Onboard a new feed or source**
- Agent: **Data Engineering Orchestrator**
- Prompt: `Onboard new Adastra file PAF_Kostenplanung_R4 into landing, curated, and staging in Synapse-itf-Dev`
- What happens: Orchestration Agent checks if existing pipelines/`feed_list`/metadata can be reused before proposing a new pipeline.

**5. Impact analysis before a change**
- Agent: **Lineage Impact Agent**
- Prompt: `What is downstream of dwh.T_IMPORT_PAF_WA_Uebersicht_R4?`
- What happens: reads `.lineage/finance/lineage.json` and lists affected core, reporting, and gold objects with file paths.

**6. Fix a notebook**
- Agent: **Synapse Platform Agent**
- Prompt: `In Synapse-itf-Dev/notebook/NB_bronze_to_silver.json, add a null check on Projektnummer before the SCD2 merge`
- What happens: converts only that notebook to `.ipynb`, edits the cell, shows the diff, converts back after `yes`.

**7. Raise the pull request**
- First: `git -C Synapse-itf-Dev checkout -b feature/GRAVITY-3101`
- Prompt: `/raise-pr` with title `GRAVITY-3101 Add Projektleiter to Werksauftrag`
- What happens: commits only `Synapse-itf-Dev/**`, pushes, opens the PR against `Main-DEV`; never approves or merges.

**8. Documentation**
- Agent: **Confluence**
- Prompts: `Summarize <page-url>` (read-only) or `Append a section "GRAVITY-3101 changes" to page <page-id>` (shows the exact change and waits for your approval).

**9. Onboard a new repo**
- Clone it into the workspace, then prompt: `/init-project-profile` with name `Controlling` -> answer the questions -> approve.

## Never commit
`.env`, `.verify_env/`, `.synapse_work/`, `.synapse_index/`, `.project_scan/`, `.lineage/`

## Troubleshooting
| Problem | Fix |
|---|---|
| Jira/Confluence tools missing | Check `.env` and the Python path in `.vscode/mcp.json`; reload window |
| Agent not visible | Reload window; confirm agent mode is on |
| Agent asks "which project?" | Mention the folder or file, e.g. `Synapse-itf-Dev/...`, or add the project label to the Jira ticket (`GIE` = Finance, `Gravity_Platform` = O&S) |
| Clone fails | Re-authenticate via Git Credential Manager with your Azure DevOps account |
| Agent cannot run commands | Enable the terminal tool or run the shown command yourself |
