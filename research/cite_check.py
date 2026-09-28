"""Deterministic citation checker for REPORT.md.
For every inline citation [https://...] in the report:
  - fetch the page (urllib; optional firecrawl fallback via rstack)
  - word-overlap score between the citing sentence and the page text
  - verdict: OK / WEAK (alive, thin overlap) / ARCHIVED (wayback only) / DEAD
Writes verify/cite_report.json. DEAD/ARCHIVED = failure.

Usage: python -u cite_check.py [REPORT.md]
Env: RESEARCH_ROOT (default: script dir), RSTACK_PATH (optional fc fallback).
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(os.environ.get("RESEARCH_ROOT", pathlib.Path(__file__).resolve().parent))
RSTACK = os.environ.get("RSTACK_PATH") or None
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

STOP = set("""и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз тоже себе под будет ж тогда кто этот того потому этого какой совсем ним здесь этом один почти мой тем чтобы нее сейчас были куда зачем всех никогда можно при наконец два об другой хоть после над больше тот через эти нас про всего них какая много разве три эту моя впрочем хорошо свою этой перед иногда лучше чуть том нельзя такой им более всегда конечно всю между the a an and or of to in is are was were for on with at by from as it its this that these those be been have has had not no yes you your we our they their he she his her them us""".split())

URL_RE = re.compile(r"\[((?:https?|tg)://[^\]\s]+)\]")
WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]{4,}")


def fetch_urllib(url):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read(400_000)
            return r.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return 0, ""


def fetch_fc(url):
    if not RSTACK or not pathlib.Path(RSTACK).exists():
        return 0, ""
    try:
        r = subprocess.run([sys.executable, "-u", RSTACK, "fc", "scrape", url, "--json"],
                           capture_output=True, text=True, timeout=200,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            return 0, ""
        data = json.loads(r.stdout)
        if data and isinstance(data, list):
            return 200, data[0].get("markdown", "") or data[0].get("snippet", "")
    except Exception:
        pass
    return 0, ""


def wayback(url):
    api = f"https://web.archive.org/cdx/search/cdx?url={urllib.parse.quote(url, safe='')}&limit=1&from=2020&output=json"
    st, body = fetch_urllib(api)
    if st == 200 and body:
        try:
            rows = json.loads(body)
            return len(rows) > 1
        except Exception:
            return False
    return False


def words(text):
    return {w.lower() for w in WORD_RE.findall(text)} - STOP


def support_score(sentence, page_text):
    sw = words(sentence)
    if len(sw) < 3:
        return None  # sentence too thin to judge
    pw = words(page_text[:200_000])
    return len(sw & pw) / len(sw)


def main():
    report_path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "REPORT.md"
    report = report_path.read_text(encoding="utf-8")
    # sentence = line fragment around the citation
    claims = []  # (url, sentence)
    for line in report.splitlines():
        for m in URL_RE.finditer(line):
            url = m.group(1)
            sent = line[:m.start()].strip(" -|*#")
            claims.append((url, sent[-300:]))
    # dedup by url, keep longest sentence
    by_url = {}
    for url, sent in claims:
        if url not in by_url or len(sent) > len(by_url[url]):
            by_url[url] = sent

    results = []
    ok = 0
    for i, (url, sent) in enumerate(sorted(by_url.items()), 1):
        st, text = fetch_urllib(url)
        method = "urllib"
        if st != 200:
            st2, text2 = fetch_fc(url)
            if text2:
                st, text, method = st2, text2, "fc"
        alive = st == 200 and bool(text.strip())
        wb = False
        if not alive:
            wb = wayback(url)
        score = support_score(sent, text) if alive else None
        verdict = "OK" if (alive and (score is None or score >= 0.35)) else \
                  ("WEAK" if alive else ("ARCHIVED" if wb else "DEAD"))
        if verdict in ("OK", "WEAK"):
            ok += 1
        results.append({"url": url, "http": st, "via": method, "alive": alive,
                        "wayback": wb, "support": None if score is None else round(score, 2),
                        "verdict": verdict, "claim": sent[:140]})
        print(f"[{i:02d}/{len(by_url)}] {verdict:8} http={st} sup={score if score is None else round(score,2)} {url[:90]}", flush=True)

    (ROOT / "verify").mkdir(exist_ok=True)
    (ROOT / "verify" / "cite_report.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nVERIFIED {ok}/{len(by_url)} citations alive+supported "
          f"(WEAK counts as alive; DEAD/ARCHIVED = failure)")


if __name__ == "__main__":
    main()
