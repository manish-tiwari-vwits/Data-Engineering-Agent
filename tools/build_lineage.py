#!/usr/bin/env python3
"""Table-level lineage from Synapse/ADF Git artifacts -> lineage.json, lineage_edges.csv, lineage.pdf.

Derived from script dependencies: stored procedures, views, external tables, ad-hoc SQL
scripts, notebooks, data flows, copy/script activities, and pipeline/trigger orchestration.
Granularity is per procedure/notebook: every table it reads feeds every table it writes.
Standard library only (the PDF is written directly). Read-only on the scanned repo.

Usage:
  python tools/build_lineage.py --root Synapse-itf-Dev --out .lineage/finance --title "Finance" \
      --layers "raw;landing;curated;staging=dwh_stg,dwh;core=dbo;reporting=rpt;bronze;silver;gold;out_gold=out_gold"

--layers is ordered (flow order). "name=schema1,schema2" maps SQL schemas; names without
schemas are matched by name tokens in table, path, notebook, and pipeline names.
"""

import argparse
import csv
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]

NOISE_TOKENS = {"error", "errors", "errorlog", "log", "logs", "audit", "syslog", "pipelinelog"}
SQL_KEYWORDS = {
    "where", "on", "inner", "left", "right", "full", "outer", "cross", "join", "group", "order", "with",
    "set", "as", "select", "union", "when", "then", "from", "into", "values", "option", "having", "pivot",
    "unpivot", "for", "and", "or", "not", "case", "end", "begin", "go", "exec", "execute", "declare", "if",
    "else", "output", "using", "merge", "update", "insert", "delete", "top", "distinct", "by", "is", "null",
    "apply", "table", "matched", "except", "intersect", "return", "commit", "rollback", "try", "catch",
}

IDENT = r"(?:\[[^\]]+\]|\"[^\"]+\"|[A-Za-z_#@][\w#@$]*)"
NAME = rf"{IDENT}(?:\s*\.\s*{IDENT}){{0,2}}"
CREATE_RE = re.compile(rf"\bCREATE\s+(?:OR\s+ALTER\s+)?(EXTERNAL\s+TABLE|TABLE|VIEW|PROC(?:EDURE)?|FUNCTION)\s+({NAME})", re.I)
WRITE_RES = [re.compile(p, re.I) for p in (
    rf"\bINSERT\s+(?:INTO\s+)?({NAME})",
    rf"\bMERGE\s+(?:INTO\s+)?({NAME})",
    rf"\bUPDATE\s+({NAME})\s+SET\b",
    rf"\bDELETE\s+(?:FROM\s+)?({NAME})",
    rf"\bTRUNCATE\s+TABLE\s+({NAME})",
    rf"\bINTO\s+({NAME})",  # SELECT ... INTO and COPY INTO
)]
READ_RE = re.compile(rf"\b(?:FROM|JOIN|USING|APPLY)\s+({NAME})", re.I)
ALIAS_RE = re.compile(rf"\b(?:FROM|JOIN|USING|UPDATE|MERGE\s+INTO|MERGE)\s+({NAME})\s+(?:AS\s+)?([A-Za-z_]\w*)", re.I)
EXEC_RE = re.compile(rf"\bEXEC(?:UTE)?\s+({NAME})", re.I)
DYNAMIC_RE = re.compile(r"\bsp_executesql\b|\bEXEC(?:UTE)?\s*\(|\bEXEC(?:UTE)?\s+@", re.I)
CTE_RE = re.compile(r"(?:\bWITH|,)\s*([A-Za-z_]\w*)\s+AS\s*\(", re.I)
LOCATION_RE = re.compile(r"LOCATION\s*=\s*N?'([^']+)'", re.I)
DATASOURCE_RE = re.compile(r"DATA_SOURCE\s*=\s*\[?([\w-]+)", re.I)

PY_STR = r"[rRfFbBuU]{0,2}(['\"])((?:(?!\1).){1,400})\1"
NB_WRITES = [re.compile(p) for p in (
    r"\.saveAsTable\(\s*" + PY_STR,
    r"\.insertInto\(\s*" + PY_STR,
    r"\.save\(\s*" + PY_STR,
    r"\.write[\s\S]{0,300}?\.(?:parquet|csv|json|orc|delta|synapsesql)\(\s*" + PY_STR,
)]
NB_READS = [re.compile(p) for p in (
    r"spark\.table\(\s*" + PY_STR,
    r"spark\.read[\s\S]{0,300}?\.(?:load|parquet|csv|json|orc|table|synapsesql)\(\s*" + PY_STR,
    r"DeltaTable\.for(?:Name|Path)\(\s*spark\s*,\s*" + PY_STR,
)]
NB_DBTABLE = re.compile(r"\.option\(\s*['\"]dbtable['\"]\s*,\s*" + PY_STR)
SPARK_SQL = re.compile(r"spark\.sql\(\s*[rRfF]{0,2}(\"\"\"|'''|\"|')([\s\S]*?)\1")

