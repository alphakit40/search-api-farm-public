"""Shared regger base: email pool, IMAP verify, yescaptcha turnstile, patchright browser.

Contract:
- pick_email(svc): picks fresh t-online email not in tmp/reggers/<svc>_used.txt
- wait_verify(email, pw, keywords, link_keywords, timeout): returns (link|None, code|None)
- solve_turnstile(sitekey, url): returns token via yescaptcha
- launch(): returns (browser, context, page) patchright chromium non-headless
- save_result(svc, rec): appends to tmp/reggers/<svc>_result.json + marks email used
"""
import json, os, random, re, ssl, string, sys, time, imaplib, email as email_lib
from pathlib import Path
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))  # secrets_env.py sits at the repo root
from secrets_env import imap_pool, req  # noqa: E402

HERE = Path(__file__).resolve().parent
POOL = imap_pool()
IMAP_HOST = "imap.t-online.de"
IMAP_PORT = 993
YC_KEY = req("YESCAPTCHA_KEY")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def rnd_pass(prefix=""):
    return prefix + "".join(random.choices(string.ascii_letters + string.digits, k=12)) + "!7zQ"


def pick_email(svc):
    used = set()
    uf = HERE / f"{svc}_used.txt"
    if uf.exists():
        used = set(uf.read_text(encoding="utf-8", errors="ignore").splitlines())
    cands = []
    for line in POOL.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        e, p = line.split(":", 1)
        e, p = e.strip(), p.strip()
        if e and p and e not in used:
            cands.append((e, p))
    random.shuffle(cands)
    if not cands:
        raise RuntimeError(f"пул исчерпан для {svc}")
    return cands[0]


def mark_used(svc, email):
    uf = HERE / f"{svc}_used.txt"
    cur = set(uf.read_text(encoding="utf-8", errors="ignore").splitlines()) if uf.exists() else set()
    cur.add(email)
    uf.write_text("\n".join(sorted(cur)), encoding="utf-8")


def save_result(svc, rec):
    rf = HERE / f"{svc}_result.json"
    accs = json.loads(rf.read_text(encoding="utf-8")) if rf.exists() else []
    accs.append(rec)
    rf.write_text(json.dumps(accs, indent=2, ensure_ascii=False), encoding="utf-8")
    mark_used(svc, rec["email"])
    print(f"  [saved] {rf.name} total={len(accs)}", flush=True)


def wait_verify(addr, pw, keywords, link_keywords, timeout=180, code_regex=None):
    """Poll IMAP latest mails; return (link|None, code|None)."""
    start = time.time()
    seen = set()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    while time.time() - start < timeout:
        try:
            imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ctx, timeout=30)
            imap.login(addr, pw)
            imap.select("INBOX")
            _, ids = imap.search(None, "ALL")
            ids = ids[0].split()[-10:] if ids[0] else []
            for mid in reversed(ids):
                if mid in seen:
                    continue
                seen.add(mid)
                _, data = imap.fetch(mid, "(RFC822)")
                if not data or not data[0] or not isinstance(data[0], tuple):
                    continue
                raw = data[0][1]
                if not isinstance(raw, bytes):
                    continue
                msg = email_lib.message_from_bytes(raw)
                body = ""
                html = ""
                for part in msg.walk() if msg.is_multipart() else [msg]:
                    ct = (part.get_content_type() or "").lower()
                    payload = part.get_payload(decode=True)
                    if ct == "text/plain" and payload and not body:
                        body = payload.decode(errors="ignore")
                    elif ct == "text/html" and payload:
                        html += (payload.decode(errors="ignore") or "")
                if not body and not html:
                    payload = msg.get_payload(decode=True)
                    body = payload.decode(errors="ignore") if payload else ""
                subj = msg.get("Subject") or ""
                if not isinstance(subj, str):
                    subj = str(subj)
                frm = msg.get("From") or ""
                if not isinstance(frm, str):
                    frm = str(frm)
                text = (subj + " " + body).lower()
                if not any(kw.lower() in text for kw in keywords):
                    continue
                links = re.findall(r'https?://[^\s<>"\']+', body)
                links += re.findall(r'href="(https?://[^"]+)"', html)
                for link in links:
                    if any(x in link for x in link_keywords):
                        imap.logout()
                        print(f"  [imap] link from {frm[:40]}", flush=True)
                        return link, None
                if code_regex:
                    codes = re.findall(code_regex, body + " " + html)
                    if codes:
                        imap.logout()
                        print(f"  [imap] code {codes[0][:12]} from {frm[:40]}", flush=True)
                        return None, codes[0]
            imap.logout()
        except Exception as e:
            print(f"  [imap] {type(e).__name__}: {str(e)[:80]}", flush=True)
        time.sleep(6)
    return None, None


