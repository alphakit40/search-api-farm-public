"""Independent post-publish sweep: downloads every REMOTE file and applies
regexes written from scratch (shares zero code with scan_secrets.py — the
audit point was that scanner and redactor shared one blind-spot set).

Checks: any email, any hex 16-64 under a key-ish JSON field, PATs, UUID keys,
known vendor prefixes, URL userinfo. Exit 1 on any hit.
"""
import base64
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from secrets_env import opt, req  # noqa: E402

REPO = req("GH_REPO")
HDRS = {"User-Agent": "independent-sweep", "Accept": "application/vnd.github+json"}
_tok = opt("GH_PAT")
if _tok:
    HDRS["Authorization"] = "Bearer " + _tok

# written independently of scan_secrets.PATTERNS
SWEEP = {
    "email":        re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}"),
    "kv_secret":    re.compile(r"(?i)(?:key|secret|token|passw?d?|pwd)['\"]?\s*[:=]\s*['\"][\w./+-]{12,}['\"]"),
    "hex_long":     re.compile(r"(?<![\w/])[0-9a-f]{20,64}(?![\w])"),
    "pat":          re.compile(r"(?:ghp|gho|ghu|ghs|ghr|github_pat)_[\w]{16,}"),
    "uuid":         re.compile(r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b"),
    "vendor":       re.compile(r"(?:tvly-|fc-[0-9a-f]|jina_|ydc-sk-|sk-[\w-]{16,}|hl_[0-9a-z]{6,})"),
    "url_userinfo": re.compile(r"[a-z][a-z0-9+.-]*://[^@\s/\"']{2,}:[^@\s\"']{2,}@"),
}
SAFE_EMAIL_DOMAINS = ("example.com", "example.org", "example.invalid",
                      "users.noreply.github.com", "noreply.github.com")
SAFE_HEX_CONTEXTS = ("…REDACTED",)  # our own marker adjacency means already redacted


def get(path):
    req_ = urllib.request.Request(f"https://api.github.com/{path}", headers=HDRS)
    with urllib.request.urlopen(req_, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def main() -> int:
    tree = get(f"repos/{REPO}/git/trees/HEAD?recursive=1")
    blobs = [t["path"] for t in tree["tree"] if t["type"] == "blob"]
    print(f"remote blobs: {len(blobs)}")
    hits = []
    for path in blobs:
        meta = get(f"repos/{REPO}/contents/{path}")
        text = base64.b64decode(meta.get("content", "")).decode("utf-8", "replace")
        for name, rx in SWEEP.items():
            for m in rx.finditer(text):
                val = m.group(0)
                ctx = text[max(0, m.start() - 40):m.end() + 8]
                if name == "email" and val.lower().endswith(SAFE_EMAIL_DOMAINS):
                    continue
                # already-redacted values keep a vendor prefix + …REDACTED marker
                if name in ("vendor", "hex_long", "kv_secret") and ("…" in ctx or "REDACTED" in ctx):
                    continue
                # vendor prefix followed by regex syntax is a pattern definition,
                # not a key: tvly-[A-Za-z0-9-]{10,} in the scanner's own source
                if name == "vendor" and m.end() < len(text) and text[m.end()] in "[{(":
                    continue
                # f-string templates and doc placeholders are not credentials
                if name == "url_userinfo" and ("{" in val or "user:pass@" in val):
                    continue
                hits.append((path, name, val[:40]))
    for h in hits:
        print("HIT", h)
    print(f"\nSWEEP: {len(hits)} hits across {len(blobs)} remote files")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
