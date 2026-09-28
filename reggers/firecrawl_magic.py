"""Firecrawl: sign in via magic link -> key."""
import sys, asyncio, json
from pathlib import Path
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))         # reg_base.py sits beside this script
sys.path.insert(0, str(_HERE.parent))  # secrets_env.py sits at the repo root
from secrets_env import req  # noqa: E402
from reg_base import launch, wait_verify

EMAIL = req("FIRECRAWL_EMAIL")
_res = _HERE / "firecrawl_result.json"
recs = json.loads(_res.read_text(encoding="utf-8")) if _res.exists() else []
EPW = next((r.get("email_pw") for r in recs if r.get("email") == EMAIL), None)
if not EPW:
    sys.exit("[firecrawl] no stored password for FIRECRAWL_EMAIL in "
             "firecrawl_result.json — this script RESUMES an existing signup; "
             "run a full registration first")


async def dump(page, tag):
    d = await page.evaluate(
        """() => {
            const o = {url: location.href, txt: (document.body.innerText||'').slice(0,200), btns: []};
            for (const b of document.querySelectorAll('button,a')) { const t=(b.innerText||'').trim(); if (t && t.length<40) o.btns.push(t); }
            return o;
        }""")
    print(f"[{tag}] url={d['url'][:85]} btns={json.dumps(d['btns'])[:250]}", flush=True)
    print(f"[{tag}] txt={d['txt'][:130]}".replace("\n", " | "), flush=True)
    return d


async def main():
    p, browser, ctx, page = await launch()
    try:
        await ctx.grant_permissions(["clipboard-read", "clipboard-write"])
    except Exception:
        pass
    key = None
    try:
        await page.goto("https://www.firecrawl.dev/signin?view=signin", timeout=90000, wait_until="domcontentloaded")
        await page.wait_for_selector("input[name=email]", timeout=30000)
        # click magic link button
        await page.evaluate("""() => { const b=[...document.querySelectorAll('button,a')].find(x=>/magic link/i.test(x.innerText||'')); if(b) b.click(); }""")
        await page.wait_for_timeout(5000)
        await dump(page, "magic-view")
        # fill email, submit
        try:
            await page.fill("input[name=email]", EMAIL, timeout=10000)
        except Exception:
            await page.evaluate(f"""() => {{ const i=document.querySelector('input[type=email],input[name=email]'); if(i) {{ i.value='{EMAIL}'; i.dispatchEvent(new Event('input',{{bubbles:true}})); }} }}""")
        await page.evaluate("""() => { const f=document.querySelector('form'); if(f){const b=f.querySelector('button[type=submit]')||f.querySelector('button:not([type])'); if(b){b.click();return;} f.requestSubmit();} }""")
        await page.wait_for_timeout(10000)
        await dump(page, "after-send")
        # wait magic link email
        link, code = wait_verify(EMAIL, EPW, ["firecrawl"], ["auth/v1/"], timeout=180)
        if link:
            link = link.rstrip("]).,;>")
        print("magic link:", (link or "")[:100], flush=True)
        if link:
            await page.goto(link, timeout=90000, wait_until="domcontentloaded")
            await page.wait_for_timeout(12000)
            await dump(page, "after-magic")
            # onboarding click-through
            for i in range(5):
                if "onboarding" not in page.url:
                    break
                await page.evaluate("""() => { const bs=[...document.querySelectorAll('button,a')]; const b=bs.find(x=>{const t=(x.innerText||'').trim().toLowerCase(); return t==='skip'||t==='continue'||t==='next'||t==='get started';}); if(b) b.click(); }""")
                await page.wait_for_timeout(5000)
            await page.goto("https://www.firecrawl.dev/app/api-keys", timeout=90000, wait_until="domcontentloaded")
            await page.wait_for_timeout(9000)
            print("keys url:", page.url[:90], flush=True)
            d = await page.evaluate("""() => { const m=(document.body.innerText||'').match(/fc-[A-Za-z0-9_-]{20,}/); const mask=(document.body.innerText||'').match(/fc-[A-Za-z0-9•*]{6,}/); return {k:m?m[0]:null, mask:mask?mask[0]:null, txt:(document.body.innerText||'').slice(0,350)}; }""")
            print("keys txt:", d["txt"][:300].replace("\n", " | "), flush=True)
            key = d.get("k")
            if not key and d.get("mask"):
                # click copy buttons near key row
                for i in range(6):
                    info = await page.evaluate("""() => {
                        const el = [...document.querySelectorAll('*')].find(x => /fc-[A-Za-z0-9•*]{6,}/.test(x.textContent||'') && x.children.length<=2 && (x.innerText||'').length<60);
                        if (el) { let row=el; for (let k=0;k<4&&row.parentElement;k++) row=row.parentElement;
                            const cl=[]; for (const b of row.querySelectorAll('button,[role=button]')) { cl.push(b.innerText||b.getAttribute('aria-label')||''); b.click(); }
                            return cl; }
                        return null;
                    }""")
                    print(f"[row{i}]", json.dumps(info, ensure_ascii=False)[:200], flush=True)
                    await page.wait_for_timeout(2000)
                    try:
                        clip = await page.evaluate("() => navigator.clipboard.readText()")
                        if clip and clip.startswith("fc-"):
                            key = clip
                            break
                    except Exception:
                        pass
                    k2 = await page.evaluate("() => { const m=(document.body.innerText||'').match(/fc-[A-Za-z0-9_-]{20,}/); return m?m[0]:null; }")
                    if k2:
                        key = k2
                        break
        print("KEY:", key, flush=True)
        try:
            await page.screenshot(path=str(_HERE / "firecrawl_magic.png"))
        except Exception:
            pass
    except Exception as e:
        print("ERR:", str(e)[:200], flush=True)
    finally:
        if key:
            for r in recs:
                if r.get("email") == EMAIL:
                    r["api_key"] = key
                    r["status"] = "ok"
            open(str(_HERE / r"firecrawl_result.json"), "w", encoding="utf-8").write(json.dumps(recs, ensure_ascii=False, indent=1))
            print("[patched] firecrawl_result.json", flush=True)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())