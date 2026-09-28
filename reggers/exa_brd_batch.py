"""Exa BATCH registration via BrightData Scraping Browser (WORKING flow).

Usage: python -u exa_brd_batch.py [COUNT]
Per account: CDP -> Turnstile auto-solved -> email magic-link -> Vercel -> onboarding
(real clicks) -> api-keys -> Create Key modal -> harvest UUID secret key.
Keys appended to exa_new_key.txt + exa_result.json.
"""
import asyncio, json, sys, time, html as _html, re as _re
from pathlib import Path
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))         # reg_base.py sits beside this script
sys.path.insert(0, str(_HERE.parent))  # secrets_env.py sits at the repo root
from secrets_env import brd_cdp  # noqa: E402
from reg_base import pick_email, save_result, wait_verify

CDP = brd_cdp("mcp_browser")
AUTH_URL = "https://auth.exa.ai/?callbackUrl=https%3A%2F%2Fdashboard.exa.ai%2F"
KEYFILE = str(_HERE / r"exa_new_key.txt")
COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 3

TS_JS = "() => { const el=document.querySelector('input[name=\"cf-turnstile-response\"],textarea[name=\"cf-turnstile-response\"]'); return el ? (el.value||'').length : -1; }"
CLICK_JS = "() => { for (const b of document.querySelectorAll('button')) if ((b.innerText||'').trim()==='Continue') { b.click(); return true; } return false; }"
VERCEL_WORDS = ["verificando", "checkpoint", "punto de control", "verifying your browser", "security check"]


