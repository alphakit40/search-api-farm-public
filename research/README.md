# research/ — мультиканальный ресёрч-тулкит с верификацией

Пайплайн «ебанутого ресёрча» (методология: `../skills/ebanut-research/SKILL.md`,
готовый агент: `../agents/research-agent.md`):

```
harvest.py (сбор) → digest.py (карта) → [синтез] → gap_backedge.py (2 цикла по дырам)
                                                        ↓
              REPORT.md ← adversarial_critic.py ← cite_check.py (0 мёртвых ссылок)
```

## Быстрый старт

```bash
cd research/
python -u harvest.py --list --topics topics.example.json   # посмотреть темы
python -u harvest.py ads_official --topics topics.example.json
python -u digest.py ads_official
# ... пишешь REPORT.md по digest ...
cp facts.example.json verify/facts.json   # отредактируй под свои топ-5 фактов
python -u cite_check.py REPORT.md
python -u adversarial_critic.py
python -u gap_backedge.py scrape gap.json  # full-text ключевых страниц
python -u gap_backedge.py query gap.json   # точечные запросы по дырам
```

`topics.example.json` — рабочий пример: 10 тем × мультиканал по TG-трафику
(по нему собрано 330+ источников, 46/46 цитат верифицировано живыми).
Своя тема = свой JSON: `{"topic_key": [["channel", "query", n], ...]}`.

## Каналы

| Канал | Ключ/env | Примечание |
|---|---|---|
| exa | `EXA_KEYS` (csv, round-robin) | `contents.text` сразу даёт до 1500 симв. текста |
| tavily | `TAVILY_KEY` | search_depth=advanced |
| you | `YOU_KEY` | ydc-index.io |
| fc, rss, yt, gh, hn, reddit | `RSTACK_PATH` | внешний rstack.py; без него — SKIP, остальное работает |

Каждая запись: `{title, url, snippet, date, topic, channel, query}` — append в
`raw/harvest_<topic>.jsonl`, crash-safe (flush на каждую запись), дедуп по URL
внутри топика (перезапуск не плодит дубли).

## Env

| Var | Default | Назначение |
|---|---|---|
| `SEARCH_API_FARM_SECRETS` | `./secrets.env` | KEY=VALUE env-файл, подхватывается если существует |
| `RESEARCH_ROOT` | каталог скрипта | корень с raw/, verify/, REPORT.md |
| `RSTACK_PATH` | — | путь к внешнему rstack.py (12 каналов) |
| `GATEWAY_URL` | `http://127.0.0.1:16432` | OpenAI-compatible шлюз для критика |
| `CRITIC_MODEL` | `deepseek-v4-flash-0731,deepseek-chat,deepseek-v3` | csv fallback; reasoning-модели ок (max_tokens=8000, fallback на `reasoning_content`) |

## Принципы

- **Верификация не опциональна**: отчёт без `cite_check.py` = черновик.
- **Критик из другого семейства**: модель, атакующая факты, ≠ модели писателя.
- **Ноль хардкода**: ни путей, ни ключей в коде; всё через env.
- Ключи никогда не коммитятся (гейт `../tools/scan_secrets.py` режет пуш).
