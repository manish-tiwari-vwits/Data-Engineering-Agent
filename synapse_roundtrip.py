#!/usr/bin/env python3
"""
synapse_roundtrip.py
--------------------
Single-file, TWO-WAY converter for Synapse Git artifacts, designed to be
driven by a GitHub Copilot custom agent.

Workflow it supports:
  1. to-editable : Synapse JSON  ->  editable .ipynb / .sql   (edit-friendly)
  2. to-json     : edited .ipynb / .sql  ->  Synapse JSON      (publish-safe)
    3. new-sqlscript : create editable .sql first, then to-json after review

Key guarantee: `to-json` REUSES the ORIGINAL .json as a template and only
replaces the notebook cell sources (properties.cells[].source) or the SQL
text (properties.content.query). Every Synapse-specific property
(bigDataPool, sessionProperties, folder, metadata, sessionProperties, etc.)
is preserved byte-for-byte, so Synapse Studio re-imports cleanly.

--------------------------------------------------------------------------
USAGE
--------------------------------------------------------------------------
# JSON -> editable (auto-detects notebook vs sqlscript)
python synapse_roundtrip.py to-editable --file notebook/MyNb.json
python synapse_roundtrip.py to-editable --file sqlscript/MyScript.json
    # -> writes .synapse_work/MyNb.ipynb  (and remembers the source json)

# editable -> JSON (writes back onto the ORIGINAL json, in place)
python synapse_roundtrip.py to-json --file .synapse_work/MyNb.ipynb
python synapse_roundtrip.py to-json --file .synapse_work/MyScript.sql
    # -> updates notebook/MyNb.json in place

# new SQL artifact -> editable first, JSON later after approval
python synapse_roundtrip.py new-sqlscript --root <artifact_root> --database <db> --pool <pool> --name MyNewScript --folder Core
python synapse_roundtrip.py to-json --file .synapse_work/MyNewScript.sql
    # -> creates <artifact_root>/sqlscript/MyNewScript.json

Options:
  --workdir DIR   where editable files live (default: .synapse_work)
  --out FILE      explicit output path (overrides defaults)
--------------------------------------------------------------------------
"""

import argparse
import json
import sys
from pathlib import Path

WORKDIR_DEFAULT = ".synapse_work"
# sidecar file that maps an editable file back to its source json
MAP_NAME = ".roundtrip-map.json"


# ======================================================================
# detection
# ======================================================================
def detect_kind(data: dict) -> str:
    props = data.get("properties", data)
    if "cells" in props or props.get("nbformat"):
        return "notebook"
    if "content" in props and "query" in props.get("content", {}):
        return "sqlscript"
    # fall back on folder name / type hints
    if props.get("type") in ("SqlQuery",):
        return "sqlscript"
    raise ValueError("Cannot detect artifact type (not notebook or sqlscript).")


# ======================================================================
# JSON -> editable
# ======================================================================
def json_to_ipynb(data: dict) -> dict:
    props = data.get("properties", data)
    lang = props.get("metadata", {}).get("language_info", {}).get("name", "python")
    nb = {
        "nbformat": props.get("nbformat", 4),
        "nbformat_minor": props.get("nbformat_minor", 2),
        "metadata": {
            "language_info": {"name": lang},
            "kernelspec": {
                "name": "synapse_pyspark" if lang == "python" else lang,
                "display_name": lang, "language": lang,
            },
        },
        "cells": [],
    }
    for cell in props.get("cells", []):
        src = cell.get("source", [])
        if isinstance(src, str):
            src = src.splitlines(keepends=True)
        c = {
            "cell_type": cell.get("cell_type", "code"),
            "metadata": cell.get("metadata", {}) or {},
            "source": src,
        }
        if c["cell_type"] == "code":
            c["outputs"] = []
            c["execution_count"] = None
        nb["cells"].append(c)
    return nb


def json_to_sql(data: dict) -> str:
    props = data.get("properties", data)
    q = props.get("content", {}).get("query", "")
    if isinstance(q, list):
        q = "".join(q)
    if q and not q.endswith("\n"):
        q += "\n"
    return q


# ======================================================================
# editable -> JSON  (inject back into ORIGINAL template)
# ======================================================================
def ipynb_into_json(original: dict, nb: dict) -> dict:
    """Replace only cell sources/types in the original Synapse notebook json."""
    props = original.setdefault("properties", {})
    new_cells = []
    for cell in nb.get("cells", []):
        src = cell.get("source", [])
        if isinstance(src, str):
            src = src.splitlines(keepends=True)
        entry = {
            "cell_type": cell.get("cell_type", "code"),
            "metadata": cell.get("metadata", {}) or {},
            "source": src,
        }
        if entry["cell_type"] == "code":
            entry["outputs"] = []
            entry["execution_count"] = None
        new_cells.append(entry)
    props["cells"] = new_cells
    return original


def sql_into_json(original: dict, sql_text: str) -> dict:
    """Replace only the query text in the original Synapse sqlscript json."""
    props = original.setdefault("properties", {})
    content = props.setdefault("content", {})
    content["query"] = sql_text
    return original


def new_sqlscript_json(name: str, sql_text: str, folder: str, database: str, pool: str, result_limit: int) -> dict:
    """Create a new Synapse SQL script artifact from reviewed editable SQL."""
    return {
        "name": name,
        "properties": {
            "folder": {
                "name": folder,
            },
            "content": {
                "query": sql_text,
                "metadata": {
                    "language": "sql",
                },
                "currentConnection": {
                    "databaseName": database,
                    "poolName": pool,
                },
                "resultLimit": result_limit,
            },
            "type": "SqlQuery",
        },
    }


