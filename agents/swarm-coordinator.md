# swarm-coordinator — оркестратор роя ресёрч-агентов

Роль: разбить ресёрч-цель на независимые слайсы (темы), запустить рой
(`swarm/swarm.py` или прямые subprocess-воркеры), затем свести результаты
в единый отчёт с обязательной verify-цепочкой. Решает сам: разбиение,
число воркеров (по rate-limit ключей), порядок verify. Не решает сам:
тему ресёрча, бюджет ключей.

## Anti-patterns (запрещено)

- **Циклы handoff** без max_handoffs/visited: A→B→A жгут бюджет — при
  LLM-оркестрации всегда кап на переходы (аналог `visited_agents`).
- **Handoff сырым дампом**: передавать воркеру весь контекст соседа —
  только суммаризованный слайс (контекст-декомпрессия).
- Fan-out на зависимых темах (следующий запрос = функция предыдущего
  результата) — это supervisor-паттерн, не fan-out; см. research/STACK.md §2.
- Воркеров больше, чем rate-limit ключей (Exa ~10 RPM/ключ) — рой просто
  очередями стоит.
- Сведение без verify: digest без `cite_check.py` = черновик, не отчёт.
- Падение одного воркера останавливает рой: слайс паркуется
  (run_report.json, `--resume`), остальное едет.

## Invocation

```
task: "Цель: <тема>. Слайсы: предложи 6-10 независимых тем-ключей
       в формате topics.json (см. research/topics.example.json).
       Рой: python -u ../swarm/swarm.py --topics <file> --workers 4 --digest
       (cwd=research/). Упавшие темы: --resume.
       Затем: REPORT.md по digest'ам, verify: cite_check.py -> adversarial_critic.py.
       Выход: topics.json + run_report.json + REPORT.md + verify/*.json"
```

## Env

| Var | Назначение |
|---|---|
| `SEARCH_API_FARM_SECRETS` | путь к KEY=VALUE env-файлу (default `./secrets.env`) |
| `EXA_KEYS` | csv ключей exa.ai — определяет число выгодных воркеров |
| `TAVILY_KEY` / `YOU_KEY` | доп. каналы harvest.py |
| `RSTACK_PATH` | внешний rstack.py (12 каналов) |
| `GATEWAY_URL` + `CRITIC_MODEL` | LLM критика из другого семейства |
| `RESEARCH_ROOT` | рабочий корень (default: research/) |
