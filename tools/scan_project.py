#!/usr/bin/env python3
"""Read-only project scanner for /init-project-profile.

Detects data platform repositories inside a workspace by structure (not by folder
name) and writes facts with evidence paths to .project_scan/<root>.json.
Standard library only; never modifies scanned files.

Usage:
  python tools/scan_project.py                     # list candidate roots
  python tools/scan_project.py --root Synapse-itf-Dev
"""

import argparse
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
OUT_DIR = WORKSPACE / ".project_scan"

SKIP_DIRS = {
    ".git", ".github", ".vscode", ".project_scan", ".synapse_work", ".synapse_index",
    "node_modules", "__pycache__", ".pytest_cache", ".venv", "venv", ".terraform",
    "cdk.out", ".databricks",
}
SYNAPSE_FOLDERS = {"pipeline", "dataset", "linkedService", "notebook", "sqlscript",
                   "dataflow", "trigger", "integrationRuntime", "sparkConfiguration"}
FABRIC_SUFFIXES = (".Notebook", ".DataPipeline", ".Lakehouse", ".Warehouse",
                   ".SemanticModel", ".Report", ".Dataflow", ".Environment")
MAX_DEPTH = 4

# Checked in order; first match wins. Tokens are underscore/dash separated name parts.
STAGE_TOKENS = [
    ("meta", {"meta", "config", "control", "etl", "log", "logs", "audit", "monitoring", "monitor"}),
    ("serve", {"reporting", "report", "rep", "rpt", "out", "outbound", "semantic", "bi", "consumption",
               "presentation", "selfservice", "views", "mart", "marts"}),
    ("model", {"core", "gold", "model", "dim", "dims", "fact", "facts"}),
    ("refine", {"curated", "crt", "clean", "cleansed", "silver", "stg", "staging", "stage",
                "conformed", "standardized"}),
    ("ingest", {"landing", "lnd", "raw", "bronze", "inbound", "ingest", "source", "src"}),
]

DDL_RE = re.compile(
    r"\bCREATE\s+(?:OR\s+ALTER\s+)?(EXTERNAL\s+TABLE|TABLE|VIEW|PROC(?:EDURE)?|FUNCTION|SCHEMA)\s+"
    r"\[?(\w+)\]?(?:\s*\.\s*\[?(\w+)\]?)?",
    re.IGNORECASE,
)
INSERT_RE = re.compile(r"\bINSERT\s+INTO\s+\[?(\w+)\]?\s*\.\s*\[?(\w+)\]?", re.IGNORECASE)


def rel(path: Path) -> str:
    return path.relative_to(WORKSPACE).as_posix()


def tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[_\-\s.]+", name.lower()) if t]


def stage_of(name: str) -> str | None:
    toks = set(tokens(name))
    for stage, keys in STAGE_TOKENS:
        if toks & keys:
            return stage
    return None


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def walk(root: Path, max_depth: int = MAX_DEPTH):
    root_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.startswith(".verify_env")]
        if len(current.parts) - root_depth >= max_depth:
            dirnames[:] = []
        yield current, dirnames, filenames


# ----------------------------------------------------------------------------
# candidate detection
# ----------------------------------------------------------------------------
def find_candidates() -> list[dict]:
    found: dict[str, dict] = {}

    def add(path: Path, platform: str, marker: str):
        key = rel(path) or "."
        entry = found.setdefault(key, {"root": key, "platforms": Counter(), "markers": []})
        entry["platforms"][platform] += 1
        if len(entry["markers"]) < 12:
            entry["markers"].append(marker)

    for current, dirnames, filenames in walk(WORKSPACE):
        subdirs = set(dirnames)
        synapse_hits = subdirs & SYNAPSE_FOLDERS
        if len(synapse_hits) >= 2:
            has_json = any(next((current / d).glob("*.json"), None) for d in synapse_hits)
            if has_json:
                platform = "synapse" if subdirs & {"sqlscript", "notebook", "sparkConfiguration"} else "adf"
                add(current, platform, f"folders: {sorted(synapse_hits)}")
        fabric_items = [d for d in dirnames if d.endswith(FABRIC_SUFFIXES)]
        if fabric_items and any((current / d / ".platform").exists() for d in fabric_items):
            add(current, "fabric", f"{len(fabric_items)} Fabric item folders")
        if "databricks.yml" in filenames:
            add(current, "databricks", rel(current / "databricks.yml"))
        # AWS code is spread across folders; attribute it to the top-level folder.
        aws_root = WORKSPACE / current.relative_to(WORKSPACE).parts[0] if current != WORKSPACE else WORKSPACE
        for f in filenames:
            path = current / f
            if f.endswith(".asl.json"):
                add(aws_root, "aws", rel(path))
            elif f.endswith(".tf") and re.search(r"aws_(glue|redshift|sfn|lambda|s3)", path.read_text(errors="ignore")):
                add(aws_root, "aws", rel(path))
            elif f.endswith(".py") and path.stat().st_size < 200_000 and re.search(
                    r"^\s*(from|import)\s+awsglue", path.read_text(errors="ignore"), re.M):
                add(aws_root, "aws", rel(path))

    result = []
    for entry in found.values():
        entry["platforms"] = dict(entry["platforms"])
        result.append(entry)
    return sorted(result, key=lambda e: e["root"])