PALETTE = [(0.86, 0.92, 0.98), (0.88, 0.96, 0.88), (1.0, 0.95, 0.85), (0.95, 0.88, 0.96),
           (0.98, 0.90, 0.88), (0.88, 0.95, 0.95), (0.96, 0.96, 0.86), (0.92, 0.92, 0.92)]


def rel(path: Path) -> str:
    try:
        return path.relative_to(WORKSPACE).as_posix()
    except ValueError:
        return path.as_posix()


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


def literal(value) -> str | None:
    """Return a plain string; None for ADF expressions or missing values."""
    if isinstance(value, str) and not value.startswith("@"):
        return value
    return None


def strip_sql_comments(text: str) -> str:
    return re.sub(r"--[^\n]*", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))


class Lineage:
    def __init__(self, root: Path, layers: list[tuple[str, set]], noise: set):
        self.root, self.layers, self.noise = root, layers, noise
        self.display: dict[str, str] = {}
        self.objects: dict[str, dict] = {}
        self.known_by_name: dict[str, set] = defaultdict(set)
        self.processes: dict[str, dict] = {}
        self.orchestration: list[dict] = []
        self.datasets: dict[str, str] = {}

    # ------------------------------------------------------------------ names
    def norm(self, raw: str, default_schema: str = "dbo") -> str | None:
        parts = [p.strip().strip('[]"') for p in re.split(r"\s*\.\s*", raw.strip())]
        if not parts or not parts[-1] or "{" in raw or parts[-1][0] in "#@" or parts[0][:1] in ("#", "@"):
            return None
        if parts[0].lower() in ("sys", "information_schema", "tempdb") or (
                len(parts) >= 2 and parts[-2].lower() in ("sys", "information_schema")):
            return None
        if len(parts) == 1:
            if parts[0].lower() in SQL_KEYWORDS:
                return None
            disp = f"{default_schema}.{parts[0]}" if default_schema else parts[0]
        else:
            disp = f"{parts[-2] or 'dbo'}.{parts[-1]}"
        key = disp.lower()
        self.display.setdefault(key, disp)
        return key

    def is_noise(self, key: str) -> bool:
        return bool(set(tokens(key.split(".")[-1])) & self.noise)

    def layer_of(self, key: str) -> str:
        if not key.startswith(("file:", "dataset:")) and "." in key:
            schema = key.split(".")[0]
            for name, schemas in self.layers:
                if schema in schemas:
                    return name
        toks = set(tokens(key))
        for name, _ in self.layers:
            if name.lower() in toks:
                return name
        return "unassigned"

    def process_layers(self, pid: str) -> list[str]:
        names = {n.lower(): n for n, _ in self.layers}
        seen = []
        for t in tokens(pid.split(":", 1)[-1]):
            if t in names and names[t] not in seen:
                seen.append(names[t])
        return seen

    # ------------------------------------------------------------------ SQL
    def sql_io(self, text: str, default_schema: str = "dbo") -> dict:
        ctes = {m.group(1).lower() for m in CTE_RE.finditer(text)}
        aliases = {}
        for m in ALIAS_RE.finditer(text):
            alias = m.group(2).lower()
            if alias not in SQL_KEYWORDS:
                aliases[alias] = m.group(1)

        def resolve(raw: str, depth: int = 0) -> str | None:
            bare = raw.strip().strip('[]"').lower()
            if "." not in raw:
                if bare in ctes:
                    return None
                if bare in aliases and depth == 0 and "." in aliases[bare]:
                    return resolve(aliases[bare], 1)
                if not default_schema:
                    return self.norm(raw, "")
                candidates = self.known_by_name.get(bare, set())
                if f"dbo.{bare}" in candidates:
                    return f"dbo.{bare}"
                return next(iter(candidates)) if len(candidates) == 1 else None
            return self.norm(raw, default_schema)

        writes, reads, calls = set(), set(), set()
        for rx in WRITE_RES:
            for m in rx.finditer(text):
                if (key := resolve(m.group(1))):
                    writes.add(key)
        for m in READ_RE.finditer(text):
            if text[m.end():m.end() + 3].lstrip().startswith("("):
                continue  # table-valued function / OPENROWSET
            if (key := resolve(m.group(1))):
                reads.add(key)
        for m in EXEC_RE.finditer(text):
            name = m.group(1).strip("[]").lower()
            if name not in SQL_KEYWORDS and "sp_executesql" not in name and (key := self.norm(m.group(1))):
                calls.add(key)
        return {"reads": reads - writes, "writes": writes, "calls": calls, "dynamic": bool(DYNAMIC_RE.search(text))}

    def add_process(self, pid: str, kind: str, io: dict, evidence: str):
        proc = self.processes.setdefault(pid, {"kind": kind, "reads": set(), "writes": set(), "calls": set(),
                                               "dynamic": False, "evidence": set()})
        proc["reads"] |= io.get("reads", set())
        proc["writes"] |= io.get("writes", set())
        proc["calls"] |= io.get("calls", set())
        proc["dynamic"] |= io.get("dynamic", False)
        proc["evidence"].add(evidence)

    def load_sql(self):
        scripts = []
        for path in sorted((self.root / "sqlscript").glob("*.json")):
            data = load_json(path)
            query = ((data.get("properties", {}) or {}).get("content", {}) or {}).get("query", "")
            query = "".join(query) if isinstance(query, list) else query
            text = strip_sql_comments(query or "")
            scripts.append((data.get("name", path.stem), rel(path), text))
            for m in CREATE_RE.finditer(text):
                kind = re.sub(r"\s+", "_", m.group(1).lower()).replace("procedure", "proc")
                if (key := self.norm(m.group(2))):
                    self.objects.setdefault(key, {"kind": kind, "defined_in": rel(path)})
                    self.known_by_name[key.split(".")[-1]].add(key)

        for name, evidence, text in scripts:
            creates = list(CREATE_RE.finditer(text))
            bodies = [m for m in creates if m.group(1).upper().startswith(("PROC", "VIEW", "FUNCTION"))]
            for i, m in enumerate(bodies):
                end = bodies[i + 1].start() if i + 1 < len(bodies) else len(text)
                key = self.norm(m.group(2))
                if not key:
                    continue
                body = text[m.end():end]
                io = self.sql_io(body)
                is_view = m.group(1).upper().startswith("VIEW")
                if is_view:
                    io["writes"] = {key}
                    io["reads"].discard(key)
                for inner in CREATE_RE.finditer(body):
                    if "TABLE" in inner.group(1).upper() and (k := self.norm(inner.group(2))):
                        io["writes"].add(k)
                        io["reads"].discard(k)
                self.add_process(("view:" if is_view else "proc:") + key, "view" if is_view else "proc", io, evidence)
            for m in creates:
                if m.group(1).upper().startswith("EXTERNAL") and (key := self.norm(m.group(2))):
                    tail = text[m.end():m.end() + 1500]
                    loc, ds = LOCATION_RE.search(tail), DATASOURCE_RE.search(tail)
                    if loc:
                        file_key = f"file:{ds.group(1) + '/' if ds else ''}{loc.group(1)}".lower()
                        self.display.setdefault(file_key, file_key[5:])
                        self.add_process(f"external:{key}", "external_table",
                                         {"reads": {file_key}, "writes": {key}}, evidence)
            if not bodies:
                io = self.sql_io(text)
                io["writes"] -= {self.norm(m.group(2)) for m in creates}
                if io["writes"]:
                    self.add_process(f"script:{name}", "script", io, evidence)

    # ------------------------------------------------------------------ notebooks
    def nb_target(self, value: str) -> str | None:
        if "{" in value or "+" in value:
            return None
        if "://" in value or value.startswith("/") or value.lower().startswith("abfss"):
            key = f"file:{value}".lower()
        else:
            key = value.lower()
        self.display.setdefault(key, value)
        return key

    def load_notebooks(self):
        for path in sorted((self.root / "notebook").glob("*.json")):
            data = load_json(path)
            cells = (data.get("properties", {}) or {}).get("cells", []) or []
            sources = ["".join(c.get("source", [])) if isinstance(c.get("source"), list) else (c.get("source") or "")
                       for c in cells if c.get("cell_type", "code") == "code"]
            code = "\n".join(sources)
            io = {"reads": set(), "writes": set(), "dynamic": False}
            for rx, bucket in [(r, "writes") for r in NB_WRITES] + [(r, "reads") for r in NB_READS]:
                for m in rx.finditer(code):
                    key = self.nb_target(m.group(2))
                    if key:
                        io[bucket].add(key)
                    else:
                        io["dynamic"] = True
            for m in NB_DBTABLE.finditer(code):
                key = self.norm(m.group(2)) if "{" not in m.group(2) else None
                if key:
                    io["writes" if ".write" in code[max(0, m.start() - 400):m.start()] else "reads"].add(key)
            sql_blocks = [m.group(2) for m in SPARK_SQL.finditer(code)]
            sql_blocks += [s.lstrip()[5:] for s in sources if s.lstrip().lower().startswith("%%sql")]
            for block in sql_blocks:
                sio = self.sql_io(strip_sql_comments(block), default_schema="")
                io["reads"] |= sio["reads"]
                io["writes"] |= sio["writes"]
                io["dynamic"] |= "{" in block
            io["reads"] -= io["writes"]
            if not io["reads"] and not io["writes"]:
                io["dynamic"] = True
            self.add_process(f"notebook:{data.get('name', path.stem)}", "notebook", io, rel(path))

    # ------------------------------------------------------------------ datasets / data flows / pipelines
    def load_datasets(self):
        for path in sorted((self.root / "dataset").glob("*.json")):
            data = load_json(path)
            name = data.get("name", path.stem)
            tp = (data.get("properties", {}) or {}).get("typeProperties", {}) or {}
            table = literal(tp.get("table")) or literal(tp.get("tableName"))
            schema = literal(tp.get("schema"))
            if table:
                self.datasets[name] = self.norm(f"{schema}.{table}" if schema else table)
                continue
            loc = tp.get("location", {}) or {}
            parts = [literal(loc.get(k)) for k in ("container", "fileSystem", "folderPath", "fileName")]
            parts += [literal(tp.get(k)) for k in ("folderPath", "fileName")]
            parts = [p for p in parts if p]
            if parts:
                key = f"file:{'/'.join(parts)}".lower()
                self.display.setdefault(key, "/".join(parts))
            else:
                key = f"dataset:{name}".lower()
                self.display.setdefault(key, f"dataset {name} (parameterized)")
            self.datasets[name] = key

    def dataset_ref(self, ref: dict) -> str | None:
        name = (ref or {}).get("referenceName")
        return self.datasets.get(name) if name else None

    def load_dataflows(self):
        for path in sorted((self.root / "dataflow").glob("*.json")):
            data = load_json(path)
            name = data.get("name", path.stem)
            tp = (data.get("properties", {}) or {}).get("typeProperties", {}) or {}
            script = "\n".join(tp.get("scriptLines", []) or []) or tp.get("script", "") or ""
            io = {"reads": set(), "writes": set(), "dynamic": False}
            for bucket, items, verb in (("reads", tp.get("sources", []), "source"), ("writes", tp.get("sinks", []), "sink")):
                for item in items or []:
                    key = self.dataset_ref(item.get("dataset"))
                    if not key:
                        block = re.search(rf"{verb}\(([\s\S]*?)\)\s*~>\s*{re.escape(item.get('name', ''))}\b", script)
                        opts = block.group(1) if block else ""
                        table = re.search(r"tableName:\s*'([^']+)'", opts)
                        schema = re.search(r"schemaName:\s*'([^']+)'", opts)
                        fname = re.search(r"fileName:\s*'([^']+)'", opts)
                        if table:
                            key = self.norm(f"{schema.group(1)}.{table.group(1)}" if schema else table.group(1))
                        elif fname:
                            key = f"file:{fname.group(1)}".lower()
                            self.display.setdefault(key, fname.group(1))
                    if key:
                        io[bucket].add(key)
                    else:
                        io["dynamic"] = True
            self.add_process(f"dataflow:{name}", "dataflow", io, rel(path))

    def activity_target(self, pipeline: str, act: dict, evidence: str) -> str | None:
        kind, tp = act.get("type", ""), act.get("typeProperties", {}) or {}
        if kind in ("SqlPoolStoredProcedure", "SqlServerStoredProcedure"):
            sp = tp.get("storedProcedureName")
            sp = sp.get("value") if isinstance(sp, dict) else sp
            key = self.norm(sp) if isinstance(sp, str) and not sp.startswith("@") else None
            return f"proc:{key}" if key else f"dynamic:{pipeline}/{act.get('name')}"
        if kind == "SynapseNotebook":
            ref = (tp.get("notebook") or {}).get("referenceName")
            return f"notebook:{ref}" if isinstance(ref, str) else f"dynamic:{pipeline}/{act.get('name')}"
        if kind == "ExecuteDataFlow":
            return f"dataflow:{(tp.get('dataflow') or {}).get('referenceName')}"
        if kind == "ExecutePipeline":
            return f"pipeline:{(tp.get('pipeline') or {}).get('referenceName')}"
        if kind == "Copy":
            pid = f"copy:{pipeline}/{act.get('name')}"
            src = self.dataset_ref((act.get("inputs") or [{}])[0])
            dst = self.dataset_ref((act.get("outputs") or [{}])[0])
            self.add_process(pid, "copy", {"reads": {src} if src else set(), "writes": {dst} if dst else set(),
                                           "dynamic": not (src and dst)}, evidence)
            return pid
        if kind == "Script":
            pid = f"script:{pipeline}/{act.get('name')}"
            text = "\n".join(literal((s or {}).get("text")) or "" for s in tp.get("scripts", []) or [])
            self.add_process(pid, "script", self.sql_io(strip_sql_comments(text)), evidence)
            return pid
        return None

    def load_pipelines(self):
        def walk(acts):
            for act in acts or []:
                yield act
                tp = act.get("typeProperties", {}) or {}
                for k in ("activities", "ifTrueActivities", "ifFalseActivities", "defaultActivities"):
                    yield from walk(tp.get(k))
                for case in tp.get("cases", []) or []:
                    yield from walk(case.get("activities"))

        for path in sorted((self.root / "pipeline").glob("*.json")):
            data = load_json(path)
            name = data.get("name", path.stem)
            for act in walk((data.get("properties", {}) or {}).get("activities")):
                target = self.activity_target(name, act, rel(path))
                if target:
                    self.orchestration.append({"from": f"pipeline:{name}", "to": target,
                                               "activity": act.get("name"), "kind": "runs"})
        for path in sorted((self.root / "trigger").glob("*.json")):
            data = load_json(path)
            props = data.get("properties", {}) or {}
            for p in props.get("pipelines", []) or []:
                ref = (p.get("pipelineReference") or {}).get("referenceName")
                if ref:
                    self.orchestration.append({"from": f"trigger:{data.get('name', path.stem)}", "to": f"pipeline:{ref}",
                                               "activity": props.get("runtimeState", ""), "kind": "triggers"})
        for pid, proc in self.processes.items():
            for callee in sorted(proc["calls"]):
                self.orchestration.append({"from": pid, "to": f"proc:{callee}", "activity": "EXEC", "kind": "calls"})

    # ------------------------------------------------------------------ graph
    def edges(self) -> list[dict]:
        agg: dict[tuple, dict] = {}
        for pid, proc in self.processes.items():
            for w in proc["writes"]:
                if self.is_noise(w):
                    continue
                for r in proc["reads"]:
                    if r == w or self.is_noise(r):
                        continue
                    e = agg.setdefault((r, w), {"source": r, "target": w, "via": set(), "evidence": set()})
                    e["via"].add(pid)
                    e["evidence"] |= proc["evidence"]
        out = [{**e, "source_layer": self.layer_of(e["source"]), "target_layer": self.layer_of(e["target"]),
                "via": sorted(e["via"]), "evidence": sorted(e["evidence"])} for e in agg.values()]
        return sorted(out, key=lambda e: (e["source_layer"], e["target_layer"], e["target"], e["source"]))

    def label(self, pid: str) -> str:
        kind, _, name = pid.partition(":")
        short = {"pipeline": "PL", "notebook": "NB", "proc": "SP", "view": "VW", "dataflow": "DF", "copy": "COPY",
                 "script": "SQL", "trigger": "TRG", "external": "EXT", "dynamic": "DYN"}.get(kind, kind)
        return f"{short} {self.display.get(name, name)}"

    def run(self):
        self.load_sql()
        self.load_notebooks()
        self.load_datasets()
        self.load_dataflows()
        self.load_pipelines()


