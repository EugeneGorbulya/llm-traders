"""Model configurations from configs/models.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..core import ROOT

MODELS_YAML = ROOT / "configs" / "models.yaml"
THINK_VALUES = (None, False, True, "low", "medium", "high")


@dataclass
class ModelConfig:
    name: str
    backend: str
    model: str
    options: dict[str, Any] = field(default_factory=dict)
    think: bool | str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    max_tokens: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    platform: str | None = None

    def __post_init__(self) -> None:
        # A typo here is sent to the backend as is or silently ignored by it.
        if self.think not in THINK_VALUES:
            raise ValueError(
                f"{self.name}: think={self.think!r}, expected one of {THINK_VALUES}"
            )

    def cache_identity(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "model": self.model,
            "options": self.options,
            "think": self.think,
            "max_tokens": self.max_tokens,
            "extra": self.extra,
            # The same weights answer differently on CUDA and Metal: without the
            # platform, a cached Mac answer would be served in an A100 run.
            "platform": self.platform,
        }


def load_models(path: Path = MODELS_YAML) -> dict[str, ModelConfig]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    ollama = data["ollama"]
    out = {}
    for name, cfg in data["models"].items():
        if cfg["backend"] == "ollama":
            cfg = dict(cfg, base_url=ollama["url"], platform=ollama["platform"])
        out[name] = ModelConfig(name=name, **cfg)
    return out


def ollama_models() -> list[str]:
    return [n for n, m in load_models().items() if m.backend == "ollama"]


def get_model(name: str, path: Path = MODELS_YAML) -> ModelConfig:
    models = load_models(path)
    if name not in models:
        raise KeyError(f"unknown model {name!r}; known: {', '.join(models)}")
    return models[name]