async def reg_one(p, idx):
    email, epw = pick_email("exa")
    print(f"\n{'='*64}\n[{idx}] email={email}\n{'='*64}", flush=True)
    browser = None
    key = None
    try:
        browser = await p.chromium.connect_over_cdp(CDP, timeout=120000)
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await ctx.new_page()

        await page.goto(AUTH_URL, timeout=120000, wait_until="domcontentloaded")
        await page.wait_for_timeout(7000)
        await page.fill("input[type=email]", email, timeout=15000)
        await page.wait_for_timeout(3000)

        # wait turnstile token, then Continue with retry
        passed = False
        for attempt in range(8):
            ts = await page.evaluate(TS_JS)
            if not (ts and ts > 10):
                for _ in range(25):
                    await page.wait_for_timeout(4000)
                    ts = await page.evaluate(TS_JS)
                    if ts and ts > 10:
                        print("  turnstile SOLVED len:", ts, flush=True)
                        break
            await page.evaluate(CLICK_JS)
            await page.wait_for_timeout(12000)
            txt = (await page.evaluate("() => (document.body.innerText||'').slice(0,300)")).lower()
            if "verification challenge" not in txt:
                print("  PASSED", flush=True)
                passed = True
                break
            print(f"  BLOCKED attempt={attempt}", flush=True)
        if not passed:
            print("  FAILED turnstile", flush=True)
            return None

        # verify link
        t0 = time.time()
        link, code = None, None
        while time.time() - t0 < 240:
            link, code = wait_verify(email, epw, ["exa"], ["exa.ai"], timeout=60, code_regex=r"\b\d{6}\b")
            if code or link:
                break
        print("  link:", (link or "")[:60], "code:", code, flush=True)
        if link:
            clean = _html.unescape(link).rstrip("]).,;>")
            await page.goto(clean, timeout=120000, wait_until="domcontentloaded")
            await page.wait_for_timeout(9000)
            for _ in range(3):
                clicked = await page.evaluate("""() => {
                    const bs=[...document.querySelectorAll('button,a')];
                    const b=bs.find(x=>{const t=(x.innerText||'').trim(); return t.length<60 && /continue|confirm|verify|sign in|finish|dashboard/i.test(t);});
                    if (b) { b.click(); return (b.innerText||'').trim(); }
                    return null;
                }""")
                if not clicked:
                    break
                print("  clicked:", clicked, flush=True)
                await page.wait_for_timeout(10000)
                if "dashboard.exa.ai" in page.url:
                    break

        # wait vercel
        async def wait_vercel():
            for _ in range(12):
                try:
                    t = (await page.evaluate("() => (document.body.innerText||'').slice(0,300)")).lower()
                except Exception:
                    return
                if not any(w in t for w in VERCEL_WORDS):
                    return
                await page.wait_for_timeout(6000)

        # onboarding via REAL locator clicks
        async def clear_onboarding(rounds=8):
            for step in range(rounds):
                try:
                    if "onboarding" not in page.url and "welcome" not in page.url:
                        return
                    await page.wait_for_timeout(3000)
                    for label in ["Build with the API", "I don't know yet", "Web search tool"]:
                        try:
                            await page.get_by_text(label, exact=False).first.click(timeout=4000)
                            await page.wait_for_timeout(1000)
                        except Exception:
                            pass
                    for nm in ["Continue", "Go to Dashboard", "Skip", "Next"]:
                        try:
                            await page.get_by_role("button", name=nm).first.click(timeout=4000)
                            print(f"  onb[{step}] clicked:", nm, flush=True)
                            break
                        except Exception:
                            continue
                except Exception as e:
                    print("  onb nav:", str(e)[:50], flush=True)
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                await page.wait_for_timeout(3000)

        await wait_vercel()
        await clear_onboarding()

        # api-keys with navigation protection
        for attempt in range(5):
            try:
                await page.goto("https://dashboard.exa.ai/api-keys", timeout=120000, wait_until="domcontentloaded")
            except Exception as e:
                print(f"  goto interrupted ({str(e)[:50]}), clear onboarding", flush=True)
                await page.wait_for_timeout(5000)
                await wait_vercel()
                await clear_onboarding()
                continue
            await page.wait_for_timeout(8000)
            await wait_vercel()
            if "onboarding" in page.url:
                await clear_onboarding()
                continue
            t = await page.evaluate("() => (document.body.innerText||'').slice(0,150)")
            if t.strip():
                break

        # Create Key -> modal -> fill name -> submit
        ck = None
        for nm in ["Create Key", "Create key", "New Key", "Create"]:
            try:
                await page.get_by_role("button", name=nm).first.click(timeout=5000)
                ck = nm
                break
            except Exception:
                continue
        print("  create-key:", ck, flush=True)
        await page.wait_for_timeout(5000)
        try:
            await page.locator('[role=dialog] input[type=text], [role=dialog] input:not([type])').first.fill("farm-key", timeout=5000)
        except Exception:
            try:
                await page.locator('input[type=text]').first.fill("farm-key", timeout=4000)
            except Exception:
                pass
        await page.wait_for_timeout(1500)
        sub = None
        for nm in ["Create a Key", "Create", "Save", "Submit", "Confirm", "Generate"]:
            try:
                await page.get_by_role("button", name=nm).first.click(timeout=4000)
                sub = nm
                break
            except Exception:
                continue
        print("  modal submit:", sub, flush=True)
        await page.wait_for_timeout(9000)

        # harvest key from page content (NOT localStorage)
        full = await page.evaluate("""() => {
            const o = {txt:(document.body.innerText||'').slice(0,1800), codes:[], inputs:[]};
            for (const c of document.querySelectorAll('code,pre,textarea')) { const t=(c.textContent||c.value||'').trim(); if(t.length>15) o.codes.push(t.slice(0,120)); }
            for (const i of document.querySelectorAll('input')) if (i.value && i.value.length>15) o.inputs.push(i.value.slice(0,120));
            return o;
        }""")
        on_keys = "api-keys" in page.url
        blob = full["txt"] + " " + " ".join(full["codes"]) + " " + " ".join(full["inputs"])
        uuids = _re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", blob)
        print("  on_keys:", on_keys, "inputs:", json.dumps(full["inputs"])[:200], "uuids:", uuids[:4], flush=True)
        key = uuids[0] if (uuids and on_keys) else None
    except Exception as e:
        print("  ERR:", str(e)[:200], flush=True)
    finally:
        save_result("exa", {"email": email, "pw": "brd-batch", "api_key": key,
                            "status": "ok" if key else "no-key"})
        if key:
            open(KEYFILE, "a", encoding="utf-8").write(key + "\n")
            print(f"  ✅ KEY: {key}", flush=True)
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
    return key


async def main():
    from patchright.async_api import async_playwright
    p = await async_playwright().start()
    keys = []
    for i in range(COUNT):
        k = await reg_one(p, i + 1)
        if k:
            keys.append(k)
        print(f">>> {len(keys)}/{i+1} keys", flush=True)
    print(f"\n{'='*64}\nDONE {len(keys)} keys:\n{'='*64}", flush=True)
    for k in keys:
        print(" ", k, flush=True)

if __name__ == "__main__":
    asyncio.run(main())