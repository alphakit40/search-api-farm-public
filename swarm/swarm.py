"""Swarm-фан-аут: N воркеров × независимые темы harvest.py, потом digest.

Паттерн «pipeline / fan-out» (см. ../research/STACK.md §2): темы независимы,
LLM-супервизор не нужен — каждый воркер = изолированный subprocess
`python harvest.py <topic>` (падение воркера паркует тему, рой не встаёт).
Merge = digest.py по каждой теме + run_report.json.

Использование (из research/):
    python -u ../swarm/swarm.py --topics topics.json --workers 4
    python -u ../swarm/swarm.py --topics topics.json --workers 4 --digest
    python -u ../swarm/swarm.py --resume          # докрутить темы с exit != 0
"""
import argparse, json, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent / "research"
REPORT = HERE / "run_report.json"


def load_topics(fn):
    return list(json.loads((RESEARCH / fn).read_text(encoding="utf-8")).keys())


def run_topic(topic, topics_fn):
    t0 = time.time()
    r = subprocess.run(
        [sys.executable, "-u", "harvest.py", topic, "--topics", topics_fn],
        cwd=str(RESEARCH), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=1800)
    dt = round(time.time() - t0)
    ok = r.returncode == 0
    print(f"  [{'ok ' if ok else 'ERR'}] {topic} ({dt}s)", flush=True)
    return {"topic": topic, "ok": ok, "sec": dt,
            "err": (r.stderr or r.stdout or "").strip().splitlines()[-1][:200] if not ok else ""}


def fanout(topics, topics_fn, workers):
    print(f"[swarm] {len(topics)} тем × {workers} воркеров", flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(run_topic, t, topics_fn) for t in topics]
        for f in as_completed(futs):
            results.append(f.result())
    return sorted(results, key=lambda r: r["topic"])


def digest_all(topics):
    for t in topics:
        subprocess.run([sys.executable, "-u", "digest.py", t],
                       cwd=str(RESEARCH), timeout=300)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topics", default="topics.example.json")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--digest", action="store_true", help="digest.py по всем темам после фан-аута")
    ap.add_argument("--resume", action="store_true", help="только темы с ok=false из run_report.json")
    a = ap.parse_args()

    if a.resume:
        prev = json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.exists() else []
        topics = [r["topic"] for r in prev if not r["ok"]]
        print(f"[swarm] resume: {len(topics)} упавших тем", flush=True)
    else:
        topics = load_topics(a.topics)
    if not topics:
        print("[swarm] пусто", flush=True)
        return

    results = fanout(topics, a.topics, a.workers)
    if a.digest:
        digest_all([r["topic"] for r in results if r["ok"]])

    REPORT.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(r["ok"] for r in results)
    for r in results:                      # ошибки тем — сразу в консоль, не только в json
        if not r["ok"]:
            print(f"  [fail] {r['topic']}: {r['err']}", flush=True)
    total_src = 0
    for r in results:                      # итог по источникам (raw jsonl, crash-safe счёт)
        f = RESEARCH / "raw" / f"harvest_{r['topic']}.jsonl"
        if f.exists():
            n = sum(1 for _ in f.open(encoding="utf-8"))
            total_src += n
            print(f"  [src ] {r['topic']}: {n}", flush=True)
    print(f"[swarm] DONE {ok}/{len(results)} тем, {total_src} источников -> {REPORT.name}"
          " (--resume для докрутки)", flush=True)


if __name__ == "__main__":
    main()
