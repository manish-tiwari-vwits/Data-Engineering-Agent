# Packaging And Sharing The Gravity Agents

This workspace can be shared as a team-consumable VS Code Copilot agents package. The recommended model is to keep it in a Git repository and ask teammates to clone it, open it in VS Code, configure their own local secrets, and reload VS Code.

## What To Share

Include these files and folders:

- `.github/agents/` - custom Copilot agent definitions.
- `.github/instructions/` - layer and workflow instructions used by the agents.
- `.github/prompts/` - reusable prompt commands such as PR preparation.
- `.github/copilot-instructions.md` - always-on workspace guidance.
- `.github/AGENTS.md` - workspace agent map.
- `.vscode/mcp.json` - MCP server configuration for Jira and Confluence.
- `.vscode/settings.json` - VS Code/Copilot settings used by this workspace.
- `README.md` - setup and operating guide.
- `requirements.txt` - Python dependencies.
- `scripts/` - MCP startup scripts.
- `tools/` and `synapse_roundtrip.py` - Synapse artifact helper tooling.
- `docs/reference/` - shared reference material needed by the agents.

Do not share or commit these local-only files and folders:

- `.env` - contains local Jira/Confluence tokens.
- `.verify_env/`, `.venv/`, or `venv/` - local Python virtual environments.
- `.synapse_work/` - temporary roundtrip edit output.
- `.synapse_index/` - generated local lookup index.
- `__pycache__/`, `.pytest_cache/`, and other generated caches.
- Any personal token, password, browser export, or machine-specific credential file.

## Recommended Package: Git Repository

Create or use a team Git repository for this workspace. This is the best option because agent updates, instruction changes, prompts, scripts, and documentation can be reviewed and versioned.

Suggested repository name:

```text
gravity-os-agents
```

Package flow:

```powershell
git init
git add .github .vscode README.md requirements.txt scripts tools docs synapse_roundtrip.py .gitignore
git commit -m "Package Gravity O&S Copilot agents"
git remote add origin <team-repo-url>
git push -u origin main
```

Before pushing, confirm `.env` and virtual environment folders are not staged:

```powershell
git status --short
```

## Alternative Package: Zip File

Use a zip only for a one-time handoff. Git is better for ongoing team use.

From the workspace root:

```powershell
Compress-Archive `
  -Path .github,.vscode,README.md,requirements.txt,scripts,tools,docs,synapse_roundtrip.py,.gitignore `
  -DestinationPath gravity-os-agents-package.zip `
  -Force
```

Do not add `.env`, `.verify_env`, `.synapse_work`, `.synapse_index`, or `synapse_artifacts` to the zip unless there is a separate approved reason.

## How Teammates Consume The Agents

Share these steps with each teammate.

### 1. Clone And Open

```powershell
git clone <team-repo-url> gravity-os-agents
cd gravity-os-agents
code .
```

### 2. Install Prerequisites

They need:

- Windows.
- VS Code.
- GitHub Copilot Chat with agent mode enabled.
- Git.
- Python 3.10 or newer.
- PowerShell.
- Access to Jira/Confluence and the Synapse artifacts repository.

### 3. Create Local Python Environment

```powershell
python -m venv .verify_env
.\.verify_env\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. Create Local `.env`

Each teammate creates their own `.env` in the workspace root.

```powershell
@"
JIRA_URL=...
JIRA_TOKEN=...
CONFLUENCE_URL=...
CONFLUENCE_TOKEN=...
"@ | Set-Content .env
```

Do not send token values in chat, email, screenshots, or committed files.

### 5. Clone Synapse Artifacts Separately

If the agents will edit or inspect Synapse artifacts, clone the Synapse artifacts repository into the workspace root:

```powershell
git clone https://Volkswagen-AG@dev.azure.com/Volkswagen-AG/IT-RA/_git/synapse_artifacts synapse_artifacts
```

The agent package and the Synapse artifact repo should usually stay separate. The package contains the agent operating system; `synapse_artifacts/` contains implementation source.

### 6. Reload VS Code

In VS Code command palette:

```text
Developer: Reload Window
```

### 7. Verify Agent Availability

In Copilot Chat agent mode, verify these agents appear or can be invoked:

- `Data Engineering Orchestrator`
- `Jira`
- `Confluence`
- `Lineage Impact Agent`
- `Synapse Platform Agent`, `Fabric Platform Agent`, `Databricks Platform Agent`, `AWS Platform Agent`
- `Pull Request Agent`

Stage agents (`Ingestion`, `Transformation`, `Data Modeling`, `Serving`, `Orchestration`) are subagents invoked by the orchestrator.

Then run read-only checks:

```text
Use the Jira agent to fetch <known-ticket-key> read-only and show the description.
```

```text
Use the Confluence agent to fetch <known-page-url> read-only and summarize it.
```

## Team Update Workflow

When you change agents or instructions:

1. Edit files under `.github/agents/`, `.github/instructions/`, `.github/prompts/`, or `.github/copilot-instructions.md`.
2. Check YAML frontmatter in changed `.agent.md`, `.instructions.md`, and `.prompt.md` files.
3. Test the agent routing in a local VS Code window.
4. Commit the package changes to the team repo.
5. Ask teammates to run `git pull` and reload VS Code.

## Consumption Modes

Use one of these patterns:

- Team workspace package: teammates clone this repo and open it directly. This is the recommended mode for Gravity O&S work.
- Copy into an existing repo: copy `.github/agents`, `.github/instructions`, `.github/prompts`, `.github/copilot-instructions.md`, and `.github/AGENTS.md` into another repository. Use this only when that repository should permanently own the same agent behavior.
- Personal install: copy selected `.agent.md`, `.instructions.md`, or `.prompt.md` files into the user's VS Code prompts folder. Use this for personal experiments, not the official team flow.

## Quick Share Message

Send this to teammates:

```text
Clone the Gravity O&S agents workspace, open it in VS Code, create your local .env with your own Jira/Confluence tokens, create .verify_env, install requirements.txt, reload VS Code, and use the Data Engineering Orchestrator in Copilot Chat agent mode. Do not commit .env, .verify_env, .synapse_work, or .synapse_index.

Setup guide: docs/team-agent-packaging.md
```