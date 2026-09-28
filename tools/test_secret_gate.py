"""Negative control for the secret gate.

Plants REAL keys (read from your local secrets.env) into a copy of
secrets.env.example and proves tools/scan_secrets.py fails the build.

Why this exists: a scanner that only ever passes is worse than no scanner.
If this test stops failing, the gate is broken and the repo is unsafe to publish.

Usage: python -u tools/test_secret_gate.py
Exit:  0 = gate works (leak detected).  1 = GATE BROKEN.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from secrets_env import req  # noqa: E402

SCANNER = ROOT / "tools" / "scan_secrets.py"
EXAMPLE = ROOT / "secrets.env.example"
WORK = ROOT / "_negctl"
REPORT = ROOT / "_negctl_report.json"

# planted deliberately: if the gate misses any of these shapes it is too narrow
PLANT = ("TAVILY_KEY", "FIRECRAWL_KEY", "JINA_KEY")


def main() -> int:
    if not EXAMPLE.exists():
        print(f"MISSING {EXAMPLE}")
        return 1
    WORK.mkdir(exist_ok=True)
    leak = WORK / "leak.env.example"
    shutil.copy(EXAMPLE, leak)

    planted = []
    with leak.open("a", encoding="utf-8") as f:
        for var in PLANT:
            val = req(var)
            f.write(var + "=" + val + "\n")
            planted.append(f"{var}(len {len(val)})")
    print("planted real secrets:", ", ".join(planted))

    env = dict(os.environ, SECRETS_ENV_DIR=str(ROOT), SECRETS_REPORT=str(REPORT))
    r = subprocess.run([sys.executable, "-u", str(SCANNER), str(WORK)],
                       env=env, capture_output=True, text=True, timeout=180)

    summary = next((ln for ln in r.stdout.splitlines() if ln.startswith("scanned")), "(none)")
    kinds = sorted({ln.split()[2] for ln in r.stdout.splitlines()
                    if ln.strip().startswith("L ") and len(ln.split()) > 2})
    print("scanner exit:", r.returncode)
    print("summary:", summary)
    print("kinds flagged:", ", ".join(kinds) or "(none)")

    shutil.rmtree(WORK, ignore_errors=True)
    REPORT.unlink(missing_ok=True)

    ok = r.returncode == 1 and len(kinds) >= 2
    print("\nRESULT:", "GATE WORKS — real keys in .example are caught" if ok
          else "GATE BROKEN — leak NOT detected")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
