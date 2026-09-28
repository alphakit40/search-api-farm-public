"""Digest harvest jsonl -> per-topic ranked source map for synthesis.

Usage: python -u digest.py [topic]   (no arg = all topics)
Prints per topic: dedup'd sources ranked by (n_channels desc, snippet len),
each as: idx | channels | date | title | url | snippet(700c).

Env: RESEARCH_ROOT (default: directory of this script); reads raw/harvest_*.jsonl.
"""
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(os.environ.get("RESEARCH_ROOT", pathlib.Path(__file__).resolve().parent))
RAW = ROOT / "raw"


def load(topic):
    p = RAW / f"harvest_{topic}.jsonl"
    if not p.exists():
        return []
    out = {}
    for ln in p.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(ln)
        except Exception:
            continue
        u = r.get("url", "")
        if not u:
            continue
        if u in out:
            out[u]["channels"].add(r.get("channel", ""))
            if len(r.get("snippet", "")) > len(out[u].get("snippet", "")):
                out[u]["snippet"] = r["snippet"]
        else:
            out[u] = {"title": r.get("title", ""), "url": u,
                      "channels": {r.get("channel", "")},
                      "date": r.get("date", ""), "snippet": r.get("snippet", ""),
                      "query": r.get("query", "")}
    return list(out.values())


def main():
    topics = [sys.argv[1]] if len(sys.argv) > 1 else sorted(
        p.stem.replace("harvest_", "") for p in RAW.glob("harvest_*.jsonl"))
    for t in topics:
        recs = load(t)
        recs.sort(key=lambda r: (-len(r["channels"]), -len(r["snippet"])))
        print(f"\n{'='*90}\n### {t}: {len(recs)} unique sources\n{'='*90}")
        for i, r in enumerate(recs, 1):
            ch = "+".join(sorted(r["channels"]))
            print(f"\n[{i:02d}] ({ch}) {r['date'][:10]}\n  {r['title'][:130]}\n  {r['url']}")
            sn = r["snippet"].replace("\n", " ")[:700]
            if sn:
                print(f"  > {sn}")


if __name__ == "__main__":
    main()
