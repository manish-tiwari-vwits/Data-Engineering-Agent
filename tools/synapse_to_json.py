#!/usr/bin/env python3
"""
synapse_to_json.py  --  REVERSE converter (edited file -> Synapse Git JSON)
==========================================================================
After you edit a .sql or .ipynb locally, this writes your changes BACK into
the original Synapse artifact JSON *in place*, so publishing / committing
reflects your edits.

WHY "in place / template" matters
---------------------------------
A Synapse JSON artifact carries platform metadata you must NOT lose:
    - notebooks: bigDataPool, sessionProperties, a365ComputeOptions, folder
    - sqlscripts: currentConnection (pool + database), folder, type
This tool loads the ORIGINAL json, replaces ONLY the query / cell sources,
and keeps everything else identical -> minimal, clean Git diff.

USAGE
-----
    # SQL: inject edited .sql back into its Synapse json
    python synapse_to_json.py MyScript.sql --json path/to/MyScript.json

    # Notebook: inject edited .ipynb back into its Synapse json
    python synapse_to_json.py MyNotebook.ipynb --json path/to/MyNotebook.json

    # If the original json sits in a repo folder, auto-find it by name:
    python synapse_to_json.py MyScript.sql   --repo .
    python synapse_to_json.py MyNotebook.ipynb --repo .

    # Write to a new file instead of overwriting (safe preview):
    python synapse_to_json.py MyScript.sql --json MyScript.json --out MyScript.new.json

    # Batch a whole folder of edited files against a repo:
    python synapse_to_json.py ./converted --repo . --batch
"""

import argparse
import json
import sys
from pathlib import Path


# ----------------------------------------------------------------------
def find_original(name: str, repo: Path) -> Path | None:
    """Locate <name>.json anywhere under the repo (notebook/ or sqlscript/)."""
    hits = [p for p in repo.rglob(f"{name}.json")]
    # prefer ones that live under a notebook/ or sqlscript/ folder
    hits.sort(key=lambda p: (("sqlscript" not in p.parts and
                              "notebook" not in p.parts), len(p.parts)))
    return hits[0] if hits else None


# ----------------------------------------------------------------------
def inject_sql(sql_text: str, original: dict) -> dict:
    """Put edited SQL back into properties.content.query, keep the rest."""
    props = original.setdefault("properties", {})
    content = props.setdefault("content", {})
    # Synapse stores the query as a single string with \n escapes
    content["query"] = sql_text.rstrip("\n")
    return original


def inject_notebook(nb: dict, original: dict) -> dict:
    """Rebuild properties.cells[] from the edited .ipynb, keep pool/session/etc."""
    props = original.setdefault("properties", {})

    new_cells = []
    for c in nb.get("cells", []):
        source = c.get("source", [])
        if isinstance(source, str):
            source = source.splitlines(keepends=True)

        cell = {
            "cell_type": c.get("cell_type", "code"),
            "metadata": c.get("metadata", {}) or {},
            "source": source,
        }
        if cell["cell_type"] == "code":
            # Synapse keeps these but they should be clean on commit
            cell["outputs"] = []
            cell["execution_count"] = None
        new_cells.append(cell)

    props["cells"] = new_cells
    # keep nbformat in sync if the edited file bumped it
    if "nbformat" in nb:
        props["nbformat"] = nb["nbformat"]
    if "nbformat_minor" in nb:
        props["nbformat_minor"] = nb["nbformat_minor"]
    return original


# ----------------------------------------------------------------------
def process_one(edited: Path, json_path: Path, out_path: Path):
    original = json.loads(json_path.read_text(encoding="utf-8"))

    if edited.suffix.lower() == ".sql":
        updated = inject_sql(edited.read_text(encoding="utf-8"), original)
        kind = "sqlscript"
    elif edited.suffix.lower() == ".ipynb":
        nb = json.loads(edited.read_text(encoding="utf-8"))
        updated = inject_notebook(nb, original)
        kind = "notebook"
    else:
        print(f"  [skip] {edited.name}: not a .sql or .ipynb")
        return

    # Synapse Git files are indent=4, keep that so diffs stay minimal
    out_path.write_text(
        json.dumps(updated, ensure_ascii=False, indent=4), encoding="utf-8"
    )
    print(f"  [ok] {kind:9s} {edited.name:40s} -> {out_path}")


# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Inject edited .sql/.ipynb back into Synapse artifact JSON.")
    ap.add_argument("path", help="edited .sql / .ipynb file, or a folder with --batch")
    ap.add_argument("--json", help="the ORIGINAL Synapse .json to update")
    ap.add_argument("--repo", help="repo root to auto-locate the original .json by name")
    ap.add_argument("--out", help="write result here instead of overwriting the .json")
    ap.add_argument("--batch", action="store_true",
                    help="path is a folder; process every .sql/.ipynb in it")
    args = ap.parse_args()

    src = Path(args.path).resolve()
    if not src.exists():
        sys.exit(f"path not found: {src}")

    # collect edited files
    if args.batch or src.is_dir():
        edited_files = [p for p in src.rglob("*")
                        if p.suffix.lower() in (".sql", ".ipynb")]
        if not edited_files:
            sys.exit(f"no .sql/.ipynb found under {src}")
    else:
        edited_files = [src]

    repo = Path(args.repo).resolve() if args.repo else None

    print(f"Updating {len(edited_files)} artifact(s):\n")
    for edited in edited_files:
        # resolve the original json for this edited file
        if args.json and not (args.batch or src.is_dir()):
            json_path = Path(args.json).resolve()
        elif repo:
            found = find_original(edited.stem, repo)
            if not found:
                print(f"  [ERROR] no {edited.stem}.json found under repo {repo}")
                continue
            json_path = found
        else:
            sys.exit("provide --json (single file) or --repo (auto-locate).")

        if not json_path.exists():
            print(f"  [ERROR] original json not found: {json_path}")
            continue

        out_path = Path(args.out).resolve() if (args.out and len(edited_files) == 1) \
            else json_path            # overwrite original by default
        process_one(edited, json_path, out_path)

    print("\nDone. Commit the updated .json to your Synapse Git branch to publish.")


if __name__ == "__main__":
    main()