# ---------------------------------------------------------------------------- PDF
class Pdf:
    W, H = 842.0, 595.0  # A4 landscape

    def __init__(self, footer: str):
        self.pages: list[list[str]] = []
        self.footer = footer

    def new_page(self):
        self.ops: list[str] = []
        self.pages.append(self.ops)

    @staticmethod
    def esc(s: str) -> str:
        s = s.encode("latin-1", "replace").decode("latin-1")
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    @staticmethod
    def fit(s: str, width: float, size: float) -> str:
        n = max(4, int(width / (size * 0.52)))
        return s if len(s) <= n else s[: n - 3] + "..."

    def text(self, x, y, s, size=8, bold=False, rgb=(0, 0, 0)):
        self.ops.append(f"BT /{'F2' if bold else 'F1'} {size} Tf {rgb[0]} {rgb[1]} {rgb[2]} rg "
                        f"{x:.1f} {self.H - y:.1f} Td ({self.esc(s)}) Tj ET")

    def rect(self, x, y, w, h, fill=None, stroke=(0.5, 0.5, 0.5)):
        f = f"{fill[0]} {fill[1]} {fill[2]} rg " if fill else ""
        self.ops.append(f"{f}{stroke[0]} {stroke[1]} {stroke[2]} RG 0.6 w "
                        f"{x:.1f} {self.H - y - h:.1f} {w:.1f} {h:.1f} re {'B' if fill else 'S'}")

    def line(self, x1, y1, x2, y2, rgb=(0.55, 0.55, 0.55), width=0.5):
        self.ops.append(f"{rgb[0]} {rgb[1]} {rgb[2]} RG {width} w {x1:.1f} {self.H - y1:.1f} m {x2:.1f} {self.H - y2:.1f} l S")

    def save(self, path: Path):
        total = len(self.pages)
        objs: list = ["<< /Type /Catalog /Pages 2 0 R >>", None,
                      "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
                      "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"]
        kids = []
        for i, ops in enumerate(self.pages, 1):
            self.ops = ops
            self.text(30, self.H - 15, f"{self.footer}   |   page {i}/{total}", size=6, rgb=(0.4, 0.4, 0.4))
            page_no = len(objs) + 1
            kids.append(f"{page_no} 0 R")
            objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {self.W:.0f} {self.H:.0f}] "
                        f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {page_no + 1} 0 R >>")
            objs.append("\n".join(ops).encode("latin-1", "replace"))
        objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
        out, offsets = bytearray(b"%PDF-1.4\n"), []
        for i, obj in enumerate(objs, 1):
            offsets.append(len(out))
            body = (b"<< /Length %d >>\nstream\n" % len(obj) + obj + b"\nendstream") if isinstance(obj, bytes) \
                else obj.encode("latin-1")
            out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
        out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
        out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        path.write_bytes(bytes(out))