# ======================================================================
# sidecar map helpers  (editable file  ->  source json path)
# ======================================================================
def load_map(workdir: Path) -> dict:
    p = workdir / MAP_NAME
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def save_map(workdir: Path, m: dict):
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / MAP_NAME).write_text(json.dumps(m, indent=2), encoding="utf-8")


# ======================================================================
# commands
# ======================================================================
def cmd_to_editable(args):
    src = Path(args.file).resolve()
    data = json.loads(src.read_text(encoding="utf-8"))
    kind = detect_kind(data)
    name = data.get("name", src.stem)
    workdir = Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    if kind == "notebook":
        out = Path(args.out) if args.out else workdir / f"{name}.ipynb"
        out.write_text(json.dumps(json_to_ipynb(data), ensure_ascii=False, indent=1),
                       encoding="utf-8")
    else:
        out = Path(args.out) if args.out else workdir / f"{name}.sql"
        out.write_text(json_to_sql(data), encoding="utf-8")

    m = load_map(workdir)
    m[out.name] = str(src)              # remember origin for the reverse trip
    save_map(workdir, m)

    print(f"[to-editable] {kind}: {src.name} -> {out}")
    print(f"[map] {out.name} -> {src}")
    return 0


def cmd_new_sqlscript(args):
    workdir = Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    out = Path(args.out).resolve() if args.out else workdir / f"{args.name}.sql"
    if args.target:
        target = Path(args.target)
    elif args.root:
        target = Path(args.root) / "sqlscript" / f"{args.name}.json"
    else:
        sys.exit("Pass --root <artifact_root> (from the project profile) or --target <path.json>.")
    target = target.resolve()

    if out.exists() and not args.overwrite:
        sys.exit(f"Editable file already exists: {out}. Pass --overwrite to replace it.")

    starter_sql = f"-- Draft SQL for new Synapse SQL script: {args.name}\n"
    out.write_text(starter_sql, encoding="utf-8")

    m = load_map(workdir)
    m[out.name] = {
        "mode": "new-sqlscript",
        "target": str(target),
        "name": args.name,
        "folder": args.folder,
        "database": args.database,
        "pool": args.pool,
        "resultLimit": args.result_limit,
    }
    save_map(workdir, m)

    print(f"[new-sqlscript] editable: {out}")
    print(f"[map] {out.name} -> {target}")
    return 0


def cmd_to_json(args):
    edit = Path(args.file).resolve()
    workdir = Path(args.workdir).resolve()
    m = load_map(workdir)
    map_entry = m.get(edit.name)

    # resolve original json: explicit --original wins, else sidecar map
    if args.original:
        origin = Path(args.original).resolve()
    elif isinstance(map_entry, str):
        origin = Path(map_entry).resolve()
    elif isinstance(map_entry, dict) and map_entry.get("mode") == "new-sqlscript":
        origin = None
    else:
        sys.exit(f"No origin json known for {edit.name}. "
                 f"Pass --original <path-to-original.json>.")

    if origin is None:
        if edit.suffix != ".sql":
            sys.exit("New artifact creation currently supports .sql files only.")
        out = Path(args.out).resolve() if args.out else Path(map_entry["target"]).resolve()
        if out.exists() and not args.overwrite:
            sys.exit(f"Target JSON already exists: {out}. Pass --overwrite to replace it.")
        updated = new_sqlscript_json(
            map_entry["name"],
            edit.read_text(encoding="utf-8"),
            map_entry["folder"],
            map_entry["database"],
            map_entry["pool"],
            map_entry["resultLimit"],
        )
    else:
        original = json.loads(origin.read_text(encoding="utf-8"))
        if edit.suffix == ".ipynb":
            nb = json.loads(edit.read_text(encoding="utf-8"))
            updated = ipynb_into_json(original, nb)
        elif edit.suffix == ".sql":
            updated = sql_into_json(original, edit.read_text(encoding="utf-8"))
        else:
            sys.exit(f"Unsupported editable type: {edit.suffix}")
        out = Path(args.out).resolve() if args.out else origin

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(updated, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"[to-json] {edit.name} -> {out}  (Synapse metadata preserved)")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Two-way Synapse artifact converter.")
    ap.add_argument("--workdir", default=WORKDIR_DEFAULT)
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("to-editable", help="Synapse JSON -> .ipynb/.sql")
    a.add_argument("--file", required=True)
    a.add_argument("--out")
    a.set_defaults(func=cmd_to_editable)

    n = sub.add_parser("new-sqlscript", help="Create editable .sql for a new Synapse SQL script")
    n.add_argument("--name", required=True)
    n.add_argument("--folder", required=True, help="Synapse Studio folder name for the SQL script")
    n.add_argument("--root", help="Synapse artifact root; target becomes <root>/sqlscript/<name>.json")
    n.add_argument("--target", help="Explicit target JSON path (overrides --root)")
    n.add_argument("--database", required=True, help="SQL pool database name (profile platform.sql_pool)")
    n.add_argument("--pool", required=True, help="SQL pool name (profile platform.sql_pool)")
    n.add_argument("--result-limit", type=int, default=5000)
    n.add_argument("--out")
    n.add_argument("--overwrite", action="store_true")
    n.set_defaults(func=cmd_new_sqlscript)

    b = sub.add_parser("to-json", help="edited .ipynb/.sql -> Synapse JSON")
    b.add_argument("--file", required=True)
    b.add_argument("--original", help="original json (if not in sidecar map)")
    b.add_argument("--out")
    b.add_argument("--overwrite", action="store_true", help="Allow replacing a new target JSON artifact")
    b.set_defaults(func=cmd_to_json)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
