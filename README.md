# PsyConsilium MCP

PsyConsilium — продолжение проекта из практического задания №1: проверяемая учебная система поддержки врачебного обсуждения при депрессивных и тревожных состояниях. Она не «угадывает лечение», а собирает воспроизводимые расчёты, публикации и ограничения препарата в единый консилиум.

> Система не ставит диагноз и не выписывает рецепт. Она сравнивает варианты и проверяет введённую врачом плановую дозу по маркировке OpenFDA; результат требует проверки квалифицированным врачом.

## Что здесь полезного

- клинические числа считает детерминированный код, а не LLM;
- у каждого результата видны методика, ограничения и ссылка на источник;
- красные флаги останавливают обычный алгоритм до обращения к внешним источникам;
- для психотерапии, препарата и комбинации выполняются отдельные PICO-поиски;
- нерелевантные статьи отбрасываются по вмешательству, проблеме, популяции и дизайну;
- для введённой врачом дозы показываются начальная доза, титрация, максимум и особые группы из OpenFDA;
- «методолог / адвокат дьявола» явно фиксирует слабые места решения;
- каждую операцию можно показать как JSON-RPC `tools/list` или `tools/call`.

## Архитектура

```text
Streamlit UI
    │
    ├── MCP stdio ───────── PHQ-9 · GAD-7 · AUDIT-C
    │
    ├── MCP Streamable HTTP ─ BMI · CKD-EPI · Cockcroft-Gault
    │                         QTcF · Child-Pugh
    │                         └── legacy /sse + /messages
    │
    ├── external MCP ────── PubMed evidence search
    └── external MCP ────── OpenFDA drug label
                              │
                              ▼
     Case Formulator · Evidence Reviewer · Psychopharmacology Safety
     Somatic Safety · Methodologist / Devil's Advocate
                              │
                     citation integrity check
                              │
                     physician review only
```

Все вычисления и поиски из приложения проходят через `MCPRouter`; прямого обращения к PubMed/OpenFDA API в бизнес-логике нет.

## MCP-источники

| Источник | Транспорт | Инструменты | Назначение |
|---|---|---|---|
| Private Assessments | `stdio` | `phq9`, `gad7`, `audit_c`, `list_calculators` | чувствительные шкалы остаются локально |
| Somatic Safety | `/mcp` Streamable HTTP, `/sse` legacy | `bmi`, `egfr_ckd_epi_2021`, `cockcroft_gault`, `qtc_fridericia`, `child_pugh`, `list_calculators` | пять медицинских направлений |
| [PubMed MCP в Glama](https://glama.ai/mcp/connectors/io.github.cyanheads/pubmed-mcp-server) | внешний Streamable HTTP | поиск и получение статей | доказательная база |
| [OpenFDA MCP в Glama](https://glama.ai/mcp/connectors/io.github.cyanheads/openfda-mcp-server) | внешний Streamable HTTP | drug label и другие FDA-наборы | противопоказания, предупреждения, взаимодействия |

Публичные серверы по умолчанию: `https://pubmed.caseyjhand.com/mcp` и `https://openfda.caseyjhand.com/mcp`. URL можно заменить через `.env`. OpenFDA содержит американскую маркировку и не заменяет актуальную локальную инструкцию.

## Быстрый запуск

Требуется Python 3.11–3.13.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
python run.py
```

Одна команда `python run.py` поднимает локальный MCP и Streamlit:

- UI: `http://127.0.0.1:8501`;
- современный MCP: `http://127.0.0.1:8000/mcp`;
- legacy SSE: `http://127.0.0.1:8000/sse`;
- сообщения legacy-клиента: `http://127.0.0.1:8000/messages?session_id=...`;
- health check: `http://127.0.0.1:8000/health`.

Альтернативно серверы запускаются отдельно:

```bash
python -m psy_consilium.server
python -m psy_consilium.servers.http_server
streamlit run app.py
```

## Демонстрация на защите

1. На экране «Обзор» нажать «Запустить готовый демо-кейс»: синтетический случай проходит весь маршрут без ручного ввода.
2. Открыть «Каталог MCP», выбрать «Приватные шкалы · stdio», получить `tools/list` и вызвать `phq9`.
3. Повторить для локального порта 8000 и `bmi` — показать автоматически построенную по JSON Schema форму.
4. Показать сравнительную матрицу, дословные результаты исследований и проверку плановой дозы 50 мг по OpenFDA.
5. Открыть «JSON-RPC» и показать реальные request/response, транспорт, задержку и cache-hit.
6. Установить пункт 9 PHQ-9 > 0 или красный флаг: система должна остановиться до PubMed/OpenFDA и не показать варианты лечения.

## Безопасность и границы

- модель `PatientCase` принципиально не содержит ФИО, контактов и номера медицинской карты;
- наружу уходят только заболевание, возрастная группа и название препарата-кандидата;
- timeout внешнего MCP — 12 секунд, повторные попытки ограничены, успешные ответы кэшируются на 15 минут;
- входные значения валидируются сначала по JSON Schema, затем в серверном инструменте;
- ошибки MCP показываются пользователю и сохраняются в инспекторе;
- система не генерирует рецепт: она проверяет введённую дозу, а не назначает её;
- это учебный прототип, а не медицинское изделие и не клинически валидированная система.

## Соответствие практическому заданию №2

| Требование | Реализация |
|---|---|
| Собственный `stdio`, ≥3 tools | 3 шкалы + `list_calculators` |
| Python MCP SDK 2.x, lifecycle | `mcp>=2.1,<3`, `async with Client(...)` |
| Локальный сервер на 8000 | `/mcp`, `/sse`, `/messages`, `/health` |
| ≥5 инструментов разных направлений | общая медицина, нефрология, клиническая фармакология, кардиология, гепатология |
| Санитайзер, retry | JSON Schema converter + bounded retries |
| Внешний MCP из Glama | PubMed и OpenFDA |
| Timeout и cache | 12 секунд, TTL 15 минут |
| UI: источник, поиск, формы | вкладка «MCP-инструменты» |
| Риск, методика, источник | карточки результатов и popover |
| JSON-RPC inspector | request/response, timing, transport, cache |
| IDE-конфигурация | `.cursor/mcp.json`, `.vscode/mcp.json`, `.vscode/tasks.json` |
| Запуск одной командой | `python run.py` |

## Тесты

```bash
pytest
```

Тестируются формулы, JSON Schema, оба собственных MCP-сервера, остановка по красному флагу, PICO-фильтрация публикаций и обнаружение превышения максимума из инструкции.

## Структура

```text
app.py                         Streamlit UI
run.py                         единая точка запуска
psy_consilium/calculators.py   детерминированная медицина
psy_consilium/servers/         stdio и HTTP/SSE MCP
psy_consilium/clients/         router, sanitizer, cache, recorder
psy_consilium/consilium.py     оркестрация ролей и citations
psy_consilium/evidence.py      PICO-поиск и оценка применимости
psy_consilium/dosing.py        проверка дозы по OpenFDA label
tests/                         unit и MCP integration tests
```