# ----------------------------------------------------------------------------
# git facts
# ----------------------------------------------------------------------------
def find_git_dir(start: Path) -> Path | None:
    for p in [start, *start.parents]:
        if (p / ".git").is_dir():
            return p / ".git"
        if p == WORKSPACE:
            break
    return None


def git_facts(root: Path) -> dict:
    git_dir = find_git_dir(root)
    if not git_dir:
        return {"found": False}
    facts: dict = {"found": True, "evidence": rel(git_dir)}
    config = (git_dir / "config").read_text(errors="ignore") if (git_dir / "config").exists() else ""
    remotes = re.findall(r'\[remote "([^"]+)"\][^\[]*?url\s*=\s*(\S+)', config, re.S)
    facts["remotes"] = {name: re.sub(r"//[^@/]+@", "//", url) for name, url in remotes}
    url = facts["remotes"].get("origin", next(iter(facts["remotes"].values()), ""))
    if "dev.azure.com" in url or "visualstudio.com" in url:
        facts["pr_tool"] = "az-repos"
    elif "github" in url:
        facts["pr_tool"] = "gh"
    elif "gitlab" in url:
        facts["pr_tool"] = "glab"
    else:
        facts["pr_tool"] = "manual"
    head = (git_dir / "HEAD").read_text(errors="ignore").strip() if (git_dir / "HEAD").exists() else ""
    facts["current_branch"] = head.split("refs/heads/")[-1] if "refs/heads/" in head else None
    branches = set()
    for base in ("refs/heads", "refs/remotes/origin"):
        d = git_dir / base
        if d.is_dir():
            branches |= {p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file()}
    packed = git_dir / "packed-refs"
    if packed.exists():
        for line in packed.read_text(errors="ignore").splitlines():
            m = re.search(r"refs/(?:heads|remotes/origin)/(\S+)", line)
            if m:
                branches.add(m.group(1))
    branches.discard("HEAD")
    facts["branches"] = sorted(branches)
    facts["likely_protected"] = sorted(b for b in branches if b in
                                       {"main", "master", "develop", "development", "devlop", "release", "prod"})
    return facts


# ----------------------------------------------------------------------------
# synapse / adf facts
# ----------------------------------------------------------------------------
def prefix(name: str, parts: int) -> str:
    toks = name.split("_")
    return "_".join(toks[:parts]) + "_" if len(toks) > parts else name


