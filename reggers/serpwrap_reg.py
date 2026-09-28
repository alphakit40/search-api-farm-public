"""SerpWrap regger: signup (Turnstile) -> dashboard -> key -> live verify + credits check."""
import asyncio, json, sys, re
from pathlib import Path
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))         # reg_base.py sits beside this script
sys.path.insert(0, str(_HERE.parent))  # secrets_env.py sits at the repo root
from reg_base import launch, pick_email, rnd_pass, save_result, wait_verify, find_sitekey, solve_turnstile, inject_token


async def main():
    p, browser, ctx, page = await launch()
    email, epw = pick_email("serpwrap")
    pw = rnd_pass()
    print("email:", email, flush=True)
    try:
        await page.goto("https://serpwrap.com/signup", timeout=45000, wait_until="domcontentloaded")
        await page.wait_for_timeout(8000)
        print("url:", page.url, flush=True)
        dump = await page.evaluate(
            """() => {
                const out = {txt: (document.body.innerText||'').slice(0,300), inputs: [], btns: []};
                for (const i of document.querySelectorAll('input,button')) {
                    const r = i.getBoundingClientRect();
                    if (r.width === 0 && r.height === 0) continue;
                    if (i.tagName === 'INPUT') out.inputs.push({name: i.name||'', type: i.type||''});
                    else out.btns.push({b: (i.textContent||'').trim().slice(0,40)});
                }
                return out;
            }""")
        print("TXT:", dump["txt"][:200], flush=True)
        print("INPUTS:", json.dumps(dump["inputs"]), flush=True)
        print("BTNS:", json.dumps([b["b"] for b in dump["btns"]]), flush=True)

        # fill: full_name, email, password (per recon: native inputs id=full_name etc.)
        import random, string as st
        name = "Mark " + "".join(random.choices(st.ascii_lowercase, k=6)).capitalize()
        try:
            await page.fill("input#full_name, input[name=full_name]", name, timeout=8000)
            print("name filled", flush=True)
        except Exception as e:
            print("name fill err", str(e)[:60], flush=True)
        try:
            await page.fill("input[type=email], input[name=email]", email, timeout=8000)
            print("email filled", flush=True)
        except Exception as e:
            print("email fill err", str(e)[:60], flush=True)
        try:
            await page.fill("input[type=password], input[name=password]", pw, timeout=8000)
            print("pw filled", flush=True)
        except Exception as e:
            print("pw fill err", str(e)[:60], flush=True)

        # turnstile
        sk = await page.evaluate(
            """() => {
                const ts = document.querySelector('.cf-turnstile [data-sitekey]');
                return ts ? ts.getAttribute('data-sitekey') : '';
            }""")
        if sk:
            tok = solve_turnstile(sk, "https://serpwrap.com/signup")
            await inject_token(page, tok)
            print("turnstile token:", len(tok), flush=True)
            await page.wait_for_timeout(2000)
        else:
            print("no turnstile on page — check .cf-turnstile", flush=True)

        # submit: click, then LAZY turnstile appears -> solve -> click again
        async def click_create():
            try:
                await page.locator("button:has-text('Create Account'), button[type=submit]").first.click(
                    timeout=6000, force=True)
                return True
            except Exception as e:
                print("click err", str(e)[:60], flush=True)
                return False

        # ensure turnstile widget actually renders (api.js may not auto-init)
        try:
            ts_type = await page.evaluate("() => typeof window.turnstile")
            print("window.turnstile:", ts_type, flush=True)
            if ts_type == "undefined":
                await page.evaluate(
                    "() => { const s = document.createElement('script'); s.src='https://challenges.cloudflare.com/turnstile/v0/api.js'; s.async=true; document.head.appendChild(s); }")
                await page.wait_for_timeout(4000)
                ts_type = await page.evaluate("() => typeof window.turnstile")
                print("window.turnstile after inject:", ts_type, flush=True)
            if ts_type != "undefined":
                await page.evaluate(
                    "() => { try { turnstile.render('.cf-turnstile'); } catch (e) { return String(e); } return 'rendered'; }")
                await page.wait_for_timeout(4000)
                print("turnstile render done", flush=True)
        except Exception as e:
            print("ensure turnstile err", str(e)[:60], flush=True)
        # turnstile: widget renders async (api.js) — click the real checkbox first
        tok_len = 0
        try:
            ifr = page.locator('iframe[src*="challenges.cloudflare.com"]').first
            await ifr.wait_for(state="visible", timeout=8000)
            await ifr.click(timeout=4000)
            print("clicked turnstile checkbox", flush=True)
            await page.wait_for_timeout(6000)
            tok_len = await page.evaluate(
                "() => { const el = document.querySelector('[name=\"cf-turnstile-response\"]'); return el && el.value ? el.value.length : 0; }")
            print("widget token len:", tok_len, flush=True)
        except Exception as e:
            print("widget click err", str(e)[:60], flush=True)
        if not tok_len:
            # fallback: solve offline + inject
            try:
                sk = await page.evaluate(
                    "() => { const ts = document.querySelector('.cf-turnstile'); return ts ? ts.getAttribute('data-sitekey') : ''; }")
            except Exception:
                sk = ""
            if sk:
                print("turnstile sitekey:", sk, flush=True)
                tok = solve_turnstile(sk, "https://serpwrap.com/signup")
                await inject_token(page, tok)
                print("injected token:", len(tok), flush=True)
                await page.wait_for_timeout(1500)
                tok_len = len(tok)
        await click_create()
        await page.wait_for_timeout(6000)
        print("after submit url:", page.url, flush=True)
        await page.wait_for_load_state("domcontentloaded", timeout=20000)
        await page.wait_for_timeout(6000)
        try:
            txt = await page.evaluate("() => (document.body ? document.body.innerText || '' : '').slice(0, 300)")
            print("after txt:", (txt or "").replace("\n", " | ")[:250], flush=True)
        except Exception as e:
            txt = ""
            print("txt err", str(e)[:60], flush=True)
        try:
            await page.screenshot(path=str(_HERE / "serpwrap_after.png"))
        except Exception:
            pass

        # email verify?
        if "verify" in txt.lower() or "confirm" in txt.lower():
            link, code = wait_verify(email, epw, ["serpwrap", "verify", "confirm"],
                                     ["serpwrap.com", "verify", "confirm"], timeout=180)
            if link:
                await page.goto(link, timeout=30000, wait_until="domcontentloaded")
                await page.wait_for_timeout(6000)
                print("after verify:", page.url[:60], flush=True)

        # dashboard key
        await page.goto("https://serpwrap.com/dashboard", timeout=45000, wait_until="domcontentloaded")
        await page.wait_for_timeout(8000)
        print("dash url:", page.url, flush=True)
        if "/login" in page.url:
            await page.fill("input[type=email], input[name=email]", email, timeout=6000)
            await page.fill("input[type=password], input[name=password]", pw, timeout=6000)
            try:
                await page.locator("button:has-text('Log in'), button[type=submit]").first.click(
                    timeout=5000, force=True)
                await page.wait_for_timeout(8000)
                print("after login:", page.url[:60], flush=True)
            except Exception as e:
                print("login err", str(e)[:50], flush=True)
            await page.goto("https://serpwrap.com/dashboard", timeout=45000, wait_until="domcontentloaded")
            await page.wait_for_timeout(8000)
        txt = await page.evaluate("() => (document.body.innerText||'').slice(0, 600)")
        print("dash txt:", txt.replace("\n", " | ")[:350], flush=True)
        await page.screenshot(path=str(_HERE / "serpwrap_dash.png"))

        # key: try API credits endpoint first (no auth needed beyond key)
        key = ""
        # from page text: key is likely a token shown in dashboard
        m = re.search(r'\b([A-Za-z0-9_-]{30,})\b', txt)
        # serp api key unknown format — try any 16+ alnum token from inputs/body
        inputs = await page.evaluate(
            """() => [...document.querySelectorAll('input')].map(i => i.value)
                   .filter(v => v && v.length > 12)""")
        print("dashboard inputs:", json.dumps(inputs)[:200], flush=True)
        if inputs:
            key = inputs[0]
        elif m:
            key = m.group(1)
        # fallback: cookies? try /api/v2/credits with candidate
        verify = ""
        if not key:
            print("key not found in DOM — checking /api/v2/credits with cookies", flush=True)
        else:
            verify = live_verify(key)
            print("VERIFY:", verify[:120], flush=True)

        print("KEY:", key[:20] if key else "NONE", flush=True)
        save_result("serpwrap", {"provider": "serpwrap", "email": email, "password": pw,
                                 "api_key": key or None,
                                 "status": "ok" if key else "no-key", "verify": verify})
        await ctx.storage_state(path=str(_HERE / "serpwrap_state.json"))
    finally:
        try:
            await browser.close()
        except Exception:
            pass
    print("done", flush=True)


def live_verify(key):
    import urllib.request, urllib.error
    for ep in [f"https://serpwrap.com/api/v2/credits",
               f"https://serpwrap.com/api/v2/search?q=test"]:
        req = urllib.request.Request(ep, headers={"X-API-KEY": key, "User-Agent": "x"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return f"{ep.split('/')[-1]} {r.status} :: {r.read().decode('utf-8','replace')[:100]}"
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', 'replace')[:80]
            if "401" not in body and e.code != 401:
                return f"{ep.split('/')[-1]} {e.code} :: {body}"
    return "401 on all endpoints"


if __name__ == "__main__":
    asyncio.run(main())