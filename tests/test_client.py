import dataclasses
import json
import re
import urllib.error
from types import SimpleNamespace

import pytest

from llmtraders.agents import validate_trader
from llmtraders.core import Observation
from llmtraders.llm.backends import AnthropicBackend, Backend
from llmtraders.llm.cache import ResponseCache
from llmtraders.llm.client import LLMClient, extract_json
from llmtraders.llm.config import get_model, load_models
from llmtraders.llm.log import JsonlLogger
from llmtraders.prompts import (
    BELIEF,
    PROMPT_VERSION,
    RESPONSE_SCHEMA,
    PromptConfig,
    build_messages,
)


def messages():
    obs = Observation(
        period=3,
        n_periods=12,
        cash=1000,
        shares=10,
        price_history=[],
        official=[(4, "good")],
        chat=[],
        ref_price=100,
    )
    return build_messages(obs, PromptConfig())


def ask(client, model, sample=0):
    return client.query(
        get_model(model),
        messages(),
        schema=RESPONSE_SCHEMA,
        validate=validate_trader,
        sample_idx=sample,
        seed_parts=("t",),
        prompt_version=PROMPT_VERSION,
    )


def test_models_yaml_loads():
    models = load_models()
    assert {
        "qwen3-4b",
        "qwen3-8b",
        "qwen3-14b",
        "qwen3-14b-think",
        "llama3.1-8b",
        "gpt-oss-20b-low",
        "gpt-oss-20b-high",
        "mock-rational",
    } <= set(models)
    assert models["qwen3-4b"].model == "qwen3:4b-instruct-2507-q4_K_M"


def test_platform_is_part_of_the_cache_key():
    models = load_models()
    a100 = models["qwen3-8b"]
    assert a100.platform and a100.base_url
    assert models["gpt-oss-20b-high"].platform == a100.platform
    assert models["mock-rational"].platform is None
    mac = dataclasses.replace(a100, platform="mac")
    assert mac.cache_identity() != a100.cache_identity()


def test_rerun_is_all_cache_hits(tmp_path):
    cache = ResponseCache(tmp_path / "c.sqlite")
    first = LLMClient(cache=cache)
    r1 = [ask(first, "mock-rational", s) for s in range(3)]
    assert first.stats["hits"] == 0
    second = LLMClient(cache=cache)
    r2 = [ask(second, "mock-rational", s) for s in range(3)]
    assert second.stats == {"calls": 3, "hits": 3, "invalid": 0}
    assert [r.parsed for r in r1] == [r.parsed for r in r2]


def test_offline_mode_raises_on_miss(tmp_path):
    c = LLMClient(cache=ResponseCache(tmp_path / "c.sqlite"), offline=True)
    with pytest.raises(RuntimeError):
        ask(c, "mock-rational")


def test_retry_once_on_invalid_json(client):
    res = ask(client, "mock-broken")
    assert res.valid and res.attempts == 2
    bad = ask(client, "mock-garbage")
    assert not bad.valid and bad.attempts == 2 and bad.error == "invalid JSON"
    assert client.stats["invalid"] == 1


def test_every_call_logged_with_version_and_commit(tmp_path):
    log = tmp_path / "calls.jsonl"
    c = LLMClient(cache=ResponseCache(tmp_path / "c.sqlite"), logger=JsonlLogger(log))
    ask(c, "mock-broken")
    recs = [json.loads(x) for x in log.read_text().splitlines()]
    assert [r["attempt"] for r in recs] == [0, 1]
    assert [r["valid"] for r in recs] == [False, True]
    assert all(r["prompt_version"] == PROMPT_VERSION and r["git"] for r in recs)


def test_extract_json_tolerates_fences_and_prose():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! {"a": 2} hope this helps') == {"a": 2}
    assert extract_json("no json here") is None
    assert extract_json("[1, 2]") is None


BASE = {
    "analysis": "r",
    BELIEF: 0.7,
    "fair_value": 112,
    "order": "buy",
    "price_limit": 110,
    "quantity": 3,
}


def test_answer_fields_sort_in_the_order_the_model_must_write_them():
    required = RESPONSE_SCHEMA["required"]
    assert sorted(required) == required
    assert required.index("analysis") < required.index(BELIEF) < required.index("order")


def test_validate_ok_and_percent_rescale():
    ok, norm, _ = validate_trader(BASE)
    assert ok and norm["p_high"] == 0.7 and not norm["p_rescaled"]
    ok, norm, _ = validate_trader({**BASE, BELIEF: 70})
    assert ok and norm["p_high"] == pytest.approx(0.7) and norm["p_rescaled"]


@pytest.mark.parametrize(
    "patch",
    [
        {BELIEF: 170},
        {BELIEF: -0.1},
        {"order": "short"},
        {"quantity": 2.5},
        {"quantity": -1},
        {"fair_value": "lots"},
    ],
)
def test_validate_rejects(patch):
    ok, _, err = validate_trader({**BASE, **patch})
    assert not ok and err


