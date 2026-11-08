# LLM-трейдеры и манипуляции через текст

Игрушечный рынок: call auction, актив стоимостью 70 или 130, 12 периодов. На нём торгуют LLM-трейдеры, а скриптовый манипулятор пишет в чат. Меряем, как фейки, хайп, social proof, авторитет и prompt injection сдвигают p(130), заявки и цену.

## Установка

```bash
uv venv --python 3.12 && uv pip install -e ".[dev,analysis,nlp]"
uv run pytest
```

## Запуск

```bash
uv run python -m experiments.pilot                     # пилот: ~50 вызовов У1 + квиз на модель
uv run python -m experiments.quiz                      # Байес-квиз
uv run python -m experiments.level1 --model qwen3-8b   # сетка У1 (--dry-run: только число вызовов)
uv run python -m analysis.level1 results/level1/qwen3-8b
uv run python -m experiments.bank                      # проверка банка; --freeze: заморозка
```

Что где лежит:
- `llmtraders/` - движок и клиент моделей с кэшем;
- `experiments/`, `analysis/` - скрипты запуска и таблиц;
- `configs/` - модели и сетка У1;
- `data/messages/` - банк сообщений;
- `results/` - результаты и кэш ответов.
