# reggers/ — регеры API-ключей

Каждый регер — автономный скрипт поверх `reg_base.py` (почтовый пул, капчи, браузер).
Секретов в коде нет: всё читается из `secrets.env` через `../secrets_env.py`.

## Подготовка

```bash
cp ../secrets.env.example ../secrets.env    # заполнить значения
```

Нужен venv с **patchright**; запускай всегда с `-u` (иначе буферизация прячет прогресс):

```bash
PY="/path/to/patchright-venv/Scripts/python.exe"
```

## Запуск

| Скрипт | Что делает | Нужные переменные |
|---|---|---|
| `exa_brd_batch.py N` | N аккаунтов Exa батчем (~6-7 мин/акк) | `BRD_CUSTOMER`, `BRD_ZONE_MCP_BROWSER`, `IMAP_POOL` |
| `exa_brd_browser.py` | один аккаунт Exa, verbose-дамп после каждого шага | то же |
| `firecrawl_magic.py` | **дорегистрирует** существующий Firecrawl-аккаунт magic-link'ом | `FIRECRAWL_EMAIL`, `IMAP_POOL` |
| `tavily_reg2.py` | Tavily: signup + verify-link | `IMAP_POOL` |
| `serpwrap_reg.py` | SerpWrap: Turnstile через YesCaptcha | `YESCAPTCHA_KEY`, `IMAP_POOL` |
| `you_reg.py` | You.com: Descope OTP + survey | `IMAP_POOL` |

```bash
$PY -u reggers/exa_brd_batch.py 5
$PY -u reggers/tavily_reg2.py
```

Все скрипты обёрнуты в `if __name__ == "__main__"` — импорт (линтер, pytest, индексатор
редактора) не запустит браузер и не начнёт регистрацию.

## reg_base.py — общая база

| Функция | Назначение |
|---------|-----------|
| `launch(**kw)` | patchright-браузер (`proxy="http://user:pass@host:port"`, `headless=`) |
| `pick_email(svc)` | ящик из пула `imap_pool()`; использованные — в `<svc>_used.txt` |
| `wait_verify(...)` | **СИНХРОННАЯ**, возвращает кортеж `(link, code)` |
| `save_result(svc, rec)` | дописывает `<svc>_result.json` и помечает ящик использованным |
| `solve_turnstile/recaptcha/hcaptcha` | через YesCaptcha; `inject_token(...)` — с `await` |

`POOL` и `YC_KEY` больше не константы: это `imap_pool()` и `req("YESCAPTCHA_KEY")`.

## Результаты

Регеры пишут `<svc>_result.json` рядом с собой — эти файлы в `.gitignore`.
`results.json` в репо — сводка с **обрезанными** ключами.

Проверка добытого:

```bash
python -u tools/verify_all.py     # из корня репо
```

## Грабли (проверено на практике)

- **Ключ — только из input/code на странице ключей.** UUID из `localStorage` — это
  tracking-pixel мусор: выглядит как ключ, на API отвечает 401.
- **base-ui radios активируются только реальным locator-кликом**
  (`page.get_by_text("Build with the API").click()`). JS `.click()` не включает
  состояние → кнопка Continue остаётся disabled.
- **Magic-link из письма нужно `html.unescape()`** — иначе `&amp;` ломает URL.
- **Rate limit выглядит как `ERR_CONNECTION_CLOSED`**, не как 429. Лечится ожиданием
  ~5 мин; живость браузера проверить `../tools/brd_cdp_test.py`.
- **Onboarding-редирект асинхронный**: на `/api-keys` ходить с retry, а не сразу.
- **`wait_verify` синхронная** — внутри async-кода зови через executor, не `await`.
- **Инлайн HTTP в shell режется** — любой запрос оформляй отдельным `.py`-файлом.
- Никогда не печатай ключ и CDP-эндпоинт целиком: в логе должен быть `redact(key)`.
