<div align="center">

# 🔍 Search API Farm

**Авторегер-комбайн поисковых / scraping API — 34 live-ключа на 7 сервисах**

`Exa ×6` · `Search1API ×23` · `Tavily` · `SerpWrap` · `You.com` · `Firecrawl` · `Jina`

[📊 Dashboard](dashboard/index.html) · [📖 FULL_GUIDE](FULL_GUIDE.md) · [🧪 Live-verify](verify/verify_results.json)

**Канал автора: [AlStack](https://t.me/AlStack)** — автореги, AI-инфраструктура, боты

</div>

---

## ✅ Live-статус (2026-09-29, реальные API-вызовы `tools/verify_all.py`)

| Сервис | Статус | Ключей | Баланс | Тариф | Регер | Готовность |
|--------|:------:|:------:|--------|-------|-------|-----------|
| **Exa** | 🟢 | **6** | **$110** ($10 + 5×$20) | $0.007/поиск | `reggers/exa_brd_batch.py N` | batch, ~80%/прогон |
| **Tavily** | 🟢 | 1 | 1000 req/мес | free tier | `reggers/tavily_reg2.py` | одиночный |
| **SerpWrap** | 🟢 | 1 | 4250 credits (+250/нед) | — | `reggers/serpwrap_reg.py` | одиночный |
| **You.com** | 🟢 | 1 | $100 | — | `reggers/you_reg.py` | одиночный |
| **Firecrawl** | 🟢 | 1 | 1000 credits (reset 27.10) | — | `reggers/firecrawl_magic.py` | одиночный |
| **Search1API** | 🟢 | **23** | **2300 credits** (100/акк) | free tier | `reggers/s1_reg.py N` | batch, ~50%/прогон |
| **Jina** | 🟡 | 1 | $0 (trial IP-лимит) | — | — | ключ valid |

**Проверка:** `python -u tools/verify_all.py` → 10/11 OK (Jina 402 — баланс trial исчерпан, ключ валиден);
s1: `cd reggers && python -u s1_reg.py --verify` → **23/23 LIVE** (2026-09-29).
Плюс **харвест: 653 ключа** (370 LLM · 209 captcha · 51 search · 6 telegram · 16 misc) — `harvest/harvest_all.json`.

---

## 🚀 Быстрый старт

### 1. Setup — секреты живут вне git

```bash
cp secrets.env.example secrets.env    # затем заполнить значения
```

`secrets.env` в `.gitignore` и в репо не попадает. Все скрипты берут секреты через
`secrets_env.py` (`req` / `opt` / `key_list` / `brd_cdp` / `imap_pool`) —
захардкоженных ключей в коде нет вообще.

| Переменная | Зачем |
|---|---|
| `EXA_KEYS` | UUID Exa через запятую; их и проверяет `verify_all.py` |
| `TAVILY_KEY` `SERPWRAP_KEY` `YOU_KEY` `FIRECRAWL_KEY` `JINA_KEY` | по одному на сервис |
| `BRD_CUSTOMER` + `BRD_ZONE_*` | BrightData Scraping Browser; CDP-эндпоинт собирает `brd_cdp()` |
| `YESCAPTCHA_KEY` / `TWOCAPTCHA_KEY` | Turnstile там, где Scraping Browser не нужен |
| `IMAP_POOL` | путь к файлу `email:password` — пул ящиков под magic-link/OTP |
| `FIRECRAWL_EMAIL` | ящик, которым `firecrawl_magic.py` ДОРЕГИСТРИРУЕТ существующий аккаунт |
| `GH_PAT` `GH_REPO` | публикация отчётов в репо |

### 2. Проверить ключи реальными API-вызовами

```bash
python -u tools/verify_all.py     # отчёт -> verify/verify_results.json (ключи обрезаны)
```

Сервис без ключа в env = `SKIP`, а не падение. Exit 1 — если настроенный ключ мёртв.

### 3. Зарегистрировать новые (patchright venv, всегда `-u`)

```bash
PY="/path/to/patchright-venv/Scripts/python.exe"
$PY -u reggers/exa_brd_batch.py 5      # 5 аккаунтов Exa
$PY -u reggers/tavily_reg2.py          # одиночные регеры — по одному
```

### 4. Гейт перед любой публикацией

```bash
python -u tools/scan_secrets.py .          # exit 1 при любом секрете
python -u tools/test_secret_gate.py        # negative control: гейт ОБЯЗАН ловить
python -u tools/redact_json.py --selftest  # корректность редктора
```

**Зависимости окружения:**

| Что | Зачем |
|-----|-------|
| patchright venv | stealth-браузер для регеров |
| IMAP-пул (`IMAP_POOL`) | ящики для magic-link / OTP |
| BrightData Scraping Browser | решает Exa Turnstile **server-side** (зона `mcp_browser`) |
| YesCaptcha / 2captcha | Turnstile там, где Scraping Browser не нужен |
| gh CLI + `GH_PAT` | публикация отчётов в репо |

---

## 🧩 Каждый сервис: флоу + что надо

### Exa — 🏆 главный приз ($20/акк, batch)
**Вход:** `auth.exa.ai` (Cloudflare Turnstile, sitekey `0x4AAAAAADSpJWQOnICEKAwx`, IP-binding).
**Обход:** обычные пути мертвы (2captcha → IP mismatch; Web Unlocker → не решает; DC-прокси → 404; домашний IP → 429). **Решение: BrightData Scraping Browser решает Turnstile сам server-side.**

Флоу: `connect_over_cdp` → fill email → ждать `cf-turnstile-response` >10 симв (10-20 c) → Continue → письмо `hello [at] exa.ai` c magic link (`html.unescape`!) → «Continue to dashboard» → Vercel checkpoint → **onboarding** → `/api-keys` → Create Key → UUID из input (один раз).

**Грабли:** base-ui radios — только реальные locator-клики (`page.get_by_text("Build with the API").click()`), JS `.click()` не активирует → Continue disabled; UUID из localStorage = tracking-pixel мусор (401); onboarding-редирект асинхронный → goto api-keys с retry; rate limit → `ERR_CONNECTION_CLOSED`, ждать ~5 мин. **~6-7 мин/аккаунт.**

### Firecrawl — magic-link (PKCE)
`firecrawl.dev` → email → письмо со ссылкой. Пароль-логин флейкает — magic-link надёжнее. **Грабли:** strip `]` из линка; clipboard-read permissions выдавать ДО навигации.

### Tavily
`app.tavily.com/signup` → email+password → verify-link из письма → ключ в dashboard. Простая форма, капчи нет. Нужны: patchright + IMAP.

### SerpWrap — Turnstile (YesCaptcha)
Signup → Turnstile → verify → dashboard → ключ → verify `GET serpwrap.com/api/v2/credits` (header `X-API-KEY`). **Грабли:** виджет ленивый — sitekey искать на `.cf-turnstile` (attr на самом div); `inject_token` → `await`.

### You.com — Descope OTP
Signup → OTP (в письме — последнее из 3 чисел) → survey + Create modal на platform. **Грабли:** Descope shadow-root hijack, `isolated_context=False`; ключ в platform UI, НЕ в settings.

### Search1API — Clerk FAPI + TanStack serverFn 🆕
Регистрация **без браузера**: `clerk.s1.dev/v1/client` FAPI (form-urlencoded + `_clerk_js_version`) —
sign_up → Turnstile-токен (YesCaptcha) → `prepare_verification` email_code → IMAP OTP →
`attempt_verification`. Ключ: браузерный sign-in паролем → `/api-keys` → перехват
serverFn `matchedKeys` (UUID, создаётся автоматически). **Грабли:** общий cookie-jar
(`__client`) на ВСЕХ FAPI-вызовах; UA на `api.search1api.com` обязателен (иначе CF 1010);
sitekey/`_clerk_js_version` ротируются — при 400 читать из трафика; в IPv6-only DNS сетях
Turnstile-iframe резолвится в unroutable → `--host-resolver-rules` pin. **~90 с/акк, ~40%/прогон.**

---

## ⛔ Заблокированные цели (проверено, не тратить время)

| Сервис | Блокер |
|--------|--------|
| Serper | reCAPTCHA (YesCaptcha: ERROR_TASK_NOT_SUPPORTED) |
| SerpApi | 429 phone-verify (нужен 5sim-баланс) |
| Brave | plan-wall на карточке |
| SearchApi | timeout/DOM-блок |
| Scrapfly | hCaptcha, сложная |
| Scrapingdog | DNS fail |
| Jina trial | 418 IP-лимит генератора ключей |

---

## 📁 Структура

```
├── README.md                  ← ты здесь
├── FULL_GUIDE.md              ← полный гайд: флоу, грабли, история
├── secrets_env.py             ← единая точка чтения секретов (env / secrets.env)
├── secrets.env.example        ← шаблон → скопировать в secrets.env (gitignored)
├── .gitignore
├── dashboard/
│   ├── index.html             ← дашборд провайдеров
│   └── dashboard.json         ← данные (ключи обрезаны)
├── verify/
│   └── verify_results.json    ← последний live-verify прогон
├── reggers/
│   ├── README.md              ← как запускать регеры
│   ├── reg_base.py            ← база: launch/pick_email/wait_verify/save_result
│   ├── results.json           ← добытые ключи (обрезаны)
│   ├── exa_brd_batch.py       ← Exa batch-регер (главный)
│   ├── exa_brd_browser.py     ← Exa одиночный + диагностика
│   ├── s1_reg.py              ← Search1API batch: Clerk FAPI + serverFn (🆕)
│   ├── firecrawl_magic.py     ├── tavily_reg2.py
│   ├── serpwrap_reg.py        └── you_reg.py
├── research/
│   ├── README.md              ← мультиканальный ресёрч-тулкит + верификация
│   ├── STACK.md               ← курируемый стек: фреймворки DR, 4 swarm-паттерна, тиры API
│   └── harvest/digest/cite_check/adversarial_critic/gap_backedge .py
├── swarm/
│   ├── README.md              ← fan-out паттерн: когда правильный, когда supervisor
│   └── swarm.py               ← N воркеров × темы harvest.py, crash-safe, --resume
├── agents/
│   ├── research-agent.md      ← автономный ресёрч-оператор
│   └── swarm-coordinator.md   ← оркестратор роя ресёрч-агентов (🆕)
├── skills/
│   ├── ebanut-research/SKILL.md    ← методология «ебанутого ресёрча»
│   └── deep-research-swarm/SKILL.md ← веер воркеров + verify-цепочка (🆕)
└── tools/
    ├── verify_all.py          ← live-verify всех ключей одним прогоном
    ├── exa_key_verify.py      ├── fc_verify.py
    ├── brd_cdp_test.py        ← живость Scraping Browser (после rate limit)
    ├── scan_secrets.py        ← ГЕЙТ: exit 1 при любом секрете
    ├── test_secret_gate.py    ← negative control гейта
    └── redact_json.py         ← редктор ключей для данных и доков
```

**Правила выживания:** инлайн HTTP в bash режется → все запросы файлом `.py`; `wait_verify` синхронная (кортеж); ключи проверять live-вызовом, не DOM; фоновые job-ы не поллить.

---

## 🔬 Research-стек: глубокий ресёрч роем

Вторая половина репо — не ключи, а то, что их тратит: мультиканальный
ресёрч-пайплайн с обязательной верификацией и swarm-оркестрацией.

```
topics.json → swarm/swarm.py (N воркеров, crash-safe) → research/harvest.py
  → digest.py → REPORT.md → cite_check → adversarial_critic → gap_backedge ×2
```

| Что | Где | Суть |
|---|---|---|
| Курируемый стек 2026-09 | `research/STACK.md` | какие DR-фреймворки живы (GPT-Researcher / open_deep_research / smolagents), 4 swarm-паттерна, тиры search-API — с вердиктом «что берём» |
| Fan-out оркестратор | `swarm/swarm.py` | ThreadPool × subprocess-воркеры, падение паркует тему, `--resume` докручивает; ноль зависимостей |
| Агент-координатор | `agents/swarm-coordinator.md` | контракт роера: анти-паттерны (циклы handoff, сырые handoff-дампы), invocation, env |
| Скилл | `skills/deep-research-swarm/SKILL.md` | когда роить, сколько воркеров (=RPM пула ключей), verify-цепочка |

**Выбор паттерна:** темы независимы → fan-out без LLM-супервизора
(merge детерминированный). Зависимы → supervisor с капом handoffs —
разбор в `STACK.md` §2.

---

## 🔒 Security

- **В репо нет ни одного секрета.** Ключи, пароли зон, PAT и почтовый пул живут в
  `secrets.env` (gitignored) и читаются через `secrets_env.py`.
- **Гейт:** `tools/scan_secrets.py` — exit 1 при любом совпадении. Прогонять перед
  каждым push. Покрыты UUID, `tvly-`, `fc-`, `jina_`, `ydc-sk-`, `sk-`, 32/64-hex,
  `ghp_`, BrightData-креды, IMAP-пары, bearer, учётка внутри `wss://`-эндпоинта.
- **Negative control:** `tools/test_secret_gate.py` намеренно подкладывает реальные
  ключи в копию `.example` и требует, чтобы гейт их поймал. Гейт, который всегда
  зелёный, хуже отсутствия гейта.
- **Отчёты:** `verify_all.py` пишет в `verify_results.json` только обрезанную форму
  (`redact()` = 6 символов + `…REDACTED`) — строку можно опознать, ключом нельзя воспользоваться.
- **Логи:** `brd_cdp_test.py` вырезает учётку из `wss://`-эндпоинта в ошибках —
  Playwright эхоит эндпоинт вместе с паролем зоны.
- **Точность важнее силы:** hex-дайджест внутри имени файла (`application-<64hex>.js`) —
  это публичный asset hash, а не ключ; f-string-шаблон `wss://…{cid}…` — не кред.
  Такие совпадения исключены, чтобы гейту доверяли.
- **Утёк ключ → ротация**, а не удаление из файла: история git сохраняет всё.

<div align="center">

**Канал: [AlStack](https://t.me/AlStack)** · public · секретов в репо нет · обновлено 2026-09-29

</div>
