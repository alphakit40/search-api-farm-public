# STACK — курируемый стек deep-research / swarm (2026-09)

Дип-ресёрч 2026-09: фреймворки глубокого ресёрча, паттерны swarm-оркестрации,
тиры search-API. Здесь — только проверенное и то, что реально берём в работу.
Конкуренты, которые НЕ прошли отбор, указаны с причиной.

## 1. Фреймворки deep-research

| Фреймворк | URL | Лицензия | ★ | Архитектура | Вердикт |
|---|---|---|---|---|---|
| **GPT-Researcher** | https://github.com/assafelovic/gpt-researcher | MIT | ~29K | план → параллельный web-crawl → вертикальные отчёты («планировщик-исполнитель») | ✅ брать идеи: report-типы (basic/deep), параллельный под-ресёрч |
| **Open Deep Research** (LangChain) | https://github.com/langchain-ai/open_deep_research | MIT | ~12.5K | supervisor + N суб-агентов-исследователей + LLM-as-judge оценок | ✅ брать идеи: multi-perspective конфигурация, judge-скоринг веток |
| **smolagents** (HF) | https://github.com/huggingface/smolagents | Apache-2.0 | ~10K | CodeAgent: агент пишет Python-код вместо JSON tool-calls | ✅ брать идеи: код-как-экшн для массовых структурных выборок |
| LangGraph контур | https://github.com/langchain-ai/langgraph | MIT | — | граф состояний, `Command(goto=…)` handoffs | ⚠️ паттерн берём, библиотеку — нет (см. ниже) |
| Deer-Flow / STORM / LDR | https://github.com/bytedance/deer-flow и др. | — | — | поContent-пайплайны | ❌ monorepo-сложность > пользы для нашего масштаба |

**Качество open vs closed (GAIA, 2026):** OpenAI Deep Research ~67% vs лучшие
open-стеки 54–55%. Вывод: open-стек проигрывает ~10 п.п. на hard-benchmark —
закрывается дешевизной параллелизма и количеством агентов, а не умом одного.

## 2. Swarm-паттерны оркестрации (LangGraph/Anthropic canon 2026)

| Паттерн | Суть | Когда |
|---|---|---|
| **Supervisor** | один менеджер-узел, tool-calls = суб-агенты, результаты назад в контекст менеджера | default; когда нужны планирование и сведение |
| **Swarm (handoff)** | одноранговые агенты, `Command(goto=…)` передаёт управление + контекст следующему | латентность важнее плана; короткие цепочки |
| **Hierarchical** | supervisor → суб-supervisor'ы → воркеры | N > ~10 воркеров, зоопарка ролей |
| **Pipeline / fan-out** | без LLM-менеджера: N воркеров по независимым слайсам, merge в конце | **наш случай**: темы независимы, merge = digest.py |

**Обязательные защиты (из боевых паттернов 2026):**
- `max_handoffs` + `visited_agents` — защита от циклов A→B→A;
- handoff = **суммаризованный** контекст, не сырой дамп (контекст-декомпрессия);
- воркер падает → слайс паркуется, рой не останавливается (crash-safe slices).

**Наш выбор: fan-out без фреймворка.** Темы в `topics.json` независимы →
LangGraph/CrewAI не нужны: `swarm/swarm.py` = ThreadPool + subprocess-изоляция
воркеров поверх `research/harvest.py`. Супервизор-логика (план/merge) — человек
или один LLM-вызов после fan-out. Ноль новых зависимостей.

## 3. Search-API тиры (free, 2026-09)

| API | Free | RPM | Примечание |
|---|---|---|---|
| **Exa** | 20K/мес search-only + $10 кредитов на регистрацию | ~10 (у нас 6 ключей = ~60 RPM) | содержимое сразу в ответе — основной сбор |
| **Tavily** | 1000 кредитов/мес | 100 | search_depth=advanced |
| **Brave** | free-tier убран 02-2026 → $5/мес кредиты | — | ❌ больше не фармится |
| **Jina Reader** | 10M токенов free | 100 | fetch-канал |
| **SearXNG** | self-host, безлимит | свой | фолбэк-метапоиск |
| **Search1API** | 100 кредитов/аккаунт | — | 🆕 наш регер `reggers/s1_reg.py` |

## References
- GAIA-сравнение open vs closed: gpt-researcher / open_deep_research README-бенчи
- LangGraph multi-agent: https://langchain-ai.github.io/langgraph/ (supervisor/swarm туториалы)
- Сводка паттернов 2026: Anthropic "Building effective agents" + LangGraph docs
