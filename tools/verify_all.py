# -*- coding: utf-8 -*-
"""Search API Farm — live-verify всех ключей одним прогоном.

Каждый сервис проверяется РЕАЛЬНЫМ API-вызовом (не доверием к DOM).
Ключи берутся из окружения (secrets.env) — в коде и в отчёте их нет.
Сервис без ключа в env = SKIP (не падение); настроенный ключ с ошибкой = FAIL.

Usage: python -u tools/verify_all.py
Exit:  0 — все настроенные ключи живы; 1 — есть FAIL.
Отчёт: <repo>/verify/verify_results.json (значения ключей обрезаны через redact()).
"""
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from secrets_env import key_list, opt, redact  # noqa: E402

REPORT = Path(__file__).resolve().parents[1] / "verify" / "verify_results.json"

# (label, service, env var)
SINGLE = [
    ("tavily2",   "tavily",    "TAVILY_KEY"),
    ("serpwrap",  "serpwrap",  "SERPWRAP_KEY"),
    ("you.com",   "you",       "YOU_KEY"),
    ("firecrawl", "firecrawl", "FIRECRAWL_KEY"),
    ("jina",      "jina",      "JINA_KEY"),
]

RESULTS = []   # (name, svc, status, code, note, key_id)


def _post(url, headers, data):
    return urllib.request.Request(
        url, data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers}, method="POST")


def _get(url, headers):
    return urllib.request.Request(url, headers=headers)


def check(name, svc, request, key_id):
    """Один live-вызов; пишет (name, svc, status, code, note, key_id)."""
    try:
        with urllib.request.urlopen(request, timeout=45) as r:
            body = r.read().decode("utf-8", "replace")
            RESULTS.append((name, svc, "OK", r.status, _note(svc, body), key_id))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        RESULTS.append((name, svc, "FAIL", e.code, body[:110], key_id))
    except Exception as e:
        # str(e) может содержать URL с ключом — режем до типа и короткого описания
        RESULTS.append((name, svc, "FAIL", 0, f"{type(e).__name__}: {str(e)[:90]}", key_id))


def skip(name, svc, var):
    RESULTS.append((name, svc, "SKIP", 0, f"{var} not set in environment", ""))


def _note(svc, body):
    """Вытащить полезное из ответа (баланс/кредиты/cost) по имени СЕРВИСА.

    Диспетчеризация по svc, а не по label: лейблы бывают `tavily2`, `exa3`,
    `you.com` — сравнение с `tavily`/`you` по ним не срабатывало и в отчёт
    печаталось сырое тело ответа.
    """
    try:
        j = json.loads(body)
    except Exception:
        return body[:90]
    if svc == "exa":
        c = j.get("costDollars", {}).get("total")
        return f"cost ${c}" if c is not None else body[:90]
    if svc == "serpwrap":
        c = j.get("credits")
        # наблюдались обе формы: {"credits":{...,"remaining":N}} и плоская {"remaining":N}
        if isinstance(c, dict) and "remaining" in c:
            return f"credits remaining {c['remaining']}"
        if isinstance(j, dict) and "remaining" in j:
            return f"credits remaining {j['remaining']}"
        return f"credits {c if c is not None else j}"
    if svc == "firecrawl":
        if j.get("success"):
            md = (j.get("data") or {}).get("markdown") or ""
            return f"scrape ok, markdown {len(md)} chars"
        return f"credits {j.get('credits', body[:60])}"
    if svc == "tavily":
        ans = j.get("answer")
        if ans:
            return f"answer: {str(ans)[:60]}"
        res = j.get("results")
        return f"results {len(res) if isinstance(res, list) else res}"
    if svc == "you":
        web = (j.get("results") or {}).get("web")
        if isinstance(web, list):
            return f"web hits {len(web)}"
        h = j.get("hits")
        return f"hits {len(h) if isinstance(h, list) else h}"
    if svc == "jina":
        return f"results {len(j.get('data', []))}"
    return body[:90]


def main():
    print(f"Search API Farm live-verify {datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 78)

    exa_keys = key_list("EXA_KEYS")
    if exa_keys:
        for i, k in enumerate(exa_keys, 1):
            label = "exa" if i == 1 else f"exa{i}"
            check(label, "exa",
                  _post("https://api.exa.ai/search", {"x-api-key": k},
                        {"query": "pi", "numResults": 1}),
                  redact(k))
    else:
        skip("exa", "exa", "EXA_KEYS")

    for label, svc, var in SINGLE:
        key = opt(var)
        if not key:
            skip(label, svc, var)
            continue
        kid = redact(key)
        if svc == "tavily":
            check(label, svc, _post("https://api.tavily.com/search",
                                    {"Authorization": f"Bearer {key}"},
                                    {"query": "pi"}), kid)
        elif svc == "serpwrap":
            check(label, svc, _get("https://serpwrap.com/api/v2/credits",
                                   {"X-API-KEY": key, "User-Agent": "Mozilla/5.0"}), kid)
        elif svc == "you":
            check(label, svc, _post("https://ydc-index.io/v1/search",
                                    {"X-API-Key": key}, {"query": "pi"}), kid)
        elif svc == "firecrawl":
            check(label, svc, _post("https://api.firecrawl.dev/v2/scrape",
                                    {"Authorization": f"Bearer {key}"},
                                    {"url": "https://example.com",
                                     "formats": ["markdown"]}), kid)
        elif svc == "jina":
            check(label, svc, _post("https://s.jina.ai/v1/search",
                                    {"Authorization": f"Bearer {key}"},
                                    {"q": "pi"}), kid)

    ok = sum(1 for r in RESULTS if r[2] == "OK")
    failed = sum(1 for r in RESULTS if r[2] == "FAIL")
    skipped = sum(1 for r in RESULTS if r[2] == "SKIP")
    for name, svc, status, code, note, kid in RESULTS:
        print(f"{status:>4}  {name:<11} {code:>3}  {kid:<18} {note}")
    print("=" * 78)
    print(f"{ok} живых / {failed} мертвых / {skipped} не настроено  (всего {len(RESULTS)})")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(
        [{"name": n, "service": s, "status": st, "code": c, "note": nt, "key": kid,
          "ts": datetime.now().isoformat(timespec="seconds")}
         for n, s, st, c, nt, kid in RESULTS],
        indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"saved -> {REPORT}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
