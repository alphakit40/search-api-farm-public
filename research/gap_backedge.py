"""Gap-backedge: second-cycle pass over holes found during synthesis.

Two modes:
  python -u gap_backedge.py scrape [gap.json]   # full-text scrape of key pages -> raw/full_<name>.md
  python -u gap_backedge.py query  [gap.json]   # targeted queries -> raw/harvest_gap.jsonl

gap.json format (see gap.example.json):
  {"scrape": {"name": "https://..."}, "queries": [["exa"|"tavily", "query", n]]}

Env: RESEARCH_ROOT, RSTACK_PATH (scrape mode), SEARCH_API_FARM_SECRETS (query mode keys).
"""
import json
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from harvest import exa, tavily  # noqa: E402

ROOT = pathlib.Path(os.environ.get("RESEARCH_ROOT", pathlib.Path(__file__).resolve().parent))
RAW = ROOT / "raw"
RSTACK = os.environ.get("RSTACK_PATH") or None


def load_gap(path):
    p = pathlib.Path(path)
    if not p.exists():
        print(f"gap file not found: {p}\nCopy gap.example.json to gap.json and edit.")
        sys.exit(2)
    return json.loads(p.read_text(encoding="utf-8"))


def scrape(name, url):
    if not RSTACK or not pathlib.Path(RSTACK).exists():
        print("  scrape SKIP (RSTACK_PATH not set)", flush=True)
        return
    r = subprocess.run([sys.executable, "-u", RSTACK, "fc", "scrape", url, "--json"],
                       capture_output=True, text=True, timeout=240, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(f"  scrape FAIL {name}: {r.stderr[:100]}", flush=True)
        return
    try:
        data = json.loads(r.stdout)
        md = data[0].get("markdown", "") if data else ""
        RAW.mkdir(exist_ok=True)
        (RAW / f"full_{name}.md").write_text(md, encoding="utf-8")
        print(f"  scrape OK {name}: {len(md)} chars", flush=True)
    except Exception as e:
        print(f"  scrape FAIL {name}: {e}", flush=True)


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("scrape", "query"):
        print((__doc__ or "usage: gap_backedge.py scrape|query [gap.json]").strip())
        sys.exit(2)
    mode = sys.argv[1]
    gap = load_gap(sys.argv[2] if len(sys.argv) > 2 else ROOT / "gap.json")
    if mode == "scrape":
        for name, url in gap.get("scrape", {}).items():
            scrape(name, url)
    else:
        RAW.mkdir(exist_ok=True)
        out = RAW / "harvest_gap.jsonl"
        rot = 0
        with out.open("a", encoding="utf-8") as f:
            for ch, q, n in gap.get("queries", []):
                try:
                    recs, rot = exa(q, n, rot) if ch == "exa" else (tavily(q, n), rot)
                except Exception as e:
                    print(f"  [{ch}] FAIL {str(e)[:80]}", flush=True)
                    continue
                for rec in recs:
                    rec.update({"topic": "gap", "channel": ch, "query": q})
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                print(f"  [{ch}] {len(recs)} ({q[:50]})", flush=True)


if __name__ == "__main__":
    main()
