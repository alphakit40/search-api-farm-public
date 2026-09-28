"""Delete the public repo (history purge) and republish the sanitized tree.

History holds the AntiCaptcha fragments, t-online emails and the author email
in ~100 commits — sanitizing HEAD alone leaves them fetchable. Delete+recreate
is the only real purge. Then gh_publish re-creates and re-pushes with noreply
committer identity, and the remote read-back gate re-verifies.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from gh_publish import api  # noqa: E402
from secrets_env import req  # noqa: E402


def main() -> int:
    repo = req("GH_REPO")
    if "--purge" in sys.argv:
        status, body = api("DELETE", f"repos/{repo}")
        print(f"DELETE {repo}: HTTP {status} {body[:120]}")
        if status not in (204, 404):
            print("DELETE failed — needs delete_repo scope on the PAT. Aborting.")
            return 1
        print("purged. Recreating via publisher...")
    r = subprocess.run([sys.executable, "-u", str(ROOT / "tools" / "gh_publish.py")],
                       capture_output=True, text=True, timeout=1200)
    tail = [ln for ln in r.stdout.splitlines()
            if ln.startswith(("==", "  local gate", "  remote gate", "PUBLISHED",
                              "REFUSED", "FAILED", "  repo", "  created")) or "FAIL" in ln]
    print("\n".join(tail))
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