def render_pdf(model: Lineage, edges: list[dict], title: str, out: Path):
    layer_names = [n for n, _ in model.layers] + ["unassigned"]
    color = {n: PALETTE[i % len(PALETTE)] for i, n in enumerate(layer_names[:-1])}
    color["unassigned"] = (1, 1, 1)
    pdf = Pdf(f"{title} - table-level lineage - generated {datetime.now():%Y-%m-%d %H:%M} from {rel(model.root)}")

    def header(text: str, sub: str = ""):
        pdf.new_page()
        pdf.text(30, 32, text, size=13, bold=True)
        if sub:
            pdf.text(30, 46, sub, size=7, rgb=(0.35, 0.35, 0.35))

    # Overview
    hops = defaultdict(list)
    for e in edges:
        hops[(e["source_layer"], e["target_layer"])].append(e)
    order = {n: i for i, n in enumerate(layer_names)}
    hop_keys = sorted(hops, key=lambda k: (order.get(k[0], 99), order.get(k[1], 99)))
    nodes = {e["source"] for e in edges} | {e["target"] for e in edges}
    per_layer = defaultdict(int)
    for n in nodes:
        per_layer[model.layer_of(n)] += 1
    unassigned_schemas = defaultdict(int)
    for n in nodes:
        if model.layer_of(n) == "unassigned" and "." in n and not n.startswith(("file:", "dataset:")):
            unassigned_schemas[n.split(".")[0]] += 1

    header(f"{title}: table-level lineage",
           "Derived from script dependencies (procedures, views, external tables, notebooks, data flows, copy activities). "
           "Per process, every table read feeds every table written.")
    y = 70
    kinds = defaultdict(int)
    for p in model.processes.values():
        kinds[p["kind"]] += 1
    pdf.text(30, y, f"Objects in lineage: {len(nodes)}    Table links: {len(edges)}    Processes: "
             + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())), size=9)
    y += 22
    pdf.text(30, y, "Layers (flow order)", size=10, bold=True)
    y += 14
    for name in layer_names:
        schemas = next((s for n, s in model.layers if n == name), set())
        pdf.rect(30, y - 8, 10, 10, fill=color[name])
        pdf.text(46, y, f"{name}: {per_layer.get(name, 0)} objects"
                 + (f"  (schemas: {', '.join(sorted(schemas))})" if schemas else ""), size=8)
        y += 13
    if unassigned_schemas:
        pdf.text(46, y, Pdf.fit("Unassigned schemas (add to --layers): " + ", ".join(
            f"{s} ({c})" for s, c in sorted(unassigned_schemas.items(), key=lambda kv: -kv[1])), Pdf.W - 80, 7),
            size=7, rgb=(0.6, 0.1, 0.1))
        y += 13
    y += 8
    pdf.text(30, y, "Layer hops", size=10, bold=True)
    y += 14
    for k in hop_keys:
        if y > Pdf.H - 40:
            header(f"{title}: layer hops (cont.)")
            y = 70
        pdf.text(46, y, f"{k[0]}  ->  {k[1]}: {len(hops[k])} table links", size=8)
        y += 12

    # Orchestration
    children = defaultdict(list)
    for o in model.orchestration:
        children[o["from"]].append(o)
    lines: list[tuple[int, str, bool]] = []

    def emit(pid: str, depth: int, seen: set):
        proc = model.processes.get(pid, {})
        tags = model.process_layers(pid)
        suffix = (f"  [{' -> '.join(tags)}]" if tags else "") + ("  (dynamic I/O)" if proc.get("dynamic") else "")
        lines.append((depth, model.label(pid) + suffix, pid.startswith(("trigger:", "pipeline:"))))
        if depth > 7:
            return
        for c in children.get(pid, []):
            if c["to"] in seen:
                lines.append((depth + 1, model.label(c["to"]) + "  (see above)", False))
            else:
                emit(c["to"], depth + 1, seen | {pid})

    triggers = sorted({o["from"] for o in model.orchestration if o["kind"] == "triggers"})
    for t in triggers:
        state = next((o["activity"] for o in model.orchestration if o["from"] == t), "")
        lines.append((0, f"{model.label(t)}  ({state})", True))
        for c in children[t]:
            emit(c["to"], 1, {t})
    reached = {o["to"] for o in model.orchestration}
    untriggered = sorted({o["from"] for o in model.orchestration if o["from"].startswith("pipeline:")} - reached)
    if untriggered:
        lines.append((0, "Pipelines without trigger or parent", True))
        for p in untriggered:
            emit(p, 1, set())
    for i in range(0, len(lines), 46):
        header(f"{title}: orchestration (trigger -> pipeline -> activity)" + (" (cont.)" if i else ""))
        y = 66
        for depth, text, bold in lines[i:i + 46]:
            pdf.text(30 + depth * 14, y, Pdf.fit(text, Pdf.W - 60 - depth * 14, 7.5), size=7.5, bold=bold)
            y += 11

    # Hop diagrams + listings
    cap, row, box_h = 26, 18, 13
    lx, lw, rx, rw = 30, 300, 512, 300
    for k in hop_keys:
        hop_edges = sorted(hops[k], key=lambda e: (e["target"], e["source"]))
        chunks, cur, left, right = [], [], set(), set()
        for e in hop_edges:
            nl, nr = left | {e["source"]}, right | {e["target"]}
            if cur and (len(nl) > cap or len(nr) > cap):
                chunks.append(cur)
                cur, nl, nr = [], {e["source"]}, {e["target"]}
            cur.append(e)
            left, right = nl, nr
        if cur:
            chunks.append(cur)
        for ci, chunk in enumerate(chunks, 1):
            header(f"{k[0]}  ->  {k[1]}" + (f"   ({ci}/{len(chunks)})" if len(chunks) > 1 else ""),
                   f"{len(hop_edges)} table links. Lines connect source tables (left) to target tables (right).")
            lefts = sorted({e["source"] for e in chunk})
            rights = sorted({e["target"] for e in chunk})
            pdf.text(lx, 64, k[0], size=9, bold=True)
            pdf.text(rx, 64, k[1], size=9, bold=True)
            pos_l = {n: 72 + i * row for i, n in enumerate(lefts)}
            pos_r = {n: 72 + i * row for i, n in enumerate(rights)}
            for e in chunk:
                pdf.line(lx + lw, pos_l[e["source"]] + box_h / 2, rx, pos_r[e["target"]] + box_h / 2)
            for names, pos, x, w in ((lefts, pos_l, lx, lw), (rights, pos_r, rx, rw)):
                for n in names:
                    pdf.rect(x, pos[n], w, box_h, fill=color.get(model.layer_of(n), (1, 1, 1)))
                    pdf.text(x + 4, pos[n] + 9.5, Pdf.fit(model.display.get(n, n), w - 8, 7), size=7)
        listing = [(model.display.get(e["source"], e["source"]),
                    ", ".join(model.label(v) for v in e["via"][:2]) + (f" +{len(e['via']) - 2}" if len(e["via"]) > 2 else ""),
                    model.display.get(e["target"], e["target"])) for e in hop_edges]
        for i in range(0, len(listing), 48):
            header(f"{k[0]}  ->  {k[1]}: link list" + (" (cont.)" if i else ""))
            for x, h in ((30, "Source"), (330, "Via (process)"), (570, "Target")):
                pdf.text(x, 64, h, size=8, bold=True)
            y = 76
            for src, via, tgt in listing[i:i + 48]:
                pdf.text(30, y, Pdf.fit(src, 295, 7), size=7)
                pdf.text(330, y, Pdf.fit(via, 235, 7), size=7, rgb=(0.3, 0.3, 0.3))
                pdf.text(570, y, Pdf.fit(tgt, 245, 7), size=7)
                y += 10

    # Unresolved
    dynamic = sorted(pid for pid, p in model.processes.items() if p["dynamic"])
    for i in range(0, max(len(dynamic), 1), 48):
        header("Unresolved / dynamic processes" + (" (cont.)" if i else ""),
               "Inputs or outputs are built at runtime (parameters, f-strings, dynamic SQL). Their lineage is incomplete; "
               "expand via metadata tables or add it manually.")
        y = 66
        for pid in dynamic[i:i + 48]:
            p = model.processes[pid]
            known = f"reads {len(p['reads'])}, writes {len(p['writes'])}"
            pdf.text(30, y, Pdf.fit(f"{model.label(pid)}   ({known})   {sorted(p['evidence'])[0]}", Pdf.W - 60, 7), size=7)
            y += 10
    pdf.save(out)


