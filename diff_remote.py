"""Diff the local publish allowlist against the remote repo tree.

The repo is public, so this reads it anonymously over plain HTTPS — no gh CLI
(which timed out at 120s), no token, and it proves the public view at the same time.
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from secrets_env import opt  # noqa: E402
from gh_publish import allowlist  # noqa: E402

REPO = opt("GH_REPO") or "alphakit40/search-api-farm-public"
HEADERS = {"User-Agent": "allowlist-diff", "Accept": "application/vnd.github+json"}
# Authenticated on purpose: the anonymous API allows 60 req/h per IP and a 25-file
# read-back burns that in one run. The token goes in the header and is never logged.
_token = opt("GH_PAT")
if _token:
    HEADERS["Authorization"] = "Bearer " + _token


def get(url: str):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:200]
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def main() -> int:
    status, body = get(f"https://api.github.com/repos/{REPO}/git/trees/HEAD?recursive=1")
    if status != 200:
        print(f"tree fetch HTTP {status}: {body[:200]}")
        return 1

    remote = {t["path"] for t in json.loads(body)["tree"] if t["type"] == "blob"}
    local = set(allowlist())
    missing = sorted(local - remote)
    extra = sorted(remote - local)

    print(f"local allowlist : {len(local)}")
    print(f"remote blobs    : {len(remote)}")
    print(f"MISSING remotely: {missing or 'none'}")
    print(f"extra remotely  : {extra or 'none'}")
    for m in missing:
        p = ROOT / m
        print(f"  {m}: exists={p.exists()} "
              f"bytes={p.stat().st_size if p.exists() else '-'}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