def scan_synapse(root: Path) -> dict:
    facts: dict = {"folders": {}}
    for d in sorted(SYNAPSE_FOLDERS | {"factory", "credential", "managedVirtualNetwork"}):
        if (root / d).is_dir():
            facts["folders"][d] = len(list((root / d).glob("*.json")))

    publish = load_json(root / "publish_config.json")
    if publish:
        facts["publish_branch"] = {"value": publish.get("publishBranch"), "evidence": rel(root / "publish_config.json")}

    # SQL scripts
    schemas: dict[str, Counter] = defaultdict(Counter)
    schema_samples: dict[str, list] = defaultdict(list)
    proc_prefix, folders, pools, databases = Counter(), Counter(), Counter(), Counter()
    meta_writers: dict[str, set] = defaultdict(set)
    reference_candidates: dict[str, list] = defaultdict(list)
    for path in sorted((root / "sqlscript").glob("*.json")) if (root / "sqlscript").is_dir() else []:
        data = load_json(path)
        props = data.get("properties", {}) or {}
        content = props.get("content", {}) or {}
        conn = content.get("currentConnection", {}) or {}
        folders[(props.get("folder", {}) or {}).get("name", "") or "<root>"] += 1
        if conn.get("poolName"):
            pools[conn["poolName"]] += 1
        if conn.get("databaseName"):
            databases[conn["databaseName"]] += 1
        query = content.get("query", "")
        if isinstance(query, list):
            query = "".join(query)
        for kind, schema, obj in DDL_RE.findall(query):
            kind = re.sub(r"\s+", "_", kind.lower()).replace("procedure", "proc")
            if kind == "schema":
                schemas[schema.lower()]["schema"] += 1
                continue
            if not obj:
                continue
            schemas[schema.lower()][kind] += 1
            if len(schema_samples[schema.lower()]) < 6:
                schema_samples[schema.lower()].append({"name": obj, "kind": kind, "path": rel(path)})
            if kind == "proc":
                pfx = prefix(obj, 2)
                proc_prefix[pfx] += 1
                score = sum(k in query.upper() for k in ("MERGE", "BEGIN TRY", "BEGIN CATCH", "LABEL", "TRANSACTION"))
                reference_candidates[pfx].append((score, obj, rel(path)))
        for schema, table in INSERT_RE.findall(query):
            if stage_of(schema) == "meta":
                meta_writers[f"{schema}.{table}"].add(data.get("name", path.stem))

    facts["sql"] = {
        "schemas": {
            s: {"objects": dict(c), "stage_guess": stage_of(s), "samples": schema_samples.get(s, [])}
            for s, c in sorted(schemas.items(), key=lambda kv: -sum(kv[1].values()))
        },
        "pools": dict(pools.most_common(5)),
        "databases": dict(databases.most_common(5)),
        "folders_top": dict(folders.most_common(40)),
        "procedure_prefixes": dict(proc_prefix.most_common(15)),
        "reference_procedures": {
            p: [{"name": n, "path": pth, "pattern_score": s}
                for s, n, pth in sorted(c, reverse=True)[:3]]
            for p, c in reference_candidates.items() if proc_prefix[p] >= 3
        },
        "metadata_tables_and_writers": {t: sorted(w)[:5] for t, w in sorted(meta_writers.items())},
    }

    facts["notebooks"] = names_and_prefixes(root / "notebook")
    facts["pipelines"] = names_and_prefixes(root / "pipeline")
    facts["pipelines"]["all_any_families"] = sorted({
        n[: -len("_ALL")] for n in facts["pipelines"]["names"]
        if n.endswith("_ALL") and f"{n[:-4]}_ANY" in facts["pipelines"]["names"]
    })
    facts["pipelines"]["activity_types"] = activity_types(root / "pipeline")
    facts["linked_services"] = typed_items(root / "linkedService")
    facts["datasets"] = typed_items(root / "dataset", names=False)
    facts["triggers"] = typed_items(root / "trigger")
    facts["spark_pools"] = dict(Counter(
        ref for p in (root / "notebook").glob("*.json")
        if (ref := ((load_json(p).get("properties", {}) or {}).get("bigDataPool", {}) or {}).get("referenceName"))
    ).most_common(5)) if (root / "notebook").is_dir() else {}

    stage_hints: dict[str, Counter] = defaultdict(Counter)
    for name in facts["pipelines"]["names"] + facts["notebooks"]["names"]:
        for tok in tokens(name):
            st = stage_of(tok)
            if st and st != "meta":
                stage_hints[st][tok] += 1
    facts["layer_name_hints"] = {s: dict(c.most_common(6)) for s, c in stage_hints.items()}
    return facts


def names_and_prefixes(folder: Path) -> dict:
    names = sorted(p.stem for p in folder.glob("*.json")) if folder.is_dir() else []
    return {
        "count": len(names),
        "names": names,
        "prefixes": dict(Counter(prefix(n, 3) for n in names).most_common(15)),
    }


def typed_items(folder: Path, names: bool = True) -> dict:
    types, by_type = Counter(), defaultdict(list)
    for p in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        t = (load_json(p).get("properties", {}) or {}).get("type", "unknown")
        types[t] += 1
        if names and len(by_type[t]) < 8:
            by_type[t].append(p.stem)
    out: dict = {"types": dict(types.most_common())}
    if names:
        out["names_by_type"] = dict(by_type)
    return out


def activity_types(folder: Path) -> dict:
    counter = Counter()
    for p in folder.glob("*.json") if folder.is_dir() else []:
        stack = list((load_json(p).get("properties", {}) or {}).get("activities", []) or [])
        while stack:
            act = stack.pop()
            counter[act.get("type", "unknown")] += 1
            tp = act.get("typeProperties", {}) or {}
            for key in ("activities", "ifTrueActivities", "ifFalseActivities"):
                stack.extend(tp.get(key, []) or [])
    return dict(counter.most_common(12))


