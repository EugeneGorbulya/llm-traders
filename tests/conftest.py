import pytest

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
