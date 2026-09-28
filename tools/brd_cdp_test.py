"""Quick CDP probe for the BrightData Scraping Browser.

Use it to tell "rate-limited / zone dead" apart from "registration script is broken":
if this connects and reports an egress IP, the browser side is healthy.

Credentials come from BRD_CUSTOMER + BRD_ZONE_MCP_BROWSER (see secrets.env.example).
Run with the patchright venv:
    ".../grok-auto/.venv/Scripts/python.exe" -u tools/brd_cdp_test.py
"""
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from secrets_env import brd_cdp  # noqa: E402

CDP = brd_cdp("mcp_browser")

# Playwright echoes the endpoint URL in connect errors, and that URL carries the
# zone password. Never let it reach stdout or a log.
_CRED_URL = re.compile(r"\b(wss?|https?)://[^@\s/]+:[^@\s]+@")


def scrub(msg: str) -> str:
    return _CRED_URL.sub(r"\1://REDACTED:REDACTED@", msg)


async def main() -> int:
    from patchright.async_api import async_playwright
    p = await async_playwright().start()
    try:
        browser = await p.chromium.connect_over_cdp(CDP, timeout=90000)
        print("CDP CONNECTED", flush=True)
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await ctx.new_page()
        await page.goto("https://api.ipify.org?format=json", timeout=60000,
                        wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)
        txt = await page.evaluate("() => document.body.innerText")
        print("egress:", txt[:120], flush=True)
        await browser.close()
        return 0
    except Exception as e:
        print("ERR:", scrub(f"{type(e).__name__}: {e}")[:250], flush=True)
        return 1
    finally:
        await p.stop()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
