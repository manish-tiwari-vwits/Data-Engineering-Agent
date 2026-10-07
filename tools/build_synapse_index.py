#!/usr/bin/env python3
"""Build lightweight lookup indexes for Synapse Git artifacts.

The generated files contain only artifact metadata, not SQL query text or
notebook cell content. Agents should read these indexes first to resolve a
candidate path before opening large Synapse JSON files.
Usage:
  python tools/build_synapse_index.py --root <artifact_root> --out <index_dir>
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT
OUT_DIR = ROOT / ".synapse_index"


def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "name": path.stem,
            "path": path.relative_to(ROOT).as_posix(),
            "error": str(exc),
        }


def collect_artifacts(kind: str, folder_name: str) -> list[dict]:
    base = ARTIFACT_ROOT / folder_name
    if not base.exists():
        return []

    entries = []
    for path in sorted(base.glob("*.json")):
        data = load_json(path)
        if not data:
            continue

        if "error" in data:
            entries.append(data | {"kind": kind, "synapseFolder": ""})
            continue

        props = data.get("properties", {}) or {}
        folder = (props.get("folder", {}) or {}).get("name", "") or ""
        content = props.get("content", {}) or {}
        connection = content.get("currentConnection", {}) or {}

        entry = {
            "name": data.get("name", path.stem),
            "path": path.relative_to(ROOT).as_posix(),
            "kind": kind,
            "synapseFolder": folder,
            "type": props.get("type", ""),
        }

        if kind == "sqlscript":
            entry["language"] = (content.get("metadata", {}) or {}).get("language", "sql")
            entry["databaseName"] = connection.get("databaseName", "")
            entry["poolName"] = connection.get("poolName", "")
        else:
            metadata = props.get("metadata", {}) or {}
            entry["language"] = (metadata.get("language_info", {}) or {}).get("name", "")

        entries.append(entry)
    return entries


def build_folder_index(sqlscripts: list[dict], notebooks: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for entry in sqlscripts + notebooks:
        grouped[(entry["kind"], entry.get("synapseFolder", ""))].append(
            {"name": entry["name"], "path": entry["path"]}
        )

    folders = []
    for (kind, folder), artifacts in sorted(grouped.items()):
        folders.append(
            {
                "kind": kind,
                "synapseFolder": folder,
                "count": len(artifacts),
                "artifacts": sorted(artifacts, key=lambda item: item["name"].lower()),
            }
        )
    return folders


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git_head(root: Path) -> str | None:
    for p in [root, *root.parents]:
        head = p / ".git" / "HEAD"
        if head.exists():
            ref = head.read_text().strip()
            if ref.startswith("ref: "):
                ref_file = p / ".git" / ref[5:]
                return ref_file.read_text().strip() if ref_file.exists() else ref[5:]
            return ref
        if p == ROOT:
            break
    return None


def main() -> int:
    global ARTIFACT_ROOT, OUT_DIR
    ap = argparse.ArgumentParser(description="Build Synapse artifact lookup indexes.")
    ap.add_argument("--root", required=True, help="Synapse artifact root, e.g. the profile's repository.artifact_root")
    ap.add_argument("--out", required=True, help="Index output folder, e.g. the profile's repository.index_dir")
    args = ap.parse_args()
    ARTIFACT_ROOT = (ROOT / args.root).resolve()
    OUT_DIR = (ROOT / args.out).resolve()
    if not ARTIFACT_ROOT.is_dir():
        raise SystemExit(f"Artifact root not found: {args.root}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    sqlscripts = collect_artifacts("sqlscript", "sqlscript")
    notebooks = collect_artifacts("notebook", "notebook")
    folders = build_folder_index(sqlscripts, notebooks)

    write_json(OUT_DIR / "sqlscripts.json", sqlscripts)
    write_json(OUT_DIR / "notebooks.json", notebooks)
    write_json(OUT_DIR / "folders.json", folders)

    out_rel = OUT_DIR.relative_to(ROOT).as_posix()
    summary = {
        # Agents compare these with the profile to detect a stale or foreign index.
        "artifactRoot": ARTIFACT_ROOT.relative_to(ROOT).as_posix(),
        "gitHead": git_head(ARTIFACT_ROOT),
        "sqlscripts": len(sqlscripts),
        "notebooks": len(notebooks),
        "folders": len(folders),
        "generatedFiles": [
            f"{out_rel}/sqlscripts.json",
            f"{out_rel}/notebooks.json",
            f"{out_rel}/folders.json",
        ],
    }
    write_json(OUT_DIR / "summary.json", summary)

    print(
        f"Indexed {summary['sqlscripts']} SQL scripts, "
        f"{summary['notebooks']} notebooks, {summary['folders']} folder groups."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())