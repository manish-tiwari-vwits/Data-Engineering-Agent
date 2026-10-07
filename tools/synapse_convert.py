#!/usr/bin/env python3
"""
synapse_convert.py  (optimized, SQL-safe)
-----------------------------------------
Convert Synapse Git artifacts (proprietary JSON) into real files:
    notebook  JSON -> *.ipynb   (valid nbformat 4)
    sqlscript JSON -> *.sql     (raw T-SQL from properties.content.query)

It accepts EITHER a single .json file OR a folder, and AUTO-DETECTS the
artifact type from the JSON content -- you do NOT have to pre-sort files
into notebook/ and sqlscript/ folders.

Pipelines / linked services / datasets / triggers are detected and skipped
(they cannot be turned into .sql or .ipynb).

WHAT'S NEW / OPTIMIZED
----------------------
  * FASTER: folders are converted in PARALLEL (thread pool) and all regexes
    are pre-compiled once -- large repos convert several times faster.
  * SAFE CLEANUP (on by default): strips leftover HTML markup (<br>, <p>,
    <div>, <strong>, <h1>..<h6>, ...) and decodes HTML entities (&gt; &amp;)
    in the EXTRACTED .sql / .ipynb only. The Synapse JSON is never touched,
    so re-import stays clean.
      - SQL comparison operators (>, <, <>, >=) are GUARANTEED preserved.
        The tag matcher only removes WELL-FORMED HTML tags: the tag name must
        sit immediately after "<" (no space) and any attributes must be
        QUOTED (name="..."). Patterns like  a < b AND c > d  or  a<b AND c>d
        can therefore never be mistaken for a tag.
      - Code notebook cells are NEVER cleaned (PySpark/SQL stays byte-exact).
      - Use --no-clean to disable, or --clean to force it on.

USAGE
-----
    # single file (output goes next to it, or use --out)
    python synapse_convert.py p_UpdateExternalTablesForToday.json
    python synapse_convert.py MyNotebook.json --out ./converted

    # a whole folder (recurses)
    python synapse_convert.py . --out ./converted
    python synapse_convert.py ./sqlscript --out ./converted

    # disable HTML cleanup / control parallelism
    python synapse_convert.py . --out ./converted --no-clean
    python synapse_convert.py . --out ./converted --workers 16

    # legacy flag form still works
    python synapse_convert.py --src . --out ./converted
"""

import argparse
import html
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


# ----------------------------------------------------------------------
# Cleanup  (safe, whitelist-based -- compiled ONCE at import time)
# ----------------------------------------------------------------------
# Only these real HTML tags are removed.
_HTML_TAGS = (
    "br", "p", "div", "span", "strong", "b", "em", "i", "u",
    "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li",
    "table", "thead", "tbody", "tr", "td", "th", "pre", "code", "hr",
)
# <br>, <br/>, <br />  ->  newline
_BR_RE = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
# WELL-FORMED tag matcher -- SQL-safe:
#   * tag name immediately after "<" (no space)  -> "< b" can't match
#   * attributes, if any, MUST be quoted name="..."/name='...'
#     -> "<b AND c>" (bare words) can't match, so SQL is never touched.
_TAG_RE = re.compile(
    r'</?(?:%s)\b'                                   # <tag  or  </tag
    r'(?:\s+[a-zA-Z_:][-\w:.]*\s*=\s*(?:"[^"]*"|\'[^\']*\'))*'  # quoted attrs only
    r'\s*/?>'                                        # optional self-close, then >
    % "|".join(_HTML_TAGS),
    re.IGNORECASE,
)
# collapse 3+ blank lines that cleanup can leave behind
_MULTI_NL_RE = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    """Strip WELL-FORMED HTML markup and decode entities -- SQL operator safe."""
    if not text or ("<" not in text and "&" not in text):
        return text                      # fast path: nothing to do
    text = _BR_RE.sub("\n", text)        # <br> -> newline first
    text = _TAG_RE.sub("", text)         # drop only well-formed whitelisted tags
    text = html.unescape(text)           # &gt; &lt; &amp; &nbsp; -> chars
    text = _MULTI_NL_RE.sub("\n\n", text)
    return text


# ----------------------------------------------------------------------
# Detection
# ----------------------------------------------------------------------
def detect_type(data: dict) -> str:
    """Return 'notebook', 'sqlscript', 'pipeline', 'other', or 'unknown'."""
    props = data.get("properties", data)
    if "cells" in props:
        return "notebook"
    if isinstance(props.get("content"), dict) and "query" in props["content"]:
        return "sqlscript"
    if "activities" in props:
        return "pipeline"
    if any(k in props for k in ("typeProperties", "linkedServiceName",
                                "runtimeState", "schema")):
        return "other"          # linked service / dataset / trigger / dataflow
    return "unknown"


