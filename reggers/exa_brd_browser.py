"""Exa via BrightData Scraping Browser (cloud CDP with built-in unlocking)."""
import asyncio, json, sys, time
from pathlib import Path
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))         # reg_base.py sits beside this script
sys.path.insert(0, str(_HERE.parent))  # secrets_env.py sits at the repo root
from secrets_env import brd_cdp  # noqa: E402
from reg_base import pick_email, save_result, wait_verify

ZONE = "mcp_browser"
CDP = brd_cdp(ZONE)
AUTH_URL = "https://auth.exa.ai/?callbackUrl=https%3A%2F%2Fdashboard.exa.ai%2F"
print("CDP: brd.superproxy.io:9222 zone=" + ZONE, flush=True)


async def dump(page, tag):
    d = await page.evaluate(
        """() => {
            const o = {url: location.href, txt: (document.body.innerText||'').slice(0,400), inputs: []};
            for (const i of document.querySelectorAll('input')) o.inputs.push((i.name||i.id||i.type)+':'+(i.value||'').length);
            return o;
        }""")
    print(f"[{tag}] url={d['url'][:95]}", flush=True)
    print(f"[{tag}] txt={d['txt'][:230].replace(chr(10),' | ')}", flush=True)
    print(f"[{tag}] inputs={json.dumps(d['inputs'])}", flush=True)
    return d


