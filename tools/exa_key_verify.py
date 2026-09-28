"""Live-verify one Exa API key.

Usage:
    python -u tools/exa_key_verify.py            # first key from EXA_KEYS
    python -u tools/exa_key_verify.py <api-key>  # explicit key (never echoed back)
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from secrets_env import key_list, redact  # noqa: E402


def resolve() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    available = key_list("EXA_KEYS")
    if available:
        return available[0]
    sys.exit("[exa] no key: pass one as argv[1] or set EXA_KEYS in secrets.env")


cred = resolve()
print("verifying key:", redact(cred))
body = json.dumps({"query": "test search", "numResults": 1}).encode()
request = urllib.request.Request(
    "https://api.exa.ai/search", data=body, method="POST",
    headers={"x-api-key": cred, "Content-Type": "application/json",
             "Accept": "application/json"})
try:
    with urllib.request.urlopen(request, timeout=40) as r:
        print("STATUS:", r.status)
        print("BODY:", r.read().decode("utf-8", "ignore")[:400])
except urllib.error.HTTPError as e:
    print("HTTPError:", e.code, e.read().decode("utf-8", "ignore")[:250])
    sys.exit(1)
except Exception as e:
    print("ERR:", type(e).__name__, str(e)[:150])
    sys.exit(1)