# ----------------------------------------------------------------------
# Converters
# ----------------------------------------------------------------------
def convert_notebook(data: dict, clean: bool = True) -> dict:
    props = data.get("properties", data)
    lang = props.get("metadata", {}).get("language_info", {}).get("name", "python")

    ipynb = {
        "nbformat": props.get("nbformat", 4),
        "nbformat_minor": props.get("nbformat_minor", 2),
        "metadata": {
            "language_info": {"name": lang},
            "kernelspec": {
                "name": "synapse_pyspark" if lang == "python" else lang,
                "display_name": lang,
                "language": lang,
            },
        },
        "cells": [],
    }

    cells_out = ipynb["cells"]
    for cell in props.get("cells", []):
        cell_type = cell.get("cell_type", "code")
        source = cell.get("source", [])
        if isinstance(source, list):
            source = "".join(source)
        # Only clean markdown/raw cells -- NEVER touch code, so PySpark/SQL
        # inside code cells stays byte-for-byte intact.
        if clean and cell_type != "code":
            source = clean_text(source)
        source = source.splitlines(keepends=True)

        new = {
            "cell_type": cell_type,
            "metadata": cell.get("metadata", {}) or {},
            "source": source,
        }
        if cell_type == "code":
            new["outputs"] = []
            new["execution_count"] = None
        cells_out.append(new)
    return ipynb


def convert_sqlscript(data: dict, clean: bool = True) -> str:
    props = data.get("properties", data)
    query = props.get("content", {}).get("query", "")
    if isinstance(query, list):
        query = "".join(query)
    if clean:
        query = clean_text(query)        # SQL-safe: comparison operators preserved
    if query and not query.endswith("\n"):
        query += "\n"
    return query


# ----------------------------------------------------------------------
# IO helpers
# ----------------------------------------------------------------------
def synapse_folder(data: dict) -> str:
    props = data.get("properties", data)
    return (props.get("folder", {}) or {}).get("name", "") or ""


def convert_one(jf: Path, out_root: Path, keep_tree: bool, clean: bool) -> tuple:
    """Returns (kind, message) -- printing is done by the caller (thread-safe)."""
    try:
        data = json.loads(jf.read_text(encoding="utf-8"))
    except Exception as e:
        return "error", f"  [ERROR] {jf.name}: bad JSON ({e})"

    kind = detect_type(data)
    name = data.get("name", jf.stem)

    if kind == "notebook":
        sub = synapse_folder(data) if keep_tree else ""
        tgt = out_root / "notebook" / sub
        tgt.mkdir(parents=True, exist_ok=True)
        f = tgt / f"{name}.ipynb"
        f.write_text(json.dumps(convert_notebook(data, clean), ensure_ascii=False, indent=1),
                     encoding="utf-8")
        return "notebook", f"  [ok]  notebook   {jf.name:45s} -> {f.relative_to(out_root)}"

    if kind == "sqlscript":
        sub = synapse_folder(data) if keep_tree else ""
        tgt = out_root / "sql" / sub
        tgt.mkdir(parents=True, exist_ok=True)
        f = tgt / f"{name}.sql"
        f.write_text(convert_sqlscript(data, clean), encoding="utf-8")
        return "sqlscript", f"  [ok]  sqlscript  {jf.name:45s} -> {f.relative_to(out_root)}"

    if kind == "pipeline":
        return "pipeline", f"  [skip] pipeline   {jf.name:45s} (no .sql/.ipynb equivalent)"

    return kind, f"  [skip] {kind:10s} {jf.name:45s} (not a notebook or sql script)"


# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Convert Synapse Git JSON to .ipynb / .sql")
    # positional path is optional so the legacy --src form still works
    ap.add_argument("path", nargs="?", help="a .json file OR a folder to scan")
    ap.add_argument("--src", help="(legacy) same as positional path")
    ap.add_argument("--out", help="output dir (default: ./converted next to input)")
    ap.add_argument("--flat", action="store_true",
                    help="do NOT recreate the Synapse folder hierarchy")
    ap.add_argument("--workers", type=int, default=0,
                    help="parallel workers for folders (0 = auto)")
    clean_grp = ap.add_mutually_exclusive_group()
    clean_grp.add_argument("--clean", dest="clean", action="store_true", default=True,
                           help="strip leftover HTML markup / decode entities (default ON)")
    clean_grp.add_argument("--no-clean", dest="clean", action="store_false",
                           help="disable HTML cleanup (raw passthrough)")
    args = ap.parse_args()

    target = args.path or args.src
    if not target:
        ap.error("give a .json file or a folder, e.g.  python synapse_convert.py MyFile.json")

    p = Path(target).resolve()
    if not p.exists():
        sys.exit(f"path not found: {p}")

    out_root = Path(args.out).resolve() if args.out else (
        (p.parent if p.is_file() else p) / "converted"
    )
    out_root.mkdir(parents=True, exist_ok=True)
    keep_tree = not args.flat
    clean = args.clean

    files = [p] if p.is_file() else sorted(p.rglob("*.json"))
    if not files:
        sys.exit(f"no .json files found under {p}")

    print(f"Converting {len(files)} file(s) -> {out_root}"
          f"  (cleanup: {'on' if clean else 'off'})\n")

    tally = {}

    def _run(jf):
        return convert_one(jf, out_root, keep_tree, clean)

    # Single file: no thread overhead. Folder: parallelize (I/O bound).
    if len(files) == 1:
        results = [_run(files[0])]
    else:
        workers = args.workers or min(32, (len(files) + 3) // 4 + 4)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(_run, files))

    for kind, msg in results:
        print(msg)
        tally[kind] = tally.get(kind, 0) + 1

    print("\nDone. Summary:")
    for k in sorted(tally):
        print(f"  {k:10s}: {tally[k]}")


if __name__ == "__main__":
    main()
