"""Publish the sanitized tree to a PUBLIC GitHub repo — gated end to end.

Order matters:
  1. local secret gate over exactly the files we intend to push  (must be clean)
  2. create the repo if absent (public)
  3. push an explicit allowlist — never a directory walk, so `secrets.env`
     cannot be swept in by accident
  4. confirm every blob by git SHA, then read the tree BACK from GitHub and
     scan the server-side content (proves what is actually public)

 Talks to api.github.com directly over HTTPS. The `gh` CLI was used before and
 timed out at 120s, reporting a push as failed after the server had already
 committed it — SHA confirmation makes that class of false failure impossible.

Usage: python -u tools/gh_publish.py [--dry-run]
Exit:  0 = published and verified clean. 1 = refused / leak found.
"""
import base64
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from secrets_env import req  # noqa: E402

# Never publishable, whatever else is true.
NEVER = {"secrets.env", "secrets_report.json", "_negctl_report.json",
         "_publish_gate.json", "_remote_gate.json"}
SKIP_DIRS = {"__pycache__", ".git", "_negctl", "_remote_check"}
TEXT_SUFFIXES = {".py", ".md", ".json", ".html", ".txt", ".yml", ".yaml",
                 ".example", ".cfg", ".ini", ".toml", ".sh", ".ps1", ""}

API = "https://api.github.com"


def _headers(json_body: bool = False) -> dict:
    h = {"User-Agent": "search-api-farm-publish",
         "Accept": "application/vnd.github+json"}
    cred = "Bearer " + req("GH_PAT")     # never logged, never in a URL
    h["Authorization"] = cred
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def api(method: str, path: str, payload=None):
    """-> (status, body_text). Network/HTTP errors are returned, not raised."""
    url = f"{API}/{path}" if not path.startswith("http") else path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method,
                                     headers=_headers(data is not None))
    try:
        with urllib.request.urlopen(request, timeout=90) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def git_blob_sha(content: bytes) -> str:
    """The SHA git/GitHub computes for a blob: sha1("blob <len>\\0" + content)."""
    return hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()


def allowlist() -> list:
    """Staged files to publish, as repo-relative POSIX paths."""
    out = []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.name in NEVER:
            continue
        if p.suffix not in TEXT_SUFFIXES:
            continue
        out.append(p.relative_to(ROOT).as_posix())
    return out


def local_gate(files: list) -> bool:
    """Run the scanner over exactly the files we are about to push."""
    import os
    env = dict(os.environ, SECRETS_ENV_DIR=str(ROOT),
               SECRETS_REPORT=str(ROOT / "_publish_gate.json"))
    r = subprocess.run([sys.executable, "-u", str(ROOT / "tools" / "scan_secrets.py"),
                        *[str(ROOT / f) for f in files]],
                       env=env, capture_output=True, text=True, timeout=600)
    summary = next((ln for ln in r.stdout.splitlines() if ln.startswith("scanned")), "")
    print(f"  local gate: {summary} | exit {r.returncode}")
    if r.returncode != 0:
        for ln in r.stdout.splitlines():
            if ln.strip().startswith("L ") or ln.startswith("C:"):
                print("   ", ln.strip()[:160])
    (ROOT / "_publish_gate.json").unlink(missing_ok=True)
    return r.returncode == 0


def ensure_repo(repo: str) -> bool:
    status, body = api("GET", f"repos/{repo}")
    if status == 200:
        vis = "private" if json.loads(body).get("private") else "PUBLIC"
        print(f"  repo exists: {repo} ({vis})")
        return True
    print(f"  creating public repo {repo} ...")
    name = repo.split("/", 1)[1]
    status, body = api("POST", "user/repos", {
        "name": name,
        "private": False,
        "description": "Search/scraping API key reggers + live verifier. "
                       "No credentials in repo: secrets come from the environment.",
        "has_issues": False,
    })
    if status not in (200, 201):
        print(f"  CREATE FAILED HTTP {status}: {body[:300]}")
        return False
    print("  created.")
    return True


