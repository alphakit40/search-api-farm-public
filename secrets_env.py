"""Single source of truth for secrets: environment variables / secrets.env.

Nothing in this repo hardcodes a credential. Copy `secrets.env.example` to
`secrets.env` (gitignored) or export the vars in your shell.

Usage from reggers/ or tools/:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from secrets_env import req, opt, key_list, brd_cdp
"""
import os
import sys
from pathlib import Path

_ENV_FILE = Path(os.environ.get("SEARCHFARM_ENV")
                 or Path(__file__).resolve().parent / "secrets.env")


def _load_env_file():
    """Parse the env file into os.environ; already-exported variables win."""
    if not _ENV_FILE.exists():
        return
    for line in _ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env_file()


def req(name: str) -> str:
    """Required secret. Exits with a clear message instead of a KeyError."""
    v = os.environ.get(name)
    if not v:
        sys.exit(f"[secrets] missing required env var: {name} "
                 f"(copy secrets.env.example -> secrets.env and fill it in)")
    return v


def opt(name: str, default=None):
    """Optional secret with fallback."""
    return os.environ.get(name) or default


def key_list(name: str) -> list:
    """Comma-separated secret list (e.g. EXA_KEYS)."""
    return [k.strip() for k in (opt(name, "") or "").split(",") if k.strip()]


def imap_pool() -> Path:
    """Path to the email:password pool file used by reg_base.pick_email."""
    p = Path(opt("IMAP_POOL") or "C:/Users/User/tmp/notion-gateway/imap.txt")
    if not p.exists():
        sys.exit(f"[secrets] IMAP_POOL not found: {p} (set IMAP_POOL in secrets.env)")
    return p


def brd_zones() -> dict:
    """{'mcp_browser': pw, ...} assembled from BRD_ZONE_<NAME> env vars."""
    out = {}
    for k, v in os.environ.items():
        if k.startswith("BRD_ZONE_") and v:
            out[k[len("BRD_ZONE_"):].lower()] = v
    return out


def brd_cdp(zone: str = "mcp_browser") -> str:
    """BrightData Scraping Browser CDP endpoint for `zone`."""
    cid = req("BRD_CUSTOMER")
    zones = brd_zones()
    if zone not in zones:
        sys.exit(f"[secrets] missing BRD_ZONE_{zone.upper()} "
                 f"(have: {', '.join(sorted(zones)) or 'none'})")
    return f"wss://brd-customer-{cid}-zone-{zone}:{zones[zone]}@brd.superproxy.io:9222"


def redact(value: str, head: int = 6) -> str:
    """Display-safe form of a secret: keep a short prefix for identification."""
    if not value:
        return ""
    if len(value) <= head:
        return value
    return value[:head] + "…REDACTED"


if __name__ == "__main__":
    # self-check: contract must resolve or fail loudly, never silently
    assert redact("abcdefghij") == "abcdef…REDACTED", redact("abcdefghij")
    assert redact("abc") == "abc", redact("abc")
    # fixture deliberately avoids the real BrightData customer-id shape so the
    # secret scanner does not flag this source file as a leak
    os.environ.setdefault("BRD_CUSTOMER", "selftestcid")
    os.environ.setdefault("BRD_ZONE_MCP_BROWSER", "pw_selftest")
    assert brd_cdp("mcp_browser").startswith("wss://brd-customer-"), brd_cdp()
    assert "mcp_browser" in brd_zones(), brd_zones()
    os.environ["_SELFTEST_KEYS"] = "aaa, bbb ,,ccc"
    assert key_list("_SELFTEST_KEYS") == ["aaa", "bbb", "ccc"], key_list("_SELFTEST_KEYS")
    assert opt("NOT_SET_XYZ", "fallback") == "fallback"
    print("secrets_env self-check OK | env file:", _ENV_FILE,
          "| loaded BRD zones:", ", ".join(sorted(brd_zones())))
