# swarm/ — fan-out оркестрация ресёрч-воркеров

Один файл: `swarm.py`. Ноль зависимостей — стандартная библиотека.

```
topics.json ──► ThreadPool(N) ──► subprocess harvest.py <тема> × N
                                        │ (crash = тема спаркована, рой жив)
                  run_report.json ◄─────┘
                                        └─► digest.py по темам (--digest)
```

```bash
cd research/
python -u ../swarm/swarm.py --topics topics.json --workers 4 --digest
python -u ../swarm/swarm.py --resume          # докрутить упавшие темы
```

## Паттерн и когда он правильный

Это **pipeline / fan-out** — один из четырёх канонических swarm-паттернов
(разбор всех четырёх + источники: `../research/STACK.md` §2). Правильный выбор,
когда слайсы независимы (темы ресёрча не зависят друг от друга) и merge
детерминированный (digest). LLM-супервизор тут = лишний узел латентности.

**Когдаfan-out НЕ подходит** и нужен supervisor (агент-планировщик, langgraph
`Command(goto=…)` handoffs): темы зависят друг от друга, следующий запрос
определяется результатом предыдущего, или нужен адаптивный бюджет. Тогда —
`../agents/swarm-coordinator.md` как оркестратор в сессии, воркеры — те же
subprocess-слайсы.

## Гарантии

- **Crash-safe**: воркер = subprocess; SIGSEGV/timeout паркует тему
  (`ok:false` в run_report.json), пул продолжает остальные.
- **Idempotent-повтор**: harvest.py дедупит по URL внутри темы — `--resume`
  не плодит дубли.
- **Timeout 30 мин/тема** — защиты от зависших сетевых каналов.
- `max_handoffs`-аналог не нужен: граф вызовов плоский, циклов нет.

## Числа

`--workers 4` = 4 параллельных IMAP/search-сессии; лимит — не CPU, а rate-limit
поисковых API (см. `../research/STACK.md` §3: Exa ~10 RPM/ключ × N ключей).
Больше 4–6 воркеров имеет смысл только при пропорциональном росте пула ключей.
