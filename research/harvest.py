"""Multi-channel harvest. One topic per invocation.

Usage:
  python -u harvest.py <topic_key> [--topics topics.example.json]
  python -u harvest.py --list [--topics topics.example.json]

Topics are loaded from a JSON file: {"topic_key": [[channel, query, n], ...]}.
Channels: exa (EXA_KEYS, comma-separated, round-robin), tavily (TAVILY_KEY),
you (YOU_KEY) via direct HTTP; fc/rss/yt/gh/hn/reddit via rstack (RSTACK_PATH).
Writes raw/harvest_<topic>.jsonl (append per record, crash-safe, URL-dedup).

Env:
  SEARCH_API_FARM_SECRETS  path to KEY=VALUE env file (default: ./secrets.env, loaded if exists)
  RESEARCH_ROOT            workspace root (default: directory of this script)
  RSTACK_PATH              path to rstack.py (optional; rstack channels are skipped without it)
"""
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request

ROOT = pathlib.Path(os.environ.get("RESEARCH_ROOT", pathlib.Path(__file__).resolve().parent))
RAW = ROOT / "raw"
RSTACK = os.environ.get("RSTACK_PATH") or None

_env_file = pathlib.Path(os.environ.get("SEARCH_API_FARM_SECRETS", ROOT / "secrets.env"))
if not _env_file.exists() and (ROOT.parent / "secrets.env").exists():
    _env_file = ROOT.parent / "secrets.env"  # ponytail: secrets.env живёт в корне репо, не в research/
if _env_file.exists():
    for line in _env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

EXA = [k.strip() for k in os.environ.get("EXA_KEYS", "").split(",") if k.strip()]
UA = {"User-Agent": "multi-channel-harvest/1.1"}

CHANNELS_DIRECT = {"exa", "tavily", "you"}
CHANNELS_RSTACK = {"fc", "rss", "yt", "gh", "hn", "reddit"}


def usage(code=2):
    print((__doc__ or "usage: harvest.py <topic_key> [--topics topics.json]").strip())
    sys.exit(code)


def load_topics(path):
    p = pathlib.Path(path)
    if not p.exists():
        usage(f"topics file not found: {p}")
    topics = json.loads(p.read_text(encoding="utf-8"))
    # normalize: allow ["ch","q",n] lists or ("ch","q",n) tuples-as-lists
    return {t: [tuple(x) for x in qs] for t, qs in topics.items()}


def post(url, headers, payload, timeout=45):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", **UA, **headers},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def exa(q, n, rot):
    if not EXA:
        print("  [exa] SKIP (EXA_KEYS not set)", flush=True)
        return [], rot
    body = {"query": q, "numResults": n, "contents": {"text": {"maxCharacters": 1500}}}
    for off in range(len(EXA)):
        key = EXA[(rot + off) % len(EXA)]
        try:
            j = post("https://api.exa.ai/search", {"x-api-key": key}, body)
            out = [{"title": it.get("title", ""), "url": it.get("url", ""),
                    "snippet": (it.get("text") or "")[:1500],
                    "date": it.get("publishedDate", "")} for it in j.get("results", [])]
            return out, rot + off
        except Exception:
            continue
    return [], rot


def tavily(q, n):
    key = os.environ.get("TAVILY_KEY")
    if not key:
        print("  [tavily] SKIP (TAVILY_KEY not set)", flush=True)
        return []
    j = post("https://api.tavily.com/search", {"Authorization": "Bearer " + key},
             {"query": q, "max_results": n, "search_depth": "advanced"})
    return [{"title": it.get("title", ""), "url": it.get("url", ""),
             "snippet": (it.get("content") or "")[:1200], "date": ""}
            for it in j.get("results", [])]


