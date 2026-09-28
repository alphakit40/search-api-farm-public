"""Prove the repo is genuinely PUBLIC: fetch it with NO credentials at all.

An authenticated check only proves the token works. An anonymous 200 proves
anyone on the internet can read it.
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from secrets_env import opt  # noqa: E402

REPO = opt("GH_REPO") or "alphakit40/search-api-farm-public"
API = f"https://api.github.com/repos/{REPO}"
WEB = f"https://github.com/{REPO}"

# deliberately no Authorization header, no token in env
HEADERS = {"User-Agent": "public-visibility-check", "Accept": "application/vnd.github+json"}


def get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:200]
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


status, body = get(API)
print(f"anonymous GET {API}")
print(f"  HTTP {status}")
if status != 200:
    print("  NOT PUBLIC (anonymous access refused):", body[:160])
    sys.exit(1)

d = json.loads(body)
print(f"  full_name : {d['full_name']}")
print(f"  private   : {d['private']}")
print(f"  visibility: {d.get('visibility')}")
print(f"  branch    : {d['default_branch']}")
print(f"  size      : {d['size']} KB")
print(f"  created   : {d['created_at']}")
print(f"  url       : {d['html_url']}")

# also prove the README itself is anonymously readable
st2, body2 = get(f"{API}/readme")
print(f"\nanonymous GET /readme -> HTTP {st2}, {len(body2)} bytes of JSON")

ok = d["private"] is False and d.get("visibility") == "public"
print("\nRESULT:", "PUBLIC — readable without any credentials" if ok else "NOT PUBLIC")
sys.exit(0 if ok else 1)