async def main():
    from patchright.async_api import async_playwright
    p = await async_playwright().start()
    browser = await p.chromium.connect_over_cdp(CDP, timeout=120000)
    ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
    page = await ctx.new_page()
    email, epw = pick_email("exa")
    print("email:", email, flush=True)
    key = None
    try:
        await page.goto(AUTH_URL, timeout=120000, wait_until="domcontentloaded")
        await page.wait_for_timeout(10000)
        await dump(page, "auth")

        await page.fill("input[type=email]", email, timeout=15000)
        await page.wait_for_timeout(4000)

        # watch turnstile (Scraping Browser solves it server-side, may take a while)
        TS_JS = "() => { const el=document.querySelector('input[name=\"cf-turnstile-response\"],textarea[name=\"cf-turnstile-response\"]'); return el ? (el.value||'').length : -1; }"
        CLICK_JS = "() => { for (const b of document.querySelectorAll('button')) if ((b.innerText||'').trim()==='Continue') { b.click(); return true; } return false; }"
        for _ in range(30):
            ts = await page.evaluate(TS_JS)
            if ts and ts > 10:
                print("  turnstile SOLVED len:", ts, flush=True)
                break
            await page.wait_for_timeout(4000)
        else:
            print("  turnstile not solved yet, clicking anyway", flush=True)

        # click Continue, retry while blocked (token may land after first click)
        d = {}
        for attempt in range(8):
            # wait for token BEFORE clicking (avoids wasted blocked attempts)
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
            d = await dump(page, f"after-continue-{attempt}")
            txt = (d.get("txt") or "").lower()
            if "verification challenge" not in txt:
                print("PASSED", flush=True)
                break
            print(f"  BLOCKED (attempt {attempt})", flush=True)

        t0 = time.time()
        link, code = None, None
        while time.time() - t0 < 240:
            link, code = wait_verify(email, epw, ["exa"], ["exa.ai"], timeout=60, code_regex=r"\b\d{6}\b")
            if code or link:
                break
        print("code:", code, "link:", (link or "")[:90], flush=True)

        if link:
            import html as _html
            clean = _html.unescape(link).rstrip("]).,;>")
            print("verify url:", clean[:110], flush=True)
            await page.goto(clean, timeout=120000, wait_until="domcontentloaded")
            await page.wait_for_timeout(9000)
            await dump(page, "after-link")
            # "Confirm your sign-in" -> click Continue
            for _ in range(3):
                clicked = await page.evaluate("""() => {
                    const bs = [...document.querySelectorAll('button,a')];
                    const b = bs.find(x => {
                        const t = (x.innerText||'').trim();
                        return t.length < 60 && /continue|confirm|verify|sign in|finish|dashboard/i.test(t);
                    });
                    if (b) { b.click(); return (b.innerText||'').trim(); }
                    return null;
                }""")
                if not clicked:
                    break
                print("  clicked:", clicked, flush=True)
                await page.wait_for_timeout(10000)
                await dump(page, "after-confirm")
                if "dashboard.exa.ai" in page.url:
                    break
        elif code:
            boxes = await page.evaluate("() => [...document.querySelectorAll('input')].filter(i=>i.type==='text' && (i.maxLength<=2||i.inputMode==='numeric')).length")
            if boxes >= 6:
                for idx, ch in enumerate(code):
                    await page.evaluate("""([i,c]) => { const ins=[...document.querySelectorAll('input')].filter(x=>x.type==='text'); if(ins[i]) { ins[i].value=c; ins[i].dispatchEvent(new Event('input',{bubbles:true})); } }""", [idx, ch])
                    await page.wait_for_timeout(150)
            else:
                await page.fill("input[type=text]", code, timeout=8000)
            await page.wait_for_timeout(2000)
            await page.evaluate("""() => { for (const b of document.querySelectorAll('button')) { const t=(b.innerText||'').trim(); if (['Continue','Verify','Submit','Confirm'].includes(t)) { b.click(); return; } } const f=document.querySelector('form'); if(f) f.requestSubmit(); }""")
            await page.wait_for_timeout(12000)
            await dump(page, "after-code")

        # settle: wait out Vercel checkpoint, then clear onboarding (redirect is async)
        ONB_JS = """() => {
            const all=[...document.querySelectorAll('button,a,label,div[role=radio],input,span')];
            const txt=x=>((x.innerText||x.value||'')+'').trim();
            const log=[];
            const o1=all.find(x=>/build with the api/i.test(txt(x)));
            if (o1){try{o1.click();log.push('api');}catch(e){}}
            const o2=all.find(x=>/i don't know yet|web search tool|coding agent|news monitoring/i.test(txt(x)));
            if (o2){try{o2.click();log.push('build');}catch(e){}}
            const fwd=all.find(x=>/^continue$/i.test(txt(x)))
                   ||all.find(x=>/^(next|get started|submit|let's go|start)$/i.test(txt(x)))
                   ||all.find(x=>/go to dashboard/i.test(txt(x)));
            if (fwd){fwd.click();log.push(txt(fwd));return log.join('+');}
            const sk=all.find(x=>/^skip/i.test(txt(x)));
            if (sk){sk.click();return 'skip';}
            return null;
        }"""
        VERCEL_WORDS = ["verificando", "checkpoint", "punto de control", "verifying your browser", "security check"]

        async def wait_vercel():
            for _ in range(12):
                try:
                    t = (await page.evaluate("() => (document.body.innerText||'').slice(0,300)")).lower()
                except Exception:
                    return
                if not any(w in t for w in VERCEL_WORDS):
                    return
                print("  vercel checkpoint, waiting...", flush=True)
                await page.wait_for_timeout(6000)

        async def clear_onboarding(rounds=8):
            for step in range(rounds):
                try:
                    if "onboarding" not in page.url and "welcome" not in page.url:
                        return
                    await page.wait_for_timeout(3000)
                    # real clicks via locators (base-ui radios need trusted events)
                    acts = []
                    for label in ["Build with the API", "I don't know yet", "Web search tool"]:
                        try:
                            loc = page.get_by_text(label, exact=False).first
                            await loc.click(timeout=4000)
                            acts.append(label[:12])
                            await page.wait_for_timeout(1200)
                        except Exception:
                            pass
                    # report Continue disabled state
                    state = await page.evaluate("""() => {
                        const bs=[...document.querySelectorAll('button')];
                        const c=bs.find(x=>/^continue$/i.test((x.innerText||'').trim()));
                        const g=bs.find(x=>/go to dashboard/i.test((x.innerText||'').trim()));
                        const s=bs.find(x=>/^skip/i.test((x.innerText||'').trim()));
                        const rad=[...document.querySelectorAll('input[type=radio]')].map(r=>r.checked);
                        return {cont: c?{dis:c.disabled,aria:c.getAttribute('aria-disabled')}:null,
                                go: g?{dis:g.disabled}:null, skip: s?{dis:s.disabled}:null, radios: rad};
                    }""")
                    print(f"  onb[{step}] acts={acts} state={json.dumps(state)}", flush=True)
                    # click Continue (real), else Go to Dashboard, else Skip
                    for nm in ["Continue", "Go to Dashboard", "Skip", "Next"]:
                        try:
                            btn = page.get_by_role("button", name=nm).first
                            await btn.click(timeout=4000)
                            print(f"  onb[{step}] real-clicked:", nm, flush=True)
                            break
                        except Exception:
                            continue
                except Exception as e:
                    print("  onb nav:", str(e)[:60], flush=True)
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                await page.wait_for_timeout(3000)

        await wait_vercel()
        await clear_onboarding()

        # dashboard api-keys with navigation-interrupt protection
        for attempt in range(5):
            try:
                await page.goto("https://dashboard.exa.ai/api-keys", timeout=120000, wait_until="domcontentloaded")
            except Exception as e:
                print(f"  goto keys interrupted ({str(e)[:60]}), clearing onboarding", flush=True)
                await page.wait_for_timeout(5000)
                await wait_vercel()
                await clear_onboarding()
                continue
            await page.wait_for_timeout(8000)
            await wait_vercel()
            if "onboarding" in page.url:
                await clear_onboarding()
                continue
            d = await dump(page, f"keys-{attempt}")
            if d.get("inputs") or (d.get("txt") or "").strip():
                break
        # list all buttons for diagnosis
        btns = await page.evaluate("() => [...document.querySelectorAll('button,a')].map(b=>(b.innerText||'').trim()).filter(t=>t&&t.length<40).slice(0,40)")
        print("  buttons:", json.dumps(btns, ensure_ascii=False)[:500], flush=True)
        # click Create Key (real locator click)
        ck = None
        for nm in ["Create Key", "Create key", "New Key", "Create"]:
            try:
                await page.get_by_role("button", name=nm).first.click(timeout=5000)
                ck = nm
                break
            except Exception:
                continue
        print("  create-key click:", ck, flush=True)
        await page.wait_for_timeout(5000)
        # dump modal: inputs + buttons inside dialog
        modal = await page.evaluate("""() => {
            const o = {inputs: [], buttons: [], txt: ''};
            const dlg = document.querySelector('[role=dialog],.modal,[class*=modal],[class*=dialog]') || document.body;
            o.txt = (dlg.innerText||'').slice(0,500);
            for (const i of dlg.querySelectorAll('input,textarea')) o.inputs.push({name:i.name||i.id||i.placeholder||i.type, type:i.type, val:(i.value||'').slice(0,40)});
            for (const b of dlg.querySelectorAll('button')) { const t=(b.innerText||'').trim(); if(t) o.buttons.push(t.slice(0,30)); }
            return o;
        }""")
        print("  modal txt:", modal["txt"][:280].replace(chr(10)," | "), flush=True)
        print("  modal inputs:", json.dumps(modal["inputs"]), flush=True)
        print("  modal buttons:", json.dumps(modal["buttons"]), flush=True)
        # fill key name if there is a text input
        try:
            name_input = page.locator('[role=dialog] input[type=text], [role=dialog] input:not([type]), .modal input[type=text]').first
            await name_input.fill("farm-key", timeout=5000)
            print("  filled name", flush=True)
        except Exception:
            try:
                await page.locator('input[type=text]').first.fill("farm-key", timeout=4000)
                print("  filled name (fallback)", flush=True)
            except Exception:
                pass
        await page.wait_for_timeout(1500)
        # submit modal
        sub = None
        for nm in ["Create", "Create Key", "Save", "Submit", "Confirm", "Generate"]:
            try:
                await page.get_by_role("button", name=nm).first.click(timeout=4000)
                sub = nm
                break
            except Exception:
                continue
        print("  modal submit:", sub, flush=True)
        await page.wait_for_timeout(9000)
        # dump modal / full page
        full = await page.evaluate("""() => {
            const o = {txt: (document.body.innerText||'').slice(0,1800), codes: [], inputs: [], storage: []};
            for (const c of document.querySelectorAll('code,pre,textarea')) { const t=(c.textContent||c.value||'').trim(); if (t.length>15) o.codes.push(t.slice(0,120)); }
            for (const i of document.querySelectorAll('input')) if (i.value && i.value.length>15) o.inputs.push(i.value.slice(0,120));
            try { for (let k=0;k<localStorage.length;k++){const key=localStorage.key(k); const v=localStorage.getItem(key)||''; if(/[0-9a-f]{8}-[0-9a-f]{4}/.test(v)) o.storage.push(key+'='+v.slice(0,120));} } catch(e){}
            return o;
        }""")
        print("  full txt:", full["txt"][:700].replace(chr(10), " | "), flush=True)
        print("  codes:", json.dumps(full["codes"])[:400], flush=True)
        print("  inputs:", json.dumps(full["inputs"])[:300], flush=True)
        print("  storage:", json.dumps(full["storage"])[:300], flush=True)
        # harvest UUID key from page content only (NOT localStorage = tracking pixels)
        import re as _re
        on_keys_page = "api-keys" in page.url
        blob = full["txt"] + " " + " ".join(full["codes"]) + " " + " ".join(full["inputs"])
        uuids = [u for u in _re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", blob)]
        print("  on_keys_page:", on_keys_page, "uuids:", uuids[:5], flush=True)
        key = uuids[0] if (uuids and on_keys_page) else None

    except Exception as e:
        print("ERR:", str(e)[:250], flush=True)
    finally:
        save_result("exa", {"email": email, "pw": "brd-scraping-browser", "api_key": key,
                            "status": "ok" if key else "no-key"})
        if key:
            open(str(_HERE / r"exa_new_key.txt"), "a", encoding="utf-8").write(key + "\n")
        try:
            await browser.close()
        except Exception:
            pass
    print("KEY:", key, flush=True)

if __name__ == "__main__":
    asyncio.run(main())