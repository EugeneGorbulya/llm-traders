import json

import pytest

from llmtraders import level1
from llmtraders.chat import DEFAULT_BANK, MessageBank
from llmtraders.llm.cache import ResponseCache
from llmtraders.llm.client import LLMClient
from llmtraders.llm.log import JsonlLogger


@pytest.fixture
def bank():
    return MessageBank.load(DEFAULT_BANK, prefer_frozen=False)


@pytest.fixture
def client(tmp_path):
    return LLMClient(
        cache=ResponseCache(tmp_path / "cache.sqlite"),
        logger=JsonlLogger(tmp_path / "calls.jsonl"),
    )


@pytest.fixture
def mock_run(tmp_path):
    """A small level-1 run of a mock model that passed the quiz (score in
    tmp_path / "quiz" / name): returns the run directory."""

    def run(conditions, model="mock-gullible", samples=1, fmt="a", name=None):
        name = name or model
        out = level1.run(
            model,
            conditions=conditions,
            samples=samples,
            fmt=fmt,
            out_dir=tmp_path / f"{name}_{fmt}",
            cache_path=tmp_path / "c.sqlite",
            quiet=True,
        )
        quiz = tmp_path / "quiz" / name
        quiz.mkdir(parents=True, exist_ok=True)
        (quiz / "score.json").write_text(json.dumps({"passed": True}), encoding="utf-8")
        return out

    return run
