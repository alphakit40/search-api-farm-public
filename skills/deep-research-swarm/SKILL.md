# Deep-research swarm — веер воркеров + verify-цепочка

Скилл оркестрации глубокого ресёрча роем: цель → независимые слайсы →
fan-out воркеров → merge → детерминированная верификация. Отличие от
`ebanut-research` (базовая методология): этот — про параллельность — сколько
воркеров, как делить, как не умереть от rate-limit и как сводить.

## When to use

- Источников нужно > 100 или тем > 4 — последовательный harvest упирается
  в латентность каналов, не в качество.
- Ключей ≥ 2 в пуле (Exa ~10 RPM на ключ: 4 ключа = 4 полезных воркера).

## Workflow

1. **Слайсы**: разбиение цели на независимые темы-ключи (JSON формата
   `research/topics.example.json`: `{"topic_key": [["channel","query",n],…]}`).
   Темы НЕ должны зависеть друг от друга — иначе это supervisor-паттерн
   (см. `research/STACK.md` §2), не fan-out.
2. **Фан-аут**: `cd research/ && python -u ../swarm/swarm.py --topics t.json --workers 4`
   — воркеры = изолированные subprocess, падение паркует тему (`--resume`
   докручивает). Число воркеров = числу «свободных» RPM пула ключей.
3. **Merge**: `--digest` (или руками `digest.py` по темам) → синтез
   REPORT.md по картам источников.
4. **Verify (не опционально)**: `cite_check.py REPORT.md` (0 мёртвых ссылок)
   → `adversarial_critic.py` (модель из ДРУГОГО семейства) →
   `gap_backedge.py` × 2 цикла по дырам.
5. **Счёт**: run_report.json (время/падения тем) — источник для решения
   «добавить ключей или снизить воркеров».

## Failure modes

| Симптом | Действие |
|---|---|
| Темы спаркованы с `ok:false` | `--resume`; 2й фейл = канал мёртв, слайс в отчёт «не нашлось» |
| 429 от Exa/Tavily | воркеров вниз до числа ключей; ключ в пул (`reggers/`) |
| Timeout 30 мин/тема | слайс слишком широкий — дробить на 2 темы |
| Воркеров > RPM пула | latency не падает, очередь растёт → воркеров вниз |

## Gotchas

- **Плоский граф = нет циклов**: fan-out не нуждается в max_handoffs, но при
  ручном LLM-оркестре кап на переходы обязателен (A→B→A жжёт бюджет).
- Handoff воркеру — суммаризованный слайс, НЕ сырой контекст соседа.
- Дедуп уже в harvest.py (по URL внутри темы) — `--resume` безопасен.
- Сведение без verify = черновик: cite_check до критика, критик до отчёта.

## Тулинг (этот репо)

```bash
cd research/
python -u ../swarm/swarm.py --topics topics.example.json --workers 4 --digest
python -u ../swarm/swarm.py --resume
python -u cite_check.py REPORT.md && python -u adversarial_critic.py
python -u gap_backedge.py scrape gap.json && python -u gap_backedge.py query gap.json
```

Env: как у `agents/swarm-coordinator.md` (EXA_KEYS csv, TAVILY_KEY, YOU_KEY,
RSTACK_PATH, GATEWAY_URL, CRITIC_MODEL, SEARCH_API_FARM_SECRETS).

## References
- `../research/STACK.md` — курируемый стек: фреймворки, 4 swarm-паттерна, тиры API
- `ebanut-research` skill — базовая методология verify-цепочки
- `../swarm/README.md` — гарантии crash-safety/idempotency
