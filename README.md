<div align="center">

# 🔍 Search API Farm

**Авторегер-комбайн поисковых / scraping API — 11 live-ключей на 6 сервисах**

`Exa ×6` · `Tavily` · `SerpWrap` · `You.com` · `Firecrawl` · `Jina`

[📊 Dashboard](dashboard/index.html) · [📖 FULL_GUIDE](FULL_GUIDE.md) · [🧪 Live-verify](verify/verify_results.json)

**Канал автора: [AlStack](https://t.me/AlStack)** — автореги, AI-инфраструктура, боты

</div>

---

## ✅ Live-статус (2026-09-28, реальные API-вызовы `tools/verify_all.py`)

| Сервис | Статус | Ключей | Баланс | Тариф | Регер | Готовность |
|--------|:------:|:------:|--------|-------|-------|-----------|
| **Exa** | 🟢 | **6** | **$110** ($10 + 5×$20) | $0.007/поиск | `reggers/exa_brd_batch.py N` | batch, ~80%/прогон |
| **Tavily** | 🟢 | 1 | 1000 req/мес | free tier | `reggers/tavily_reg2.py` | одиночный |
| **SerpWrap** | 🟢 | 1 | 4250 credits (+250/нед) | — | `reggers/serpwrap_reg.py` | одиночный |
| **You.com** | 🟢 | 1 | $100 | — | `reggers/you_reg.py` | одиночный |
| **Firecrawl** | 🟢 | 1 | 1000 credits (reset 27.10) | — | `reggers/firecrawl_magic.py` | одиночный |
| **Jina** | 🟡 | 1 | $0 (trial IP-лимит) | — | — | ключ valid |

**Проверка:** `python -u tools/verify_all.py` → 10/11 OK (Jina 402 — баланс trial исчерпан, ключ валиден).
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

---

## ⛔ Заблокированные цели (проверено, не тратить время)

| Сервис | Блокер |
|--------|--------|
| Search1API | код Apodex не приходит / signup-формы нет на `app.s1.dev` |
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
│   ├── firecrawl_magic.py     ├── tavily_reg2.py
│   ├── serpwrap_reg.py        └── you_reg.py
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

**Канал: [AlStack](https://t.me/AlStack)** · public · секретов в репо нет · обновлено 2026-09-28

</div>
