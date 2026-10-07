from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = WORKSPACE_ROOT / "scripts" / "start-mcp-atlassian.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch a Jira issue through the local Atlassian MCP server.")
    parser.add_argument("issue_key", help="Jira issue key, for example GRAVITY-2773")
    parser.add_argument("--comment-limit", type=int, default=10, help="Maximum number of comments to request")
    parser.add_argument("--raw", action="store_true", help="Print the raw tool response as JSON")
    return parser.parse_args()


def compact_issue(payload: dict) -> dict:
    status = payload.get("status")
    assignee = payload.get("assignee")
    reporter = payload.get("reporter")
    priority = payload.get("priority")
    issue_type = payload.get("issuetype")
    parent = payload.get("parent")

    return {
        "key": payload.get("key"),
        "summary": payload.get("summary"),
        "status": status.get("name") if isinstance(status, dict) else status,
        "assignee": assignee.get("displayName") if isinstance(assignee, dict) else assignee,
        "reporter": reporter.get("displayName") if isinstance(reporter, dict) else reporter,
        "priority": priority.get("name") if isinstance(priority, dict) else priority,
        "issueType": issue_type.get("name") if isinstance(issue_type, dict) else issue_type,
        "labels": payload.get("labels") or [],
        "parent": parent,
        "description": payload.get("description"),
        "comments": payload.get("comments") or [],
        "transitions": payload.get("transitions") or [],
    }


async def fetch_issue(issue_key: str, comment_limit: int) -> dict:
    server = StdioServerParameters(command=sys.executable, args=[str(LAUNCHER)])
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(
                "jira_get_issue",
                {
                    "issue_key": issue_key,
                    "fields": "summary,status,assignee,reporter,priority,issuetype,labels,parent,description,comment",
                    "include": "comments,transitions",
                    "use_display_names": True,
                    "comment_limit": comment_limit,
                },
            )

    text_parts = [item.text for item in result.content if getattr(item, "text", None)]
    raw_text = "\n".join(text_parts)
    if result.isError:
        raise RuntimeError(raw_text or f"jira_get_issue failed for {issue_key}")
    return json.loads(raw_text)


def main() -> int:
    args = parse_args()
    payload = asyncio.run(fetch_issue(args.issue_key, args.comment_limit))
    output = payload if args.raw else compact_issue(payload)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())