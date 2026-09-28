"""Redact every credential from a JSON / HTML / Markdown file.

One source of truth for secret shapes: PATTERNS from tools/scan_secrets.py.
Idempotent — re-running on already-redacted output changes nothing.

Usage:
    python -u tools/redact_json.py --selftest
    python -u tools/redact_json.py <input> <output> [<input> <output> ...]
"""
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from secrets_env import redact  # noqa: E402
import scan_secrets as sc  # noqa: E402

MARKER = "…REDACTED"

# hex32/hex64 are ambiguous: a bare one is a key, but the same run inside a
# filename (Rails-style `application-<digest>.js`) is a public asset hash.
AMBIGUOUS = {"hex32", "hex64"}
# The scanner's pass_assign (8+ chars, no regex guard) is replaced below by
# PASS_ASSIGN, which skips regex SOURCE like `set_token:"([0-9a-f]+)"`.
REPLACED = "pass_assign"

TOKEN_CHARS = set("-_./0123456789"
                  "abcdefghijklmnopqrstuvwxyz"
                  "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
PASS_ASSIGN = re.compile(
    r"(?i)\b(?:password|passwd|pwd|secret|api_?key|token|key)\s*[:=]\s*[\"']([^\"'\s]{16,})[\"']")


def _is_regex_source(val: str) -> bool:
    """A credential never contains regex metacharacters; a pattern usually does."""
    return any(c in val for c in "[](){}*+?|^$\\")


def _embedded(text: str, start: int, end: int) -> bool:
    """True when the match is part of a longer token (asset hash in a path/URL)."""
    before = text[start - 1] if start else ""
    after = text[end] if end < len(text) else ""
    return before in TOKEN_CHARS or after in TOKEN_CHARS


class _GroupMatch:
    """Match shim: group(0)/start()/end() refer to a capture-group span."""

    __slots__ = ("_m", "_s", "_e")

    def __init__(self, m, s, e):
        self._m, self._s, self._e = m, s, e

    def group(self, _i=0):
        return self._m.string[self._s:self._e]

    def start(self):
        return self._s

    def end(self):
        return self._e


def _spans(text: str) -> list:
    """Collect (start, end, secret) spans to redact.

    Patterns with capture groups (json_hex_key) mark the VALUE in the last
    group; redacting the full match would destroy the surrounding JSON key.
    """
    found = []
    for name, rx in sc.COMPILED.items():
        if name == REPLACED:
            continue
        ambiguous = name in AMBIGUOUS
        for m in rx.finditer(text):
            if m.lastindex:
                gs, ge = m.span(m.lastindex)
                m = _GroupMatch(m, gs, ge)
            val = m.group(0)
            # Invariant: a credential never spans lines. A multi-line match means a
            # pattern's character class forgot \n and is eating real text — this
            # once swallowed a whole README section between `wss://` and an `@`.
            if "\n" in val or "\r" in val:
                continue
            if val in sc.ALLOWLIST:
                continue
            if ambiguous and _embedded(text, m.start(), m.end()):
                continue
            found.append((m.start(), m.end(), val))
    for m in PASS_ASSIGN.finditer(text):
        literal = m.group(1)
        if _is_regex_source(literal):
            continue
        found.append((m.start(1), m.end(1), literal))
    return found


def redact_text(text: str) -> tuple:
    """Redact credentials inside arbitrary text. Returns (new_text, n_changes)."""
    spans = _spans(text)
    if not spans:
        return text, 0

    # merge overlaps, keeping the longest span at each start position
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    merged = []
    for s in spans:
        if merged and s[0] < merged[-1][1]:
            if (s[1] - s[0]) > (merged[-1][1] - merged[-1][0]):
                merged[-1] = s
            continue
        merged.append(s)

    out, last, n = [], 0, 0
    for start, end, val in merged:
        out.append(text[last:start])
        out.append(redact(val))
        last = end
        n += 1
    out.append(text[last:])
    return "".join(out), n


CRED_FIELD = re.compile(r"(?i)^(?:password|passwd|pwd|secret|api_?key|token|key|pass)$")
SECRETISH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{11,}$")


def redact_value(node: Any) -> tuple:
    """Recursively redact credential strings in a parsed JSON structure.

    Beyond pattern matching on values, a dict field NAMED like a credential
    (password/secret/api_key/token/key/...) has its string value redacted
    directly — a bare 20-char hex under "key" matches no global pattern.
    """
    changes = 0
    if isinstance(node, dict):
        for k, v in node.items():
            if (isinstance(v, str) and CRED_FIELD.match(str(k))
                    and SECRETISH.match(v) and not v.endswith(MARKER)):
                node[k] = redact(v)
                changes += 1
                continue
            node[k], n = redact_value(v)
            changes += n
        return node, changes
    if isinstance(node, list):
        for i, v in enumerate(node):
            node[i], n = redact_value(v)
            changes += n
        return node, changes
    if isinstance(node, str):
        if node.endswith(MARKER):
            return node, 0
        return redact_text(node)
    return node, 0


def process(src: Path, dst: Path) -> int:
    text = src.read_text(encoding="utf-8", errors="replace")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            new, n = redact_text(text)          # JSONL or malformed: text pass
            dst.write_text(new, encoding="utf-8")
            return n
        data, n = redact_value(data)
        dst.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return n
    new, n = redact_text(text)
    dst.write_text(new, encoding="utf-8")
    return n


def _selftest() -> int:
    import secrets_env as s

    exa = s.key_list("EXA_KEYS")[0]
    tav = s.req("TAVILY_KEY")
    # synthetic digests built at runtime so this source file holds no secret-shaped literal
    h32 = "deadbeef" * 4
    h64 = "0123456789abcdef" * 4

    cases = [
        ("exa uuid in json",   f'"key": "{exa}"',                    True),
        ("bearer + tavily",    f"Authorization: Bearer {tav}",       True),
        ("bare tavily key",    tav,                                  True),
        ("bare hex32 key",     f'"api_key": "{h32}"',                True),
        ("bare hex64 key",     f'"api_key": "{h64}"',                True),
        ("hex32 asset file",   f"assets/application-{h32}.js",       False),
        ("hex64 asset file",   f"assets/tailwind-{h64}.css",         False),
        ("public sitekey",     "sitekey 0x4AAAAAADSpJWQOnICEKAwx",   False),
        ("regex source",       're.search(r\'set_token:"([0-9a-f]+)"\')', False),
        ("already redacted",   redact(exa),                          False),
    ]

    fails = 0
    for label, text, should in cases:
        out, n = redact_text(text)
        # only a case that SHOULD be redacted can leak; preserved hashes are expected
        leaked = should and (exa in out or tav in out or h32 in out or h64 in out)
        if (n > 0) != should or leaked:
            fails += 1
            print(f"  FAIL {label:20} redacted={n > 0} want={should} leaked={leaked}")
        else:
            print(f"  ok   {label:20} redacted={n > 0}")

    # JSON structure walk
    d1, n1 = redact_value(json.loads(json.dumps({"api_key": h32, "label": "searchapi"})))
    d2, n2 = redact_value(json.loads(json.dumps({"asset": f"x-{h32}.js", "n": 5})))
    if n1 != 1 or not str(d1.get("api_key", "")).endswith(MARKER):
        fails += 1
        print(f"  FAIL json bare hex32 (n={n1})")
    else:
        print(f"  ok   json bare hex32 -> {d1['api_key']} (label kept: {d1['label']})")
    if n2 != 0:
        fails += 1
        print(f"  FAIL json asset hash wrongly redacted (n={n2})")
    else:
        print("  ok   json asset hash preserved")

    # nested + idempotency
    nested, nn = redact_value({"a": [{"b": tav}, ["x", exa]], "c": 1})
    if nn != 2:
        fails += 1
        print(f"  FAIL nested walk changed {nn}, want 2")
    else:
        print("  ok   nested walk (dict/list) redacted 2")
    once, _ = redact_text(tav)
    twice, n = redact_text(once)
    if n != 0 or once != twice:
        fails += 1
        print(f"  FAIL not idempotent (2nd pass changed {n})")
    else:
        print("  ok   idempotent")

    # regression: a wss:// credential must not swallow everything up to a later "@".
    # The endpoint is assembled at runtime so this source holds no cred-shaped
    # literal for the scanner to flag (same trick as the synthetic hex digests).
    fake = "wss://" + "brd-customer-cid-zone-z1" + ":" + "secretpw" + "@brd.io:9222"
    doc = f"| BrightData | CDP `{fake}` |\n\n### Exa — magic link from hello [at] exa.ai\n"
    out, n = redact_text(doc)
    if "### Exa" not in out or "hello [at] exa.ai" not in out:
        fails += 1
        print("  FAIL multiline swallow: text between wss:// and a later @ was eaten")
    elif "secretpw" in out:
        fails += 1
        print("  FAIL wss password survived redaction")
    else:
        print(f"  ok   multiline span contained (redacted {n}, section text kept)")

    print("\nSELFTEST:", "PASS" if fails == 0 else f"FAIL ({fails})")
    return 1 if fails else 0


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] == "--selftest":
        return _selftest()
    if len(args) % 2:
        sys.exit("usage: redact_json.py <input> <output> [...pairs] | --selftest")
    total = 0
    for i in range(0, len(args), 2):
        src, dst = Path(args[i]), Path(args[i + 1])
        if not src.exists():
            print(f"  MISSING {src}")
            continue
        n = process(src, dst)
        total += n
        print(f"  {src.name} -> {dst}  ({n} redacted)")
    print(f"total redactions: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