def parse_layers(spec: str) -> list[tuple[str, set]]:
    layers = []
    for part in [p.strip() for p in spec.split(";") if p.strip()]:
        name, _, schemas = part.partition("=")
        layers.append((name.strip(), {s.strip().lower() for s in schemas.split(",") if s.strip()}))
    return layers


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, help="Synapse artifact root (profile repository.artifact_root)")
    ap.add_argument("--out", required=True, help="Output folder, e.g. .lineage/<profile-id>")
    ap.add_argument("--title", help="Title in the PDF (default: root folder name)")
    ap.add_argument("--layers", default="", help="Ordered layers: 'name=schema1,schema2;name2;...'")
    ap.add_argument("--noise-tokens", default=",".join(sorted(NOISE_TOKENS)),
                    help="Name tokens of logging/audit tables excluded from links")
    args = ap.parse_args()

    root = (WORKSPACE / args.root).resolve()
    if not root.is_dir():
        raise SystemExit(f"Root not found: {args.root}")
    out = (WORKSPACE / args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    model = Lineage(root, parse_layers(args.layers),
                    {t.strip().lower() for t in args.noise_tokens.split(",") if t.strip()})
    model.run()
    edges = model.edges()
    title = args.title or root.name

    nodes = sorted({e["source"] for e in edges} | {e["target"] for e in edges} | set(model.objects))
    (out / "lineage.json").write_text(json.dumps({
        "generated": datetime.now().isoformat(timespec="seconds"),
        "root": rel(root),
        "granularity": "table, per process (all reads -> all writes)",
        "layers": [{"name": n, "schemas": sorted(s)} for n, s in model.layers],
        "nodes": {n: {"display": model.display.get(n, n), "layer": model.layer_of(n),
                      **({"kind": model.objects[n]["kind"], "defined_in": model.objects[n]["defined_in"]}
                         if n in model.objects else {"kind": "file" if n.startswith("file:") else "external"})}
                  for n in nodes},
        "edges": edges,
        "processes": {pid: {"label": model.label(pid), "kind": p["kind"], "reads": sorted(p["reads"]),
                            "writes": sorted(p["writes"]), "calls": sorted(p["calls"]), "dynamic": p["dynamic"],
                            "layers": model.process_layers(pid), "evidence": sorted(p["evidence"])}
                      for pid, p in sorted(model.processes.items())},
        "orchestration": model.orchestration,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    with (out / "lineage_edges.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["source", "source_layer", "target", "target_layer", "via", "evidence"])
        for e in edges:
            w.writerow([model.display.get(e["source"], e["source"]), e["source_layer"],
                        model.display.get(e["target"], e["target"]), e["target_layer"],
                        "; ".join(model.label(v) for v in e["via"]), "; ".join(e["evidence"])])

    render_pdf(model, edges, title, out / "lineage.pdf")
    dynamic = sum(p["dynamic"] for p in model.processes.values())
    print(f"{len(edges)} table links, {len(model.processes)} processes ({dynamic} dynamic) -> "
          f"{rel(out / 'lineage.pdf')}, lineage.json, lineage_edges.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