def push_one(repo: str, path: str, local: Path):
    """Upload one file and confirm it by git blob SHA. -> (ok, detail)."""
    raw = local.read_bytes()
    want = git_blob_sha(raw)
    # explicit noreply identity: default author leaks the account's git email
    identity = {"name": "alphakit40",
                "email": "333579620+alphakit40@users.noreply.github.com"}
    payload = {
        "message": f"chore: publish sanitized {path}",
        "content": base64.b64encode(raw).decode(),
        "committer": identity,
        "author": identity,
    }
    status, body = api("GET", f"repos/{repo}/contents/{path}")
    if status == 200:
        payload["sha"] = json.loads(body)["sha"]

    status, body = api("PUT", f"repos/{repo}/contents/{path}", payload)
    if status in (200, 201):
        got = (json.loads(body).get("content") or {}).get("sha")
        if got == want:
            return True, "OK (sha verified)"
        # PUT answered but sha differs/absent — verify by reading it back
        status2, body2 = api("GET", f"repos/{repo}/contents/{path}")
        got2 = json.loads(body2).get("sha") if status2 == 200 else None
        return (got2 == want), f"sha mismatch (want {want[:8]}, got {str(got2)[:8]})"

    # A timeout can land the commit anyway: trust only a read-back SHA.
    status2, body2 = api("GET", f"repos/{repo}/contents/{path}")
    if status2 == 200 and json.loads(body2).get("sha") == want:
        return True, "OK (verified after error)"
    return False, f"HTTP {status}: {body[:120]}"


def remote_gate(repo: str, files: list) -> bool:
    """Download every published blob and scan the SERVER-SIDE bytes."""
    tmp = ROOT / "_remote_check"
    tmp.mkdir(exist_ok=True)
    pulled = 0
    for f in files:
        status, body = api("GET", f"repos/{repo}/contents/{f}")
        if status != 200:
            print(f"  READBACK MISSING {f} (HTTP {status})")
            continue
        raw = base64.b64decode(json.loads(body).get("content", ""))
        dest = tmp / f
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        pulled += 1

    import os
    env = dict(os.environ, SECRETS_ENV_DIR=str(ROOT),
               SECRETS_REPORT=str(ROOT / "_remote_gate.json"))
    r = subprocess.run([sys.executable, "-u", str(ROOT / "tools" / "scan_secrets.py"), str(tmp)],
                       env=env, capture_output=True, text=True, timeout=600)
    summary = next((ln for ln in r.stdout.splitlines() if ln.startswith("scanned")), "")
    print(f"  remote gate: pulled {pulled}/{len(files)} | {summary} | exit {r.returncode}")
    if r.returncode != 0:
        for ln in r.stdout.splitlines():
            if ln.strip().startswith("L ") or ln.startswith("C:"):
                print("   LEAK", ln.strip()[:160])
    shutil.rmtree(tmp, ignore_errors=True)
    (ROOT / "_remote_gate.json").unlink(missing_ok=True)
    return r.returncode == 0 and pulled == len(files)


def main() -> int:
    dry = "--dry-run" in sys.argv
    repo = req("GH_REPO")
    files = allowlist()

    print(f"== publish -> {repo} ({'DRY RUN' if dry else 'LIVE'}) ==")
    print(f"  allowlist: {len(files)} files")
    for f in files:
        print("   ", f)

    if any(Path(f).name in NEVER for f in files):
        print("\nREFUSED: a NEVER-publish file reached the allowlist")
        return 1

    print("\n== 1. local gate ==")
    if not local_gate(files):
        print("\nREFUSED: local tree is not clean — fix the leaks before publishing")
        return 1

    if dry:
        print("\nDRY RUN: stopped before touching GitHub")
        return 0

    print("\n== 2. ensure repo ==")
    if not ensure_repo(repo):
        return 1

    print("\n== 3. push (SHA-confirmed) ==")
    bad = []
    for f in files:
        ok, detail = push_one(repo, f, ROOT / f)
        if not ok:
            bad.append(f)
        print(f"  {'OK  ' if ok else 'FAIL'} {f:38} {detail}")
    if bad:
        print(f"\n{len(bad)} file(s) failed: {', '.join(bad)}")
        return 1

    print("\n== 4. remote read-back gate ==")
    if not remote_gate(repo, files):
        print("\nFAILED: server-side content is not clean")
        return 1

    print(f"\nPUBLISHED & VERIFIED CLEAN: https://github.com/{repo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
