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
uv run python -m experiments.level15 --model qwen3-8b  # У1.5: цена по сценарию x чат (--seeds 1: смоук)
uv run python -m analysis.level1 results/level1/qwen3-8b
uv run python -m experiments.bank                      # проверка банка; --freeze: заморозка
```

## Модели

Ollama 0.40.15 (Homebrew), Mac M5 24 GB. На macOS 26 llama-server падает без `launchctl setenv GGML_METAL_TENSOR_DISABLE 1` и перезапуска Ollama.

| Конфигурация | Тег Ollama | Параметры | Квантизация | Digest | Размышление |
|---|---|---|---|---|---|
| qwen3-4b | qwen3:4b-instruct-2507-q4_K_M | 4.0B | Q4_K_M | 0edcdef34593 | нет |
| qwen3-8b | qwen3:8b | 8.2B | Q4_K_M | 500a1f067a9f | выкл |
| qwen3-14b | qwen3:14b | 14.8B | Q4_K_M | bdbd181c33f2 | выкл |
| qwen3-14b-think | qwen3:14b | 14.8B | Q4_K_M | bdbd181c33f2 | вкл |
| llama3.1-8b | llama3.1:8b | 8.0B | Q4_K_M | 46e0c10c039e | нет |
| gpt-oss-20b-low | gpt-oss:20b | 20.9B | MXFP4 | f38aa0c53da5 | low |
| gpt-oss-20b-high | gpt-oss:20b | 20.9B | MXFP4 | f38aa0c53da5 | high |

Сэмплинг и лимиты токенов - `configs/models.yaml`. Полный digest пишется в каждую строку `calls.jsonl`.

Что где лежит:
- `llmtraders/` - движок и клиент моделей с кэшем;
- `experiments/`, `analysis/` - скрипты запуска и таблиц;
- `configs/` - модели, сетка У1, У1.5;
- `data/messages/` - банк сообщений;
- `results/` - результаты и кэш ответов.
