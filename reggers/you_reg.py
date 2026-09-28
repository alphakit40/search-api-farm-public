"""you.com (YDC) registration + API key regger.

Flow (2026-09, Descope sign-up-or-in):
  1. you.com/signin -> descope-wc widget renders in CLOSED shadow root
     (hijack attachShadow via init script, drive with isolated_context=False)
  2. email -> 6-digit OTP mail (real code = 6-digit != 101012, html color)
     -> auto-submit (no button; Enter dispatch)
  3. post-login screens (password create / name) if any
  4. you.com/platform (survey walker) -> Create key modal -> key ydc-...
  5. live verify via api.ydc-index.io
WAF: fresh sessions to /signin get Cloudflare-blocked if rapid -> cooldown + retry.
"""
import sys, asyncio, json, re, ssl, imaplib, email as email_lib, time, random, string
from pathlib import Path
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))         # reg_base.py sits beside this script
sys.path.insert(0, str(_HERE.parent))  # secrets_env.py sits at the repo root
from reg_base import launch, save_result, pick_email, rnd_pass

SVC = "you"
SHOT = str(_HERE / r"you_final_{}.png")
log = lambda *a: print(*a, flush=True)

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def snapshot_mids(addr, pw):
    try:
        imap = imaplib.IMAP4_SSL("imap.t-online.de", 993, ssl_context=SSL_CTX, timeout=30)
        imap.login(addr, pw)
        imap.select("INBOX")
        _, ids = imap.search(None, "ALL")
        mids = set(ids[0].split()[-12:]) if ids[0] else set()
        imap.logout()
        return mids
    except Exception:
        return set()


def get_you_code(addr, pw, exclude_mids=None, timeout=240):
    """Real OTP: 6-digit number != 101012 (html color in you.com mail template)."""
    exclude_mids = exclude_mids or set()
    start = time.time()
    while time.time() - start < timeout:
        try:
            imap = imaplib.IMAP4_SSL("imap.t-online.de", 993, ssl_context=SSL_CTX, timeout=30)
            imap.login(addr, pw)
            imap.select("INBOX")
            _, ids = imap.search(None, "ALL")
            ids = ids[0].split()[-10:] if ids[0] else []
            for mid in reversed(ids):
                if mid in exclude_mids:
                    continue
                _, data = imap.fetch(mid, "(RFC822)")
                raw = data[0][1]
                if not isinstance(raw, bytes):
                    continue
                msg = email_lib.message_from_bytes(raw)
                frm = (msg.get("From") or "").lower()
                subj = (msg.get("Subject") or "").lower()
                if "you.com" not in frm and "you.com" not in subj:
                    continue
                body = ""
                for part in msg.walk() if msg.is_multipart() else [msg]:
                    if (part.get_content_type() or "").lower() in ("text/plain", "text/html"):
                        payload = part.get_payload(decode=True)
                        if payload:
                            body += payload.decode(errors="ignore")
                codes = [c for c in re.findall(r"\b(\d{6})\b", body) if c != "101012"]
                if codes:
                    imap.logout()
                    return codes[-1]
            imap.logout()
        except Exception as e:
            log(f"  [imap] {type(e).__name__}: {str(e)[:60]}")
        time.sleep(5)
    return None


INIT = """
window.__sroots = [];
(() => {
  const orig = Element.prototype.attachShadow;
  Element.prototype.attachShadow = function(init) {
    const r = orig.call(this, init);
    window.__sroots.push({root: r, host: this.tagName ? this.tagName.toLowerCase() : 'unknown'});
    return r;
  };
})();
"""

FILL = """([sel, val]) => {
  for (const {root} of window.__sroots) {
    try {
      const f = root.querySelector(sel);
      if (f) { f.value = val; f.dispatchEvent(new Event('input', {bubbles:true, composed:true})); f.dispatchEvent(new Event('change', {bubbles:true, composed:true})); return true; }
    } catch (e) {}
  }
  return false;
}"""

CLICK = """([txt]) => {
  const t = txt.toLowerCase();
  const btns = [];
  for (const {root} of window.__sroots) { try { for (const b of root.querySelectorAll('descope-button')) btns.push(b); } catch (e) {} }
  for (const b of btns) { if ((b.getAttribute('data-type')||'')==='social') continue; if ((b.textContent||'').trim().toLowerCase()===t) { b.click(); return 'exact'; } }
  for (const b of btns) { if ((b.getAttribute('data-type')||'')==='social') continue; if ((b.textContent||'').trim().toLowerCase().includes(t)) { b.click(); return 'incl'; } }
  return null;
}"""

ENTER_CODE = """() => {
  for (const {root} of window.__sroots) {
    const f = root.querySelector('descope-code-field, descope-text-field');
    if (f) {
      f.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true, composed:true}));
      f.dispatchEvent(new KeyboardEvent('keyup', {key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true, composed:true}));
    }
  }
}"""

WIDGET_HAS = """([sel]) => {
  for (const {root} of window.__sroots) {
    try { if (root.querySelector(sel)) return true; } catch (e) {}
  }
  return false;
}"""


