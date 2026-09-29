"""Search1API (s1.dev) regger — Clerk FAPI signup + browser key extraction.

Пайплайн на аккаунт (~90 с):
  1) Turnstile (YesCaptcha) → Clerk FAPI sign_up (urllib, без браузера)
  2) prepare email_code → IMAP OTP (t-online pool) → attempt → сессия
  3) браузер: sign-in паролем (OTP не нужен) → /api-keys → перехват
     TanStack serverFn `matchedKeys` → UUID-ключ (создаётся автоматически)
  4) live-verify ключа на api.search1api.com/search

Каждый аккаунт = 100 free-кредитов.

Использование:
    python -u s1_reg.py [N]          # N аккаунтов, default 1
    python -u s1_reg.py --verify     # live-проверка всех active-ключей
"""
import asyncio, http.cookiejar, json, pathlib, re, sys, urllib.error, urllib.parse, urllib.request

from reg_base import pick_email, rnd_pass, save_result, mark_used, solve_turnstile, wait_verify, launch

FAPI = "https://clerk.s1.dev"
PAGE = "https://app.s1.dev/sign-up"
CLERK_VER = "6.34.1"        # берётся из трафика clerk.s1.dev; протухшая версия → 400
TS_KEY = "0x4AAAAAAAWXJGBD7bONzLBd"  # Turnstile sitekey, РОТИРУЕТСЯ: при 400 смотри
                                      # challenge-platform/…/turnstile/…/<sitekey>/auto в трафике
# Ключ возвращает TanStack serverFn `matchedKeys` на /api-keys; хеш функции в URL
# ротируется между билдами → ловим ЛЮБОЙ /_serverFn/-ответ и ищем UUID в payload.
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150.0.0.0",
      "Content-Type": "application/x-www-form-urlencoded",
      "Origin": "https://app.s1.dev", "Referer": PAGE}
UUID_RE = re.compile(r'"s":"([0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12})"')
# Фикс сети, где резолвер отдаёт для *.challenges.cloudflare.com только IPv6 без маршрута
# (браузер молча зависает на Clerk-форме без ERR в консоли):
CHROME_ARGS = ["--host-resolver-rules=MAP *.challenges.cloudflare.com 104.18.94.41"]

_opener = None


def call(path, data, timeout=30):
    q = urllib.parse.urlencode(dict(data, _clerk_js_version=CLERK_VER))
    req = urllib.request.Request(FAPI + path, data=q.encode(), headers=UA, method="POST")
    op = _opener
    assert op is not None, "call() before signup()"  # _opener живёт только внутри signup-сессии
    try:
        with op.open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            return e.code, {}


def signup(email, imap_pw, pw):
    """Clerk FAPI signup; True = аккаунт верифицирован (сессия создана)."""
    global _opener
    cj = http.cookiejar.CookieJar()   # общий jar ОБЯЗАТЕЛЕН на всех вызовах, иначе 401
    _opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    req = urllib.request.Request(FAPI + f"/v1/client?_clerk_js_version={CLERK_VER}", headers=UA)
    with _opener.open(req, timeout=30) as r:
        r.read()
    tok = solve_turnstile(TS_KEY, PAGE)
    print("  [turnstile]", len(tok), flush=True)
    st, d = call("/v1/client/sign_ups",
                 {"email_address": email, "password": pw, "captcha_token": tok})
    su = ((d.get("client") or {}).get("sign_up") or d.get("response") or {})
    su_id = su.get("id", "")
    print("  [sign_up]", st, su.get("status"), flush=True)
    if not su_id:
        print("  [err]", json.dumps(d.get("errors", ""), ensure_ascii=False)[:150], flush=True)
        return False
    st, d = call(f"/v1/client/sign_ups/{su_id}/prepare_verification", {"strategy": "email_code"})
    if st != 200:
        print("  [prepare]", st, flush=True)
        return False
    _, code = wait_verify(email, imap_pw, ["search1api", "s1.dev", "clerk"], [],
                          timeout=240, code_regex=r"\b(\d{6})\b")
    if not code:
        print("  [imap] no code", flush=True)
        return False
    print("  [code] ok", flush=True)
    st, d = call(f"/v1/client/sign_ups/{su_id}/attempt_verification",
                 {"strategy": "email_code", "code": code})
    su = ((d.get("client") or {}).get("sign_up") or d.get("response") or {})
    print("  [attempt]", st, su.get("status"), flush=True)
    return su.get("status") == "complete"


