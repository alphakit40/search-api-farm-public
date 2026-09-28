"""Live-verify the Firecrawl key from FIRECRAWL_KEY."""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from secrets_env import redact, req  # noqa: E402

cred = req("FIRECRAWL_KEY")
print("verifying key:", redact(cred))

request = urllib.request.Request(
    "https://api.firecrawl.dev/v2/scrape",
    data=json.dumps({"url": "https://example.com", "formats": ["markdown"]}).encode(),
    headers={"Authorization": f"Bearer {cred}", "Content-Type": "application/json"})
try:
    with urllib.request.urlopen(request, timeout=60) as r:
        print("STATUS:", r.status)
        print("BODY:", r.read().decode("utf-8", "ignore")[:300])
except urllib.error.HTTPError as e:
    print("ERR:", e.code, e.read().decode("utf-8", "ignore")[:200])
    sys.exit(1)
except Exception as e:
    print("ERR:", type(e).__name__, str(e)[:120])
    sys.exit(1)