def test_validate_missing_field_and_hold_normalisation():
    ok, _, err = validate_trader({k: v for k, v in BASE.items() if k != "quantity"})
    assert not ok and "missing" in err
    ok, norm, _ = validate_trader({**BASE, "quantity": 0})
    assert ok and norm["side"] == "hold"


class FailingBackend(Backend):
    def __init__(self, error: Exception):
        self.error = error

    def generate(self, cfg, messages, schema, seed):
        raise self.error


def client_with(backend: Backend, tmp_path) -> LLMClient:
    client = LLMClient(cache=ResponseCache(tmp_path / "c.sqlite"))
    client._backends["mock"] = backend
    return client


def test_connection_refused_stops_the_run(tmp_path):
    # A dropped SSH tunnel to the VM looks like this: stop, do not log invalids.
    client = LLMClient(cache=ResponseCache(tmp_path / "c.sqlite"))
    client._backends["ollama"] = FailingBackend(ConnectionRefusedError(61, "refused"))
    url = get_model("qwen3-8b").base_url
    with pytest.raises(RuntimeError, match=f"not responding at {re.escape(url)}"):
        ask(client, "qwen3-8b")


def test_server_errors_are_invalid_answers(tmp_path):
    error = urllib.error.HTTPError("http://x", 500, "out of memory", None, None)
    client = client_with(FailingBackend(error), tmp_path)
    res = ask(client, "mock-rational")
    assert not res.valid and res.attempts == 2 and "HTTPError" in res.error
    assert client.stats["invalid"] == 1


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            urllib.error.HTTPError("http://x", 404, "not found", None, None),
            RuntimeError,
        ),
        (ValueError("bug in a backend"), ValueError),
    ],
)
def test_setup_errors_and_bugs_stop_the_run(tmp_path, error, expected):
    client = client_with(FailingBackend(error), tmp_path)
    with pytest.raises(expected):
        ask(client, "mock-rational")


def test_a_run_of_server_errors_stops_the_run(tmp_path):
    error = urllib.error.HTTPError("http://x", 500, "Internal Server Error", None, None)
    client = client_with(FailingBackend(error), tmp_path)
    assert not ask(client, "mock-rational", sample=0).valid
    assert not ask(client, "mock-rational", sample=1).valid
    with pytest.raises(RuntimeError, match="HTTP 500 .* 6 times in a row"):
        ask(client, "mock-rational", sample=2)


@pytest.mark.parametrize("name", ["claude-haiku-5.5", "claude-sonnet-5.5"])
def test_anthropic_request_asks_for_json_without_sampling(name):
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text='{"order": "hold"}')],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            stop_reason="end_turn",
        )

    backend = AnthropicBackend()
    backend._client = SimpleNamespace(messages=SimpleNamespace(create=create))
    cfg = get_model(name)
    r = backend.generate(cfg, messages(), RESPONSE_SCHEMA, seed=7)

    assert sent["output_config"]["format"]["schema"] == RESPONSE_SCHEMA
    assert sent["thinking"] == cfg.extra["thinking"]
    assert not {"temperature", "top_p", "top_k", "tools", "tool_choice"} & sent.keys()
    assert all(m["role"] != "system" for m in sent["messages"])
    assert r.text == '{"order": "hold"}'


def _anthropic_error(kind: str) -> Exception:
    anthropic = pytest.importorskip("anthropic")
    httpx = pytest.importorskip("httpx2")
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    if kind == "connection":
        return anthropic.APIConnectionError(request=req)
    code = 529 if kind == "overloaded" else 400
    response = httpx.Response(code, request=req)
    return anthropic.APIStatusError(kind, response=response, body=None)


@pytest.mark.parametrize(
    ("kind", "stops"),
    [("overloaded", None), ("bad request", RuntimeError), ("connection", RuntimeError)],
)
def test_api_errors_follow_the_ollama_rule(tmp_path, kind, stops):
    # An overloaded API is a failed answer (retry, then invalid); a 4xx or no
    # connection stops the run, as with Ollama.
    error = _anthropic_error(kind)

    def create(**kwargs):
        raise error

    backend = AnthropicBackend()
    backend._client = SimpleNamespace(messages=SimpleNamespace(create=create))
    client = client_with(backend, tmp_path)
    if stops is None:
        res = ask(client, "mock-rational")
        assert not res.valid and res.attempts == 2 and "529" in res.error
    else:
        with pytest.raises(stops):
            ask(client, "mock-rational")


def test_a_dropped_tunnel_at_the_digest_stops_with_the_watchdog_text(tmp_path):
    class NoDigest(Backend):
        def digest(self, cfg):
            raise urllib.error.URLError(ConnectionRefusedError(61, "refused"))

    client = LLMClient(cache=ResponseCache(tmp_path / "c.sqlite"))
    client._backends["ollama"] = NoDigest()
    with pytest.raises(RuntimeError, match="not responding"):
        ask(client, "qwen3-8b")