def cap_post(host, method, payload):
    payload = dict(payload, clientKey=YC_KEY)
    req = __import__("urllib.request").request.Request(
        f"https://api.{host}/{method}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with __import__("urllib.request").request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode())


def solve_turnstile(sitekey, page_url, host="yescaptcha.com"):
    c = cap_post(host, "createTask",
                 {"task": {"type": "TurnstileTaskProxyless", "websiteURL": page_url, "websiteKey": sitekey}})
    if c.get("errorId"):
        raise RuntimeError(f"captcha create: {c}")
    tid = c["taskId"]
    for i in range(40):
        time.sleep(4)
        g = cap_post(host, "getTaskResult", {"taskId": tid})
        if g.get("status") == "ready":
            tok = g["solution"]["token"]
            print(f"  [captcha] solved len={len(tok)} ({i*4}s)", flush=True)
            return tok
        if g.get("errorId"):
            raise RuntimeError(f"captcha poll: {g}")
    raise TimeoutError("captcha timeout")


def solve_recaptcha(sitekey, page_url, version="v2", action=None, host="yescaptcha.com"):
    """Google reCAPTCHA v2 checkbox / v3 via YesCaptcha. Returns token."""
    ttype = "RecaptchaV2TaskProxyless" if version == "v2" else "RecaptchaV3TaskProxyless"
    task = {"type": ttype, "websiteURL": page_url, "websiteKey": sitekey}
    if version == "v3" and action:
        task["pageAction"] = action
    c = cap_post(host, "createTask", {"task": task})
    if c.get("errorId"):
        raise RuntimeError(f"recaptcha create: {c}")
    tid = c["taskId"]
    for i in range(50):
        time.sleep(4)
        g = cap_post(host, "getTaskResult", {"taskId": tid})
        if g.get("status") == "ready":
            tok = g["solution"].get("gRecaptchaResponse") or g["solution"].get("token")
            print(f"  [recaptcha] solved len={len(tok)} ({i*4}s)", flush=True)
            return tok
        if g.get("errorId"):
            raise RuntimeError(f"recaptcha poll: {g}")
    raise TimeoutError("recaptcha timeout")


def solve_hcaptcha(sitekey, page_url, host="yescaptcha.com"):
    """hCaptcha via YesCaptcha (HCaptchaTaskProxyless). Returns token."""
    c = cap_post(host, "createTask",
                 {"task": {"type": "HCaptchaTaskProxyless", "websiteURL": page_url, "websiteKey": sitekey}})
    if c.get("errorId"):
        raise RuntimeError(f"hcaptcha create: {c}")
    tid = c["taskId"]
    for i in range(40):
        time.sleep(4)
        g = cap_post(host, "getTaskResult", {"taskId": tid})
        if g.get("status") == "ready":
            tok = g["solution"].get("token") or g["solution"].get("gRecaptchaResponse")
            print(f"  [hcaptcha] solved len={len(tok)} ({i*4}s)", flush=True)
            return tok
        if g.get("errorId"):
            raise RuntimeError(f"hcaptcha poll: {g}")
    raise TimeoutError("hcaptcha timeout")


def inject_hcaptcha_token(page, token):
    """Set hCaptcha response in the form field; returns awaitable."""
    return page.evaluate(
        """([t]) => {
            const ta = document.querySelector('[name="h-captcha-response"], textarea[name="h-captcha-response"]');
            if (ta) {
                const proto = ta.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                Object.getOwnPropertyDescriptor(proto, 'value').set.call(ta, t);
                ta.dispatchEvent(new Event('input', {bubbles: true}));
                ta.dispatchEvent(new Event('change', {bubbles: true}));
            }
            return !!ta;
        }""", [token])


def find_sitekey(page, recaptcha=True, turnstile=True):
    """Return (kind, sitekey) from page, or (None, None)."""
    res = page.evaluate(
        """() => {
            const out = [];
            // recaptcha: explicit widget or hidden response textarea (sitekey in iframe src)
            const rc = document.querySelector('.g-recaptcha[data-sitekey], iframe[src*="recaptcha"]');
            if (rc) {
                const sk = rc.getAttribute('data-sitekey')
                    || (rc.tagName === 'IFRAME' ? (rc.src.match(/[?&]k=([^&]+)/) || [])[1] : '');
                if (sk) out.push('recaptcha|' + sk);
            }
            const gresp = document.querySelector('#g-recaptcha-response');
            if (gresp && gresp.closest('form,[class*="captcha"]')) out.push('recaptcha|form');
            // turnstile: only inside cf-turnstile containing block
            const ts = document.querySelector('.cf-turnstile [data-sitekey], div[class*="turnstile"] [data-sitekey]');
            if (ts) out.push('turnstile|' + ts.getAttribute('data-sitekey'));
            // hcaptcha
            const hc = document.querySelector('.h-captcha[data-sitekey], [data-sitekey].h-captcha');
            if (hc) out.push('hcaptcha|' + hc.getAttribute('data-sitekey'));
            const hc2 = document.querySelector('.h-captcha');
            if (hc2 && !hc) out.push('hcaptcha|' + (hc2.getAttribute('data-sitekey') || ''));
            return out.join(';');
        }""")
    if not res:
        return None, None
    for item in res.split(";"):
        if "|" in item:
            kind, sk = item.split("|", 1)
            if sk and kind != "recaptcha-form":
                return kind, sk
    return None, None


def inject_recaptcha_token(page, token):
    return page.evaluate(
        """([t]) => {
            const ta = document.querySelector('#g-recaptcha-response');
            if (ta) {
                const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
                setter.call(ta, t);
                ta.dispatchEvent(new Event('input', {bubbles: true}));
                ta.dispatchEvent(new Event('change', {bubbles: true}));
            }
        }""", [token])


def inject_token(page, token):
    return page.evaluate(
        """([t]) => {
            const el = document.querySelector('textarea[name="cf-turnstile-response"], input[name="cf-turnstile-response"]');
            if (el) {
                const setter = Object.getOwnPropertyDescriptor(el.__proto__, 'value')?.set;
                if (setter) setter.call(el, t);
                else el.value = t;
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
            }
            const ifr = document.querySelector('iframe[src*="challenges.cloudflare.com"]');
            if (ifr) { try { ifr.contentWindow.postMessage(t, '*'); } catch (e) {} }
        }""", [token])


async def launch(**kw):
    from patchright.async_api import async_playwright
    from urllib.parse import urlparse
    p = await async_playwright().start()
    proxy = None
    if kw.get("proxy"):
        u = urlparse(kw["proxy"])
        proxy = {"server": f"{u.scheme}://{u.hostname}:{u.port}"}
        if u.username:
            proxy["username"] = u.username
            proxy["password"] = u.password or ""
        print("  [proxy]", u.hostname, u.port, flush=True)
    browser = await p.chromium.launch(
        headless=bool(kw.get("headless", False)),
        args=["--disable-blink-features=AutomationControlled", "--window-size=1280,900",
              "--ignore-certificate-errors"] + list(kw.get("args", [])),
        proxy=proxy)
    ctx = await browser.new_context(
        user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"),
        viewport={"width": 1280, "height": 900}, locale="en-US",
        ignore_https_errors=True)
    page = await ctx.new_page()
    return p, browser, ctx, page