async def has_widget(page, sel, rounds=12, delay=4000):
    for _ in range(rounds):
        try:
            if await page.evaluate(WIDGET_HAS, [sel], isolated_context=False):
                return True
        except Exception:
            pass
        await page.wait_for_timeout(delay)
    return False


async def open_signin(page):
    for attempt in range(4):
        try:
            await page.goto("https://you.com/signin", wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            log(f"  goto err: {str(e)[:80]}")
        await page.wait_for_timeout(9000)
        try:
            title = (await page.title()).lower()
        except Exception:
            title = ""
        if "cloudflare" not in title:
            return True
        log(f"  WAF blocked (attempt {attempt}), wait 75s")
        await page.wait_for_timeout(75000)
    return False


def verify_key(key):
    """Live verify: POST https://ydc-index.io/v1/search (per official docs)."""
    import urllib.request, urllib.error
    req = urllib.request.Request(
        "https://ydc-index.io/v1/search",
        data=json.dumps({"query": "test", "count": 3}).encode(),
        headers={"X-API-Key": key, "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            body = r.read().decode(errors="replace")
            n = len(((json.loads(body).get("results") or {}).get("web")) or [])
            return {"ok": True, "status": r.status, "web_results": n,
                    "endpoint": "POST https://ydc-index.io/v1/search"}
    except urllib.error.HTTPError as e:
        if e.code == 429:
            return {"ok": True, "status": 429, "endpoint": "POST https://ydc-index.io/v1/search"}
        return {"ok": False, "status": e.code, "body": e.read()[:150].decode(errors="replace")}
    except Exception as e:
        return {"ok": False, "status": str(e)[:80]}

async def find_keys(page):
    try:
        txt = await page.evaluate("() => document.body.innerText + ' ' + document.documentElement.innerHTML")
    except Exception:
        return []
    return [k for k in set(re.findall(r"ydc-[A-Za-z0-9_-]{10,}", txt))
            if k not in ("ydc-knowledge-samples", "ydc-og-image-rebrand")]


async def signup_and_login(page, email, imap_pw, pw):
    """Descope sign-up-or-in: email -> OTP -> (password/name screens) -> logged in."""
    if not await open_signin(page):
        return "waf-blocked"
    if not await has_widget(page, "descope-email-field"):
        return "no-email-widget"
    pre = await asyncio.to_thread(snapshot_mids, email, imap_pw)
    await page.evaluate(FILL, ["descope-email-field", email], isolated_context=False)
    r = await page.evaluate(CLICK, ["continue"], isolated_context=False)
    log("[2] email submitted:", r)
    await page.wait_for_timeout(8000)
    # OTP code screen
    if not await has_widget(page, "descope-text-field, descope-code-field", rounds=6):
        return "no-code-screen"
    code = await asyncio.to_thread(get_you_code, email, imap_pw, pre, 240)
    log("[3] otp code:", code)
    if not code:
        return "no-otp-mail"
    await page.evaluate(FILL, ["descope-code-field, descope-text-field", code], isolated_context=False)
    r = await page.evaluate(CLICK, ["verify"], isolated_context=False) \
        or await page.evaluate(CLICK, ["continue"], isolated_context=False)
    if not r:
        await page.evaluate(ENTER_CODE, None, isolated_context=False)
        log("[3] enter dispatched")
    else:
        log("[3] code submit:", r)
    await page.wait_for_timeout(12000)
    log("[4] url after code:", page.url)
    # post-code screens for fresh accounts: password create / display name / second code
    for i in range(5):
        if "/signin" not in page.url and "auth.you.com" not in page.url:
            break
        if await has_widget(page, "descope-password-field", rounds=1):
            await page.evaluate(FILL, ["descope-password-field", pw], isolated_context=False)
            await page.evaluate(CLICK, ["continue"], isolated_context=False)
            log(f"[5.{i}] password set")
            await page.wait_for_timeout(9000)
            continue
        texts = await page.evaluate("""() => {
            const out = [];
            for (const {root} of window.__sroots) {
                try { for (const t of root.querySelectorAll('descope-text, descope-enriched-text')) { const tx=(t.textContent||'').trim(); if (tx) out.push(tx); } } catch (e) {}
            }
            return out.join(' | ').toLowerCase();
        }""", None, isolated_context=False)
        if "code" in texts and await has_widget(page, "descope-text-field", rounds=1):
            code = await asyncio.to_thread(get_you_code, email, imap_pw, None, 180)
            log(f"[5.{i}] second code:", code)
            if code:
                await page.evaluate(FILL, ["descope-code-field, descope-text-field", code], isolated_context=False)
                await page.evaluate(CLICK, ["verify"], isolated_context=False) \
                    or await page.evaluate(CLICK, ["continue"], isolated_context=False) \
                    or await page.evaluate(ENTER_CODE, None, isolated_context=False)
                await page.wait_for_timeout(10000)
            continue
        break
    await page.wait_for_timeout(5000)
    log("[5] final url:", page.url)
    if "/signin" in page.url:
        return "login-failed"
    return "ok"


async def survey_and_key(page):
    """Walk /platform onboarding survey, then create API key. Returns key|None."""
    await page.goto("https://you.com/platform", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(8000)
    log("[6] platform url:", page.url)
    for step in range(10):
        keys = await find_keys(page)
        if keys:
            return keys
        log(f"[6] survey step {step}: {page.url[:60]}")
        act = await page.evaluate("""() => {
            const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
            for (const t of ['skip', 'skip survey', 'later']) {
                for (const b of document.querySelectorAll('button, [role=button], a')) {
                    if (!vis(b)) continue;
                    if ((b.innerText || '').trim().toLowerCase() === t) { b.click(); return 'skip'; }
                }
            }
            const opt = [...document.querySelectorAll('input[type=radio], input[type=checkbox]')].filter(vis)[0];
            if (opt) { opt.click(); return 'option'; }
            const ti = [...document.querySelectorAll('input[type=text], input[type=email], textarea')].filter(vis)[0];
            if (ti) {
                const setter = ti.tagName === 'TEXTAREA'
                    ? Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set
                    : Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                setter.call(ti, 'AI agents');
                ti.dispatchEvent(new Event('input', {bubbles: true}));
                ti.dispatchEvent(new Event('change', {bubbles: true}));
                return 'text';
            }
            for (const t of ['continue', 'next', 'submit', 'finish', 'get started', 'done']) {
                for (const b of document.querySelectorAll('button, [role=button], a')) {
                    if (!vis(b)) continue;
                    const tx = (b.innerText || '').trim().toLowerCase();
                    if (tx === t || (tx.includes(t) && tx.length < 30)) { b.click(); return t; }
                }
            }
            return null;
        }""")
        log("    action:", act)
        if act is None and page.url.rstrip("/") == "https://you.com/platform":
            log("[6] survey done")
            break
        await page.wait_for_timeout(7000)
    # create key
    keys = await find_keys(page)
    if keys:
        return keys
    await page.evaluate("""() => {
        for (const b of document.querySelectorAll('button, a, [role=button]')) {
            const t = (b.innerText || '').trim().toLowerCase();
            if (t && t.includes('create key')) { b.click(); return; }
        }
    }""")
    await page.wait_for_timeout(5000)
    await page.evaluate("""() => {
        const i = document.querySelector('input[name=name], input[type=text]');
        if (i) {
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
            setter.call(i, 'regger-key');
            i.dispatchEvent(new Event('input', {bubbles: true}));
            i.dispatchEvent(new Event('change', {bubbles: true}));
        }
    }""")
    await page.wait_for_timeout(1500)
    c = await page.evaluate("""() => {
        const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
        for (const b of document.querySelectorAll('button, [role=button]')) {
            if (!vis(b) || b.disabled) continue;
            if ((b.innerText || '').trim().toLowerCase() === 'create') { b.click(); return 'create'; }
        }
        return null;
    }""")
    log("[7] create clicked:", c)
    await page.wait_for_timeout(10000)
    keys = await find_keys(page)
    if not keys:
        await page.goto("https://you.com/platform/keys", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(8000)
        log("[7] keys page:", page.url)
        keys = await find_keys(page)
    return keys


async def main():
    email, imap_pw = pick_email(SVC)
    pw = rnd_pass()
    log(f"[email] {email}")
    p, browser, ctx, page = await launch()
    await page.add_init_script(INIT)
    rec = {"provider": "you.com", "email": email, "password": pw,
           "api_key": "", "status": "", "verify": None}
    try:
        log("[0] cooldown 60s (WAF)...")
        await page.wait_for_timeout(60000)
        st = await signup_and_login(page, email, imap_pw, pw)
        log("[signup] ->", st)
        if st != "ok":
            await page.screenshot(path=SHOT.format(st))
            rec["status"] = st
            save_result(SVC, rec)
            return
        await page.screenshot(path=SHOT.format("logged"))
        keys = await survey_and_key(page)
        log("[8] keys:", keys[:5] if keys else None)
        await page.screenshot(path=SHOT.format("keys"))
        if not keys:
            rec["status"] = "no-api-key"
            save_result(SVC, rec)
            return
        key = sorted(keys)[0]
        v = verify_key(key)
        log("[9] verify:", v)
        rec.update(api_key=key, status="ok" if v.get("ok") else "verify-fail",
                   verify=v,
                   note="ydc key from you.com/platform; magic-link OTP email auth; $100 free credits")
        if v.get("ok"):
            open(str(_HERE / r"you_real_key.txt"), "w").write(key)
        save_result(SVC, rec)
        log("DONE")
    except Exception:
        import traceback
        log("EXC:", traceback.format_exc()[-1200:])
        try:
            await page.screenshot(path=SHOT.format("exc"))
        except Exception:
            pass
        rec["status"] = "exc"
        save_result(SVC, rec)
    finally:
        try:
            await browser.close()
            await p.stop()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