async def fetch_key(email, pw):
    """Браузер: sign-in → /api-keys → UUID из matchedKeys serverFn."""
    _, browser, _, page = await launch(args=CHROME_ARGS)
    found = {"key": ""}

    async def on_resp(resp):
        if "/_serverFn/" in resp.url:
            try:
                m = UUID_RE.findall(await resp.text())
            except Exception:
                return
            if m:
                found["key"] = m[0]

    page.on("response", lambda r: asyncio.ensure_future(on_resp(r)))
    try:
        await page.goto("https://app.s1.dev/sign-in", timeout=60000, wait_until="domcontentloaded")
        await page.wait_for_timeout(8000)
        await page.fill("input[name='identifier']", email, timeout=15000)
        await page.locator("button.cl-formButtonPrimary:has-text('Continue')").first.click(timeout=8000)
        await page.wait_for_timeout(4000)
        await page.fill("input[name='password']", pw, timeout=8000)
        await page.locator("button.cl-formButtonPrimary:has-text('Continue')").first.click(timeout=8000)
        for _ in range(15):
            await page.wait_for_timeout(3000)
            if "sign-in" not in page.url:
                break
        if "sign-in" in page.url:
            print("  [browser] sign-in stuck", flush=True)
            return ""
        await page.goto("https://app.s1.dev/api-keys", timeout=45000, wait_until="domcontentloaded")
        await page.wait_for_timeout(7000)
        print("  [browser] key:", found["key"] or "NONE", flush=True)
        return found["key"]
    finally:
        await browser.close()


def verify_live(key):
    """POST api.search1api.com/search; UA обязателен — без него CF 1010."""
    req = urllib.request.Request(
        "https://api.search1api.com/search",
        data=json.dumps({"query": "ping", "max_results": 1}).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                 "User-Agent": UA["User-Agent"]}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status == 200
    except Exception:
        return False


def verify_all():
    res = json.loads(pathlib.Path(__file__).with_name("search1api_result.json")
                     .read_text(encoding="utf-8"))
    act = [r for r in res if r.get("status") == "active"]
    ok = 0
    for r in act:
        st = verify_live(r["api_key"])
        ok += st
        print(" ", r["email"][:30].ljust(30), r["api_key"][:13] + "…", "LIVE" if st else "DEAD", flush=True)
    print(f"LIVE: {ok}/{len(act)}")


async def main():
    if "--verify" in sys.argv:
        verify_all()
        return
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    for i in range(n):
        email, imap_pw = pick_email("search1api_clerk")
        pw = rnd_pass()
        print(f"[s1 #{i+1}] {email}", flush=True)
        if not signup(email, imap_pw, pw):
            save_result("search1api", {"provider": "search1api", "email": email, "password": pw,
                                       "email_pw": imap_pw, "api_key": "", "status": "fail: signup"})
            continue
        key = await fetch_key(email, pw)
        live = verify_live(key) if key else False
        if key and live:
            mark_used("search1api_clerk", email)
        save_result("search1api", {"provider": "search1api", "email": email, "password": pw,
                                   "email_pw": imap_pw, "api_key": key,
                                   "status": "active" if live else ("key-unverified" if key else "no-key")})
        print(f"[s1 #{i+1}] DONE:", "ACTIVE" if live else "partial", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
