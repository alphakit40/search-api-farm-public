import sys, asyncio, json, re
from pathlib import Path
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))         # reg_base.py sits beside this script
sys.path.insert(0, str(_HERE.parent))  # secrets_env.py sits at the repo root
from reg_base import (pick_email, mark_used, wait_verify, save_result, rnd_pass,
                      solve_turnstile, launch)

SVC = "tavily"
OUT = str(_HERE / r"tavily_result.json")
CREDS = str(_HERE / r"tavily_creds.json")
FALLBACK_SK = "0x4AAAAAACwSuI5jPtwnNwc5"

async def dump(page, tag):
    f = await page.evaluate("""() => {
        const o = {inputs: [], buttons: [], captcha: null, errors: []};
        document.querySelectorAll('input:not([type=hidden])').forEach(i => { if (i.offsetParent !== null || i.type==='password') o.inputs.push(i.type+':'+(i.name||i.id)+':'+(i.className||'')); });
        document.querySelectorAll('button').forEach(b => { const t=(b.innerText||'').trim(); if(t) o.buttons.push(t.slice(0,40)); });
        const cap = document.querySelector('[data-captcha-sitekey]');
        if (cap) o.captcha = cap.getAttribute('data-captcha-provider') + '|' + cap.getAttribute('data-captcha-sitekey');
        if (document.querySelector('iframe[src*="challenges.cloudflare.com"]')) o.captcha = (o.captcha||'') + '|cf-iframe';
        document.querySelectorAll('.ulp-input-error-message:not(.hide)').forEach(e => { const t=(e.innerText||'').trim(); if(t) o.errors.push(t.slice(0,120)); });
        return o;
    }""")
    print(f"[{tag}] url={page.url}\n[{tag}] {json.dumps(f)}", flush=True)
    return f

async def captcha_state(page):
    return await page.evaluate("""() => {
        const cap = document.querySelector('[data-captcha-sitekey]');
        if (cap) return [cap.getAttribute('data-captcha-provider')||'', cap.getAttribute('data-captcha-sitekey')];
        const tsf = document.querySelector('iframe[src*="challenges.cloudflare.com"]');
        if (tsf) return ['turnstile-iframe', ''];
        return [null, null];
    }""")

async def solve_auth0_captcha(page):
    kind, sk = await captcha_state(page)
    if not kind:
        return None
    if not sk:
        sk = FALLBACK_SK
    print("[captcha]", kind, sk, flush=True)
    tok = solve_turnstile(sk, page.url)
    await page.evaluate("""([tok]) => {
        const set = (el) => { if (el) { el.value = tok; el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); } };
        set(document.querySelector('input[name="captcha"]'));
        set(document.querySelector('textarea[name="cf-turnstile-response"]'));
        set(document.querySelector('[name="cf-turnstile-response"]'));
    }""", [tok])
    await page.wait_for_timeout(800)
    return None

async def click_continue(page):
    btn = page.locator('button[data-action-button-primary]').first
    if await btn.count():
        await btn.click(timeout=8000)
    else:
        await page.locator("button[type=submit]").first.click(timeout=8000)

def fail(page, reason):
    try:
        asyncio.get_event_loop().create_task(page.screenshot(path=str(_HERE / f"{SVC}_2_fail.png")))
    except Exception:
        pass
    save_result(SVC, {"provider": SVC, "email": globals().get("email", ""),
                      "password": globals().get("pw", ""), "api_key": "",
                      "status": reason, "verify": False})
    print("[FAIL]", reason, flush=True)

