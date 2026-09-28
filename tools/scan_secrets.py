"""Scan searchfarm tree for secrets. Output: secrets_report.json (file -> [hits])."""
import json, os, re, sys
from pathlib import Path

ROOTS = [Path(a) for a in sys.argv[1:]] if len(sys.argv) > 1 else [
    Path("C:/Users/User/tmp/searchfarm"),
    Path("C:/Users/User/tmp/reggers"),
]
SKIP_DIRS = {".git", "__pycache__", "node_modules"}
SKIP_FILES = {"secrets_report.json", "secrets.env", "scan_secrets.py"}
# ".example" included on purpose: a real key pasted into secrets.env.example must fail the gate
SCAN_SUFFIXES = {".py", ".md", ".json", ".html", ".txt", ".yml", ".yaml", ".env", ".example",
                 ".cfg", ".ini", ".toml", ".sh", ".ps1"}

PATTERNS = {
    "github_pat":      r"ghp_[A-Za-z0-9]{20,}",
    "github_fgp":      r"github_pat_[A-Za-z0-9_]{20,}",
    "uuid_key":        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    "tavily_key":      r"tvly-[A-Za-z0-9-]{10,}",
    "firecrawl_key":   r"fc-[0-9a-f]{16,}",
    "jina_key":        r"jina_[A-Za-z0-9_]{16,}",
    "youcom_key":      r"ydc-sk-[A-Za-z0-9-]{10,}",
    "openai_style":    r"\bsk-[A-Za-z0-9_-]{20,}",
    "hex64":           r"\b[0-9a-f]{64}\b",
    "hex32":           r"\b[0-9a-f]{32}\b",
    "brd_customer":    r"hl_[0-9a-z]{6,}",
    "brd_zone_pw":     r"\bZZ_REPLACED_FROM_ENV_BELOW_ZZ\b",
    "brd_email":       r"baradok227@gmail\.com",
    "imap_cred":       r"[A-Za-z0-9._%+-]+@t-online\.de:[^\s\"']+",
    "pass_assign":     r"(?i)(password|passwd|pwd|secret|api_?key|token)\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']",
    "bearer":          r"(?i)bearer\s+[A-Za-z0-9._-]{20,}",
    "x_api_key":       r"(?i)x-api-key[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9._-]{16,}",
    # Excluded from the character classes: braces (an f-string template is not a
    # credential), \r\n (a multi-line match eats real text), and quotes/whitespace
    # (a URL userinfo never contains them — without this the pattern matches across
    # string concatenation like "wss://" + user + ":" + pw + "@host").
    "wss_creds":       r"wss://[^:{}\s\"']+:[^@{}\s\"']+@",
    "tg_bot_token":    r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b",
    # PII: any real email in a public artifact. Placeholder/noreply domains exempt.
    "email_leak":      r"[A-Za-z0-9._%+-]+@(?!(?:example\.(?:com|org|invalid)|users\.noreply\.github\.com)\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    # Bare "key" JSON field holding hex material (AntiCaptcha fragments slipped
    # through pass_assign which required password|api_key|token field names).
    # Group 2 = the value only, so the redactor keeps the key name intact.
    "json_hex_key":    r"(?i)(\"(?:api_?key|key|secret|token)\"\s*:\s*\")([0-9a-f]{16,})(?=\")",
    # Key-ish JSON field with high-entropy value (any charset, not just hex).
    # Requires lower+digit+(upper|_) so labels like "rotator-local-pool" pass.
    "json_kv_secret":  r"(?i)(\"(?:api_?key|key|secret|token|password)\"\s*:\s*\")((?=[\w./+-]*[a-z])(?=[\w./+-]*\d)(?=[\w./+-]*[A-Z_])[\w./+-]{20,})(?=\")",
}


def _zone_pw_pattern() -> str:
    """BRD zone passwords are read from env at runtime, so the scanner stores none."""
    here = Path(__file__).resolve().parent
    extra = os.environ.get("SECRETS_ENV_DIR")
    cands = ([Path(extra)] if extra else []) + [here, here.parent, here.parent / "searchfarm_public"]
    for cand in cands:
        if cand.is_dir() and str(cand) not in sys.path:
            sys.path.insert(0, str(cand))
    try:
        from secrets_env import brd_zones
        vals = sorted({v for v in brd_zones().values() if v})
    except Exception as exc:
        # never swallow silently: an inactive zone check is a weaker gate
        print(f"[scan_secrets] WARNING: secrets_env unavailable ({exc!r}) "
              f"— BRD zone-password check INACTIVE. Set SECRETS_ENV_DIR.", file=sys.stderr)
        vals = []
    if not vals:
        return r"\bZZ_NO_BRD_ZONES_IN_ENV_ZZ\b"
    return r"\b(" + "|".join(re.escape(v) for v in vals) + r")\b"


PATTERNS["brd_zone_pw"] = _zone_pw_pattern()
COMPILED = {k: re.compile(v) for k, v in PATTERNS.items()}

# values that look like secrets but are safe to keep
ALLOWLIST = {
    "0x4AAAAAADSpJWQOnICEKAwx",   # public Turnstile sitekey
}

REGEX_META = set("[](){}*+?|^$\\")


def _is_regex_source(val: str) -> bool:
    """pass_assign also fires on regex SOURCE, e.g. `token:"([0-9a-f]+)"`.

    A real credential never contains regex metacharacters, so those are skipped.
    Without this the gate cries wolf on pattern definitions and loses trust.
    """
    return any(c in REGEX_META for c in val)


def scan_file(p: Path):
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for name, rx in COMPILED.items():
            for m in rx.finditer(line):
                val = m.group(0)
                if val in ALLOWLIST:
                    continue
                if name == "pass_assign" and _is_regex_source(val):
                    continue
                hits.append({
                    "line": lineno,
                    "kind": name,
                    "match": val[:8] + "…" + val[-4:] if len(val) > 16 else val,
                    "full_len": len(val),
                    "snippet": line.strip()[:160],
                })
    return hits


def main():
    report = {}
    files_scanned = 0
    for root in ROOTS:
        if root.is_file():
            candidates = [root]
        elif root.is_dir():
            candidates = sorted(p for p in root.rglob("*") if p.is_file())
        else:
            print(f"[scan_secrets] skip missing root: {root}", file=sys.stderr)
            continue
        for p in candidates:
            if p.name in SKIP_FILES:
                continue
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            if p.suffix not in SCAN_SUFFIXES:
                continue
            files_scanned += 1
            hits = scan_file(p)
            if hits:
                report[str(p)] = hits

    base = ROOTS[0] if ROOTS[0].is_dir() else ROOTS[0].parent
    out = Path(os.environ.get("SECRETS_REPORT") or (base / "secrets_report.json"))
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    total = sum(len(v) for v in report.values())
    print(f"scanned {files_scanned} files | {len(report)} files with hits | {total} secret hits")
    for f, hits in report.items():
        kinds = sorted({h["kind"] for h in hits})
        print(f"\n{f}  ({len(hits)} hits: {', '.join(kinds)})")
        seen = set()
        for h in hits:
            key = (h["kind"], h["match"])
            if key in seen:
                continue
            seen.add(key)
            print(f"   L{h['line']:>4} {h['kind']:<14} {h['match']}")
            print(f"        {h['snippet'][:140]}")
    print(f"\nreport -> {out}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
