"""Adversarial critic: a model from a DIFFERENT family attacks the top-N
load-bearing/controversial facts of the report. Writes verify/critic.json.
Falls back to 'skipped' if the gateway is down — never fake the critique
with the same model that wrote the report.

Usage: python -u adversarial_critic.py [facts.json]
  facts.json: ["fact 1", "fact 2", ...] (default: verify/facts.json)
Env:
  GATEWAY_URL   OpenAI-compatible base or full chat endpoint
                (default: http://127.0.0.1:16432)
  CRITIC_MODEL  comma-separated model fallbacks
                (default: deepseek-v4-flash-0731,deepseek-chat,deepseek-v3)
"""
import json
import os
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(os.environ.get("RESEARCH_ROOT", pathlib.Path(__file__).resolve().parent))

GATEWAY = os.environ.get("GATEWAY_URL", "http://127.0.0.1:16432").rstrip("/")
MODELS = [m.strip() for m in os.environ.get(
    "CRITIC_MODEL", "deepseek-v4-flash-0731,deepseek-chat,deepseek-v3").split(",") if m.strip()]

PROMPT_TMPL = """Ты — adversarial-редактор. Атакуй каждый факт ниже. Для каждого:
1) вердикт: PLAUSIBLE / SUSPICIOUS / REJECT
2) самое слабое место (что именно может быть неправдой: воронка, арифметика, устаревание, cherry-pick, нерепрезентативность)
3) что бы ты проверил дополнительно одним запросом
Пиши по-русски, коротко, без воды. Формат JSON-массива: [{{"fact": i, "verdict": "...", "weakness": "...", "check": "..."}}]

Факты:
{facts}"""


def call_gateway(facts):
    prompt = PROMPT_TMPL.format(facts="\n".join(f"{i+1}. {f}" for i, f in enumerate(facts)))
    bases = [GATEWAY, GATEWAY + "/v1"] if not GATEWAY.endswith("/v1") else [GATEWAY]
    last = None
    for base in bases:
        for model in MODELS:
            try:
                payload = {"model": model,
                           "messages": [{"role": "user", "content": prompt}],
                           "temperature": 0.2, "max_tokens": 8000}
                req = urllib.request.Request(
                    f"{base}/chat/completions",
                    data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=180) as r:
                    j = json.loads(r.read().decode("utf-8", "replace"))
                    msg = j["choices"][0]["message"]
                    # reasoning models may spend the whole budget on reasoning_content
                    txt = msg.get("content") or msg.get("reasoning_content") or ""
                    if not txt.strip():
                        last = f"{base} {model}: empty completion (reasoning budget?)"
                        continue
                    return {"model": model, "base": base, "text": txt}
            except Exception as e:
                last = f"{base} {model}: {type(e).__name__} {str(e)[:80]}"
                continue
    return {"error": last or "no gateway"}


def main():
    facts_path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "verify" / "facts.json"
    if not facts_path.exists():
        print(f"facts file not found: {facts_path}\n"
              f"Create it (JSON array of strings) or copy facts.example.json.")
        sys.exit(2)
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    res = call_gateway(facts)
    (ROOT / "verify").mkdir(exist_ok=True)
    (ROOT / "verify" / "critic.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    if "error" in res:
        print("ADVERSARIAL SKIPPED:", res["error"])
    else:
        print(f"model={res['model']} via {res['base']}")
        print(res["text"][:3000])


if __name__ == "__main__":
    main()