# ----------------------------------------------------------------------------
# docs
# ----------------------------------------------------------------------------
def doc_facts(root: Path) -> dict:
    facts: dict = {}
    readme = root / "README.md"
    if readme.exists():
        text = readme.read_text(encoding="utf-8", errors="ignore")
        title = next((l.lstrip("# ").strip() for l in text.splitlines() if l.startswith("#")), None)
        facts["readme"] = {"path": rel(readme), "title": title, "excerpt": text[:2500]}
    for name in ("CHANGELOG.md",):
        if (root / name).exists():
            facts[name] = rel(root / name)

    repo_docs, lineage, schema_files = [], [], []
    for current, _, filenames in walk(root, max_depth=4):
        for f in filenames:
            low, path = f.lower(), current / f
            if "lineage" in low and low.endswith((".pdf", ".xlsx", ".md", ".html", ".json")):
                lineage.append(rel(path))
            elif low.endswith("_schema.txt"):
                schema_files.append(rel(path))
            elif low.endswith(".md") and path != readme:
                text = path.read_text(encoding="utf-8", errors="ignore")
                title = next((l.lstrip("# ").strip() for l in text.splitlines() if l.startswith("#")), f)
                repo_docs.append({"path": rel(path), "title": title, "chars": len(text)})
    facts["repo_docs"] = sorted(repo_docs, key=lambda d: d["path"])[:30]
    facts["lineage_documents"] = sorted(lineage)[:20]
    facts["schema_files"] = sorted(schema_files)[:20]

    # Workspace-level docs may belong to another project; the setup agent must confirm ownership.
    shared = []
    if (WORKSPACE / "docs").is_dir():
        for current, _, filenames in walk(WORKSPACE / "docs", max_depth=4):
            shared.extend(rel(current / f) for f in filenames
                          if "lineage" in f.lower() or f.lower().endswith("_schema.txt"))
    facts["shared_workspace_docs_unconfirmed"] = sorted(shared)[:20]
    return facts


def excerpt(path: Path, limit: int = 1500) -> dict:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return {"path": rel(path), "chars": len(text), "excerpt": text[:limit]}


def team_rule_facts(root: Path) -> dict:
    """Copilot/agent rules shipped inside the cloned repo. VS Code does not load nested .github folders."""
    files = [root / "AGENTS.md", root / "CONTRIBUTING.md", root / ".github" / "copilot-instructions.md",
             root / ".github" / "AGENTS.md"]
    for sub, pattern in (("instructions", "*.instructions.md"), ("agents", "*.agent.md"),
                         ("prompts", "*.prompt.md"), ("skills", "**/SKILL.md")):
        files.extend(sorted((root / ".github" / sub).glob(pattern)) if (root / ".github" / sub).is_dir() else [])
    return {"files": [excerpt(p) for p in files if p.is_file()][:20]}


def cicd_facts(root: Path) -> dict:
    found = []
    candidates = list(root.glob("*pipelines*.y*ml")) + list(root.glob(".gitlab-ci.yml")) + list(root.glob("Jenkinsfile"))
    for sub in (".github/workflows", ".azure-pipelines", "pipelines", "devops", "cicd", "deploy"):
        d = root / sub
        if d.is_dir():
            candidates.extend(p for p in d.rglob("*") if p.suffix in (".yml", ".yaml") and p.is_file())
    for p in sorted(set(candidates))[:15]:
        text = p.read_text(encoding="utf-8", errors="ignore")
        branches = sorted(set(re.findall(r"^\s*-\s*['\"]?(main|master|develop|release[\w/*.-]*|prod\w*)['\"]?\s*$", text, re.M)))
        found.append({"path": rel(p), "branch_refs": branches, "excerpt": text[:800]})
    readme = root / "README.md"
    related = []
    if readme.exists():
        related = sorted(set(re.findall(r"\(\.\./([\w.-]+)/", readme.read_text(encoding="utf-8", errors="ignore"))))
    return {"files": found, "related_repos_from_readme": related}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="Artifact root to scan (relative to workspace). Omit to list candidates.")
    args = ap.parse_args()

    candidates = find_candidates()
    if not args.root:
        print(json.dumps({"workspace": str(WORKSPACE), "candidates": candidates}, indent=2))
        return 0

    root = (WORKSPACE / args.root).resolve()
    if not root.is_dir():
        raise SystemExit(f"Root not found: {args.root}")
    match = next((c for c in candidates if c["root"] == rel(root)), None)
    platforms = match["platforms"] if match else {}
    scan = {
        "root": rel(root),
        "platforms": platforms,
        "markers": match["markers"] if match else [],
        "git": git_facts(root),
        "docs": doc_facts(root),
        "team_rules": team_rule_facts(root),
        "cicd": cicd_facts(root),
    }
    if "synapse" in platforms or "adf" in platforms:
        scan["synapse"] = scan_synapse(root)

    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', root.name)}.json"
    out.write_text(json.dumps(scan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Scanned {scan['root']} ({', '.join(platforms) or 'no platform detected'}) -> {rel(out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
