from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = WORKSPACE_ROOT / ".env"
SERVER_CANDIDATES = [
    WORKSPACE_ROOT / ".new_env" / "Scripts" / "mcp-atlassian.exe",
    WORKSPACE_ROOT / ".verify_env" / "Scripts" / "mcp-atlassian.exe",
]


def load_env_file(env_file: Path) -> None:
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ[key] = value


def normalize_jira_token() -> None:
    jira_token = os.environ.get("JIRA_TOKEN")
    if not jira_token:
        return
    if os.environ.get("JIRA_PERSONAL_TOKEN") or os.environ.get("JIRA_API_TOKEN"):
        return

    jira_url = os.environ.get("JIRA_URL", "").lower()
    token_name = "JIRA_API_TOKEN" if "atlassian.net" in jira_url or "jira.com" in jira_url else "JIRA_PERSONAL_TOKEN"
    os.environ[token_name] = jira_token

def normalize_confluence_token() -> None:
    conf_token = os.environ.get("CONFLUENCE_TOKEN")
    if not conf_token:
        return
    if os.environ.get("CONFLUENCE_PERSONAL_TOKEN") or os.environ.get("CONFLUENCE_API_TOKEN"):
        return

    conf_url = os.environ.get("CONFLUENCE_URL", "").lower()
    token_name = "CONFLUENCE_API_TOKEN" if "atlassian.net" in conf_url else "CONFLUENCE_PERSONAL_TOKEN"
    os.environ[token_name] = conf_token


def resolve_server_path() -> Path:
    for candidate in SERVER_CANDIDATES:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Could not find mcp-atlassian.exe in .new_env or .verify_env.")


def main() -> int:
    load_env_file(ENV_FILE)
    normalize_jira_token()
    normalize_confluence_token()
    server_path = resolve_server_path()
    completed = subprocess.run([str(server_path), *sys.argv[1:]], check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())