async def main():
    email, mailpw = pick_email(SVC)
    mark_used(SVC, email)
    pw = rnd_pass()
    globals()["email"] = email; globals()["pw"] = pw; globals()["mailpw"] = mailpw
    print("[1] email:", email, flush=True)
    p, browser, ctx, page = await launch()

    try:
        await page.goto("https://app.tavily.com/signup", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2500)
        await page.locator("a", has_text="Sign up").first.click(timeout=8000)
        await page.wait_for_timeout(2500)
        await dump(page, "signup")

        await page.locator("input#email").fill(email)
        await click_continue(page)
        await page.wait_for_timeout(3500)
        d = await dump(page, "after-email")
        if d["captcha"]:
            await solve_auth0_captcha(page)
            await click_continue(page)
            await page.wait_for_timeout(3500)
            d = await dump(page, "after-captcha")

        pwf = page.locator("input#password:visible, input[name=password]:visible")
        if await pwf.count():
            await pwf.first.fill(pw)
            name = page.locator("input#name, input[name=name], input#username, input[name=username]")
            if await name.count() and (await name.first.input_value() or "") == "":
                await name.first.fill(email.split("@")[0])
            await click_continue(page)
            await page.wait_for_timeout(5000)
            d = await dump(page, "after-password")
            if d["captcha"]:
                await solve_auth0_captcha(page)
                await click_continue(page)
                await page.wait_for_timeout(5000)
                await dump(page, "after-pw-captcha")
        else:
            return fail(page, "no-password-screen")

        # save creds IMMEDIATELY (password never lost again)
        json.dump({"email": email, "mail_pw": mailpw, "password": pw},
                  open(CREDS, "w"), indent=1)
        print("[creds saved]", CREDS, flush=True)

        print("[2] waiting verify email...", flush=True)
        link, code = wait_verify(email, mailpw,
            ["tavily", "verify", "confirm"], ["tavily.com"], timeout=240)
        print("[2] link:", (link or "")[:90], flush=True)
        if not link:
            return fail(page, "no-verify-email")

        # click verify link in the logged-in context (page holds session)
        try:
            await page.goto(link, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print("[verify-goto] soft-fail", e, flush=True)
        await page.wait_for_timeout(10000)
        print("[3] after link:", page.url, flush=True)
        await page.screenshot(path=str(_HERE / r"tavily_verify.png"))

        key = await find_key(page)
        if not key:
            return fail(page, "no-key-found")
        print("[4] key:", key[:16] + "…", flush=True)

        ok = verify_live(key)
        print("[5] live verify:", ok, flush=True)
        save_result(SVC, {"provider": "tavily", "email": email, "mail_pw": mailpw,
                          "password": pw, "api_key": key,
                          "status": "ok" if ok else "verify-failed", "verify": ok})
        json.dump({"ok": bool(ok), "key": key[:16],
                   "status": "ok" if ok else "verify-failed", "verify": ok},
                  open(OUT, "w"))
        print("[DONE]", ok, flush=True)
        await browser.close(); await p.stop()
    except Exception as e:
        import traceback; traceback.print_exc()
        try: fail(page, f"error:{e}")
        except Exception: pass
        try:
            await browser.close(); await p.stop()
        except Exception:
            pass

async def find_key(page):
    routes = ["/home", "/api-keys", "/keys", "/overview", "/settings/api-keys", "/settings"]
    for r in routes:
        try:
            await page.goto("https://app.tavily.com" + r, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        for _ in range(3):
            await page.wait_for_timeout(3000)
            body = await page.content()
            m = re.search(r"tvly-[A-Za-z0-9\-_]{20,}", body)
            if m:
                return m.group(0)
            # try to click key-related elements
            for sel in ["text=API Keys", "text=API keys", "text=Keys",
                        "a[href*='key']", "button:has-text('Create')", "button:has-text('Generate')"]:
                loc = page.locator(sel).first
                try:
                    if await loc.count() and await loc.is_visible():
                        await loc.click(timeout=3000)
                        await page.wait_for_timeout(3000)
                        break
                except Exception:
                    pass
        print("[key-scan]", page.url, "not found", flush=True)
    return None

def verify_live(key):
    import urllib.request, urllib.error
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=json.dumps({"query": "test"}).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print("[verify] HTTP", r.status, r.read()[:150], flush=True)
            return r.status == 200
    except urllib.error.HTTPError as e:
        print("[verify] HTTP", e.code, e.read()[:200], flush=True)
        return e.code == 200
    except Exception as e:
        print("[verify] err", e, flush=True)
        return False

if __name__ == "__main__":
    asyncio.run(main())
