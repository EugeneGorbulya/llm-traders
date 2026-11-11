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
uv run python -m experiments.level2_smoke --model qwen3-8b  # смоук У2: 4 LLM + ZI, одна сессия без манипулятора
uv run python -m experiments.finbert                   # FinBERT-трейдер на лентах У1 (бейзлайн, без LLM)
uv run python -m experiments.defenses --model qwen3-4b  # защиты D1-D4 по configs/defenses.yaml: 600 вызовов + фильтр D4
uv run python -m experiments.d4_labels                 # пустой лист data/labels/d4_feed.csv для ручной разметки ленты
uv run python -m analysis.level1 results/level1/*/     # гипотезы, k из n, выбор для У2 (одна папка - таблицы одного прогона)
uv run python -m analysis.defenses results/level1/*/   # защиты по трём осям, D4 как классификатор
uv run python -m experiments.bank                      # проверка банка; --freeze: заморозка
```

## Модели

Все прогоны идут на арендованной NVIDIA A100 80 GB (immers.cloud), Ollama 0.40.15. Пилот 8.11 шёл на Mac M5 24 GB (`results/mac/`); там llama-server на macOS 26 падает без `launchctl setenv GGML_METAL_TENSOR_DISABLE 1`. Одна и та же модель отвечает на CUDA и на Metal по-разному, поэтому платформа входит в ключ кэша, а все прогоны одной модели идут на одной платформе.

| Конфигурация | Тег Ollama | Параметры | Квантизация | Digest | Размышление |
|---|---|---|---|---|---|
| qwen3-4b | qwen3:4b-instruct-2507-q4_K_M | 4.0B | Q4_K_M | 0edcdef34593 | нет |
| qwen3-8b | qwen3:8b | 8.2B | Q4_K_M | 500a1f067a9f | выкл |
| qwen3-14b | qwen3:14b | 14.8B | Q4_K_M | bdbd181c33f2 | выкл |
| qwen3-14b-think | qwen3:14b | 14.8B | Q4_K_M | bdbd181c33f2 | вкл |
| llama3.1-8b | llama3.1:8b | 8.0B | Q4_K_M | 46e0c10c039e | нет |
| gpt-oss-20b-low | gpt-oss:20b | 20.9B | MXFP4 | f38aa0c53da5 | low |
| gpt-oss-20b-high | gpt-oss:20b | 20.9B | MXFP4 | f38aa0c53da5 | high |

Сэмплинг, лимиты токенов, платформа и адрес Ollama - `configs/models.yaml`. Полный digest и платформа пишутся в каждую строку `calls.jsonl`.

Две модели идут через Anthropic API (квиз и сетка У1, 10.11.2026), A100 им не нужна:

| Конфигурация | Модель API | Размышление | Сэмплинг |
|---|---|---|---|
| claude-haiku-5.5 | `claude-haiku-5-5` | выкл (`thinking: disabled`) | по умолчанию |
| claude-sonnet-5.5 | `claude-sonnet-5-5` | `thinking: between_tools`: только между вызовами инструментов, а их в задаче нет | по умолчанию |

Ответ идёт через structured outputs (`output_config`, та же JSON-схема, что у локальных моделей). Сэмплинг по умолчанию, потому что обе модели отвечают 400 на нестандартный (temperature и т. п.) и не принимают seed. Поэтому сэмплы различаются только случайностью API, а повторный прогон берёт ответы из кэша. Sonnet 5.5 не принимает `thinking: disabled`, поэтому у него `between_tools`. Ключ берётся из переменной `ANTHROPIC_API_KEY`. Квиз обеих моделей стоил $0.11, сетка У1 ≈ $4.3. Запуск тот же, что у локальных: `uv run python -m experiments.level1 --model claude-haiku-5.5`.

FinBERT-бейзлайн: `ProsusAI/finbert` с Hugging Face, ревизия `0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031` (зафиксирована в `llmtraders/finbert.py`), считается на CPU Mac. Каждый текст ленты (официальная новость и чат) голосует своей меткой: покупка, если позитивных больше, чем негативных, продажа - если меньше.

## Запуск на A100

На ВМ работает только Ollama. Код, кэш и логи остаются на Mac, Ollama доступна через SSH-туннель. На ВМ (Ubuntu с драйвером NVIDIA):

```bash
curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION=0.40.15 sh
for t in qwen3:4b-instruct-2507-q4_K_M qwen3:8b qwen3:14b llama3.1:8b gpt-oss:20b; do ollama pull $t; done
nvidia-smi && ollama -v
```

На Mac, в отдельной вкладке терминала, на всё время прогона (порт 11435, чтобы не попасть в Ollama самого Mac):

```bash
ssh -N -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes -L 11435:localhost:11434 <user>@<ip>
```

Затем на Mac:

```bash
curl -s localhost:11435/api/tags                                 # туннель работает
caffeinate -i -s uv run python -m experiments.pilot              # пилот и квиз на A100
```

Mac должен не спать, пока идёт прогон: клиент работает на нём. Если туннель оборвался, прогон останавливается. Повторный запуск берёт готовые ответы из кэша и продолжает с места обрыва. Если digest на ВМ не совпал с таблицей, значит тег обновился: запишите новый digest в таблицу.

Что где лежит:
- `llmtraders/` - движок и клиент моделей с кэшем;
- `experiments/`, `analysis/` - скрипты запуска и таблиц;
- `configs/` - модели (локальные и API), сетка У1, У1.5, защиты;
- `data/messages/` - банк сообщений: исходник `bank_v1.yaml` и замороженный `bank_v1.frozen.json` (10.11.2026, sha256 `fa80bf71b3e69179c3d9bcbca4120179742430dc1f6f22487e35665ca25b51bb`); код берёт замороженный, если он есть;
- `data/labels/` - ручная разметка ленты для D4 `d4_feed.csv` (11.11.2026, sha256 `cbd0c6216512b2299072fa5384eb3440fcd82345d31c56c48aaa78de0693797b`): истина для D4 как классификатора;
- `results/` - результаты и кэш ответов; `results/mac/` - пилот и квиз 8.11 на Mac.