def you(q, n):
    key = os.environ.get("YOU_KEY")
    if not key:
        print("  [you] SKIP (YOU_KEY not set)", flush=True)
        return []
    j = post("https://ydc-index.io/v1/search", {"X-API-Key": key}, {"query": q})
    web = (j.get("results") or {}).get("web") or j.get("hits") or []
    return [{"title": it.get("title", ""), "url": it.get("url", ""),
             "snippet": " ".join(it.get("snippets", []) if isinstance(it.get("snippets"), list) else [it.get("description", "")])[:1000],
             "date": ""} for it in web[:n]]


def rstack(channel, q, n):
    if not RSTACK or not pathlib.Path(RSTACK).exists():
        print(f"  [{channel}] SKIP (RSTACK_PATH not set)", flush=True)
        return []
    cmd = [sys.executable, "-u", RSTACK]
    if channel == "rss":
        cmd += ["rss", "news", q, str(n), "ru"]
    elif channel == "gh":
        cmd += ["gh", "repos", q, str(n)]
    elif channel == "yt":
        cmd += ["yt", "search", q, str(n)]
    elif channel == "hn":
        cmd += ["hn", q, str(n)]
    elif channel == "reddit":
        cmd += ["reddit", q, str(n)]
    elif channel == "fc":
        cmd += ["fc", "search", q, str(n)]
    else:
        return []
    r = subprocess.run(cmd + ["--json"], capture_output=True, text=True, timeout=200,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return []
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return []
    # rstack v2 returns {"web": [...]} for fc search; plain list for others
    if isinstance(data, dict):
        data = data.get("web") or data.get("results") or []
    return [{"title": it.get("title", ""), "url": it.get("url", ""),
             "snippet": (it.get("snippet") or "")[:1200],
             "date": it.get("date", "")} for it in (data if isinstance(data, list) else [])]


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        usage(0)
    topics_file = "topics.example.json"
    if "--topics" in args:
        i = args.index("--topics")
        topics_file = args[i + 1]
        del args[i:i + 2]
    topics = load_topics(topics_file)
    if args[0] == "--list":
        for t, qs in topics.items():
            print(f"{t}: {len(qs)} queries")
        return
    topic = args[0]
    if topic not in topics:
        usage(f"unknown topic '{topic}'. Available: {', '.join(sorted(topics))}")
    plan = topics[topic]
    RAW.mkdir(exist_ok=True)
    out_path = RAW / f"harvest_{topic}.jsonl"
    seen = set()
    if out_path.exists():
        for ln in out_path.read_text(encoding="utf-8").splitlines():
            try:
                seen.add(json.loads(ln)["url"])
            except Exception:
                pass
    rot = 0
    n_new = 0
    with out_path.open("a", encoding="utf-8") as f:
        for channel, q, n in plan:
            try:
                if channel == "exa":
                    recs, rot = exa(q, n, rot)
                elif channel == "tavily":
                    recs = tavily(q, n)
                elif channel == "you":
                    recs = you(q, n)
                else:
                    recs = rstack(channel, q, n)
            except Exception as e:
                print(f"  [{channel}] FAIL {type(e).__name__}: {str(e)[:80]}", flush=True)
                continue
            got = 0
            for rec in recs:
                if not rec["url"] or rec["url"] in seen:
                    continue
                seen.add(rec["url"])
                rec.update({"topic": topic, "channel": channel, "query": q})
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                got += 1
                n_new += 1
            print(f"  [{channel}] {got} new ({q[:50]})", flush=True)
            time.sleep(1)
    print(f"DONE {topic}: {n_new} new, {len(seen)} total", flush=True)
    if n_new == 0 and not seen:
        # Все каналы SKIP/пустые (нет ключей или RSTACK_PATH) — это НЕ «пустая тема».
        # Громко, чтобы swarm --resume это подхватил, а не маскировал под успех.
        print("WARNING: 0 new AND 0 total — проверь SEARCH_API_FARM_SECRETS/ключи "
              "(SKIP-строки выше)", flush=True)
        sys.exit(3)


if __name__ == "__main__":
    main()
