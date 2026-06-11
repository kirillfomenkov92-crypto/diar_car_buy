# Claude Code Project: Diar Car Buy AI v3.0

## Проектные конвенции
- Язык: Python 3.10+
- Тесты: pytest
- Логи: agent.log
- Конфиг: config.yaml
- БД: diar_car_buy.db

## Доступные агенты
- @orchestrator — координатор
- @code-architect — рефакторинг
- @domain-expert — DCB Score, арбитраж
- @parser-expert — источники данных
- @testing-expert — тесты
- @debugger — отладка

## Рабочие процессы
### Исправление бага
1. @debugger находит причину
2. @domain-expert проверяет логику
3. @testing-expert пишет падающий тест

## Полезные команды
- /audit-parsers — проверить все парсеры
- /market-check [модель] — смоделировать DCB
