"""Create reusable text embeddings beside a reference or generated specification."""

from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Literal, Protocol

import yaml
from openai import OpenAI
from pydantic import BaseModel, Field, model_validator

from metis.core.model_settings import ROLES, ModelRole, resolve_role
from metis.core.specification import Specification

if TYPE_CHECKING:
    from typing import Self


class BehaviourText(StrEnum):
    BEHAVIOUR = "behaviour"
    CONTEXT = "feature-behaviour-criteria"


def named_text(name: str, description: object) -> str:
    """Use the same text for embedding generation and metric calculation."""
    return f"{name}\n{description}"


def behaviour_texts(
    specification: Specification, version: BehaviourText
) -> dict[str, str]:
    """Return one text per behaviour; context includes all its criteria."""
    texts: dict[str, str] = {}
    for feature in specification.features:
        for behaviour in feature.behaviours:
            text = named_text(behaviour.name, behaviour.description)
            if version is BehaviourText.CONTEXT:
                parts = [
                    f"Feature: {feature.name}",
                    feature.description,
                    f"Behaviour: {text}",
                    "Criteria:",
                ]
                for criterion in behaviour.criteria:
                    parts.extend(
                        [
                            criterion.name,
                            criterion.description,
                        ]
                    )
                text = "\n".join(parts)
            texts[behaviour.id] = text
    return texts


def specification_texts(specification: Specification) -> list[str]:
    """Include both behaviour versions and all texts used by existing metrics."""
    texts = [
        named_text(item.name, item.description)
        for item in [
            *specification.features,
            *[c for b in specification.behaviours() for c in b.criteria],
            *specification.scenarios,
            *specification.personas,
        ]
    ]
    for version in BehaviourText:
        texts.extend(behaviour_texts(specification, version).values())
    return list(dict.fromkeys(texts))


def resolve_specification(path: Path) -> Path:
    """Accept a YAML file or a folder containing exactly one YAML file."""
    if path.is_dir():
        candidates = sorted([*path.glob("*.yaml"), *path.glob("*.yml")])
        if len(candidates) != 1:
            raise ValueError(
                f"Expected one specification YAML in {path}; supply its file path."
            )
        path = candidates[0]
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.resolve()


def read_specification(path: Path) -> Specification:
    return Specification.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    )


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TextEmbedding(BaseModel):
    text: str
    vector: list[float] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_vector(self) -> Self:
        if not all(math.isfinite(value) for value in self.vector):
            raise ValueError("Embedding values must be finite.")
        norm = sum(value * value for value in self.vector)
        if not math.isfinite(norm) or norm <= 0:
            raise ValueError("Embedding norm must be finite and positive.")
        return self


class EmbeddingCache(BaseModel):
    schema_version: Literal[1] = 1
    model: str
    endpoint_hash: str
    behaviours: dict[BehaviourText, dict[str, str]] = Field(default_factory=dict)
    entries: dict[str, TextEmbedding] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_entries(self) -> Self:
        if any(key != text_hash(item.text) for key, item in self.entries.items()):
            raise ValueError("Embedding text does not match its hash.")
        if len({len(item.vector) for item in self.entries.values()}) > 1:
            raise ValueError("Embedding dimensions must agree within a cache.")
        return self


class TextEmbedder(Protocol):
    """One independent vector per input text."""

    model: str
    endpoint_hash: str

    def embed(self, text: str) -> list[float]: ...


class GatewayEmbedder:
    """Create the API client only when a text is missing from the cache.

    The model and the gateway are the embeddings role (`EMBEDDING_*`, then `OPENAI_*`).
    """

    def __init__(self) -> None:
        self._settings = resolve_role(ModelRole.EMBEDDINGS, os.environ)
        self.model = self._settings.model
        self.base_url = (self._settings.base_url or "").rstrip("/")
        self.endpoint_hash = text_hash(self.base_url) if self.base_url else ""
        self._client: OpenAI | None = None

    def embed(self, text: str) -> list[float]:
        if self._client is None:
            if not self._settings.configured:
                names = " or ".join(ROLES[ModelRole.EMBEDDINGS].key_vars)
                raise ValueError(
                    f"Missing embeddings require {names}. See docs/guide/models.md."
                )
            self._client = OpenAI(
                base_url=self.base_url or None,
                api_key=self._settings.api_key,
                timeout=60,
                max_retries=2,
            )
        # This gateway combines multiple texts into one vector for Gemini embedding 2.
        response = self._client.embeddings.create(model=self.model, input=text)
        if len(response.data) != 1:
            raise ValueError("Expected one vector for one embedding input.")
        return response.data[0].embedding


def save_cache(path: Path, cache: EmbeddingCache) -> None:
    """Replace a complete JSON file without exposing a partial write."""
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(cache.model_dump_json(indent=2) + "\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@dataclass
class EmbeddedSpecification:
    path: Path
    specification: Specification
    cache: EmbeddingCache


def ensure_embeddings(
    path: Path, *, embedder: TextEmbedder | None = None, include_metrics: bool = False
) -> EmbeddedSpecification:
    """Reuse valid entries and embed missing text for either specification role."""
    path = resolve_specification(path)
    specification = read_specification(path)
    provider = embedder or GatewayEmbedder()
    cache_path = path.with_suffix(".embeddings.json")
    cache = (
        EmbeddingCache.model_validate_json(cache_path.read_text(encoding="utf-8"))
        if cache_path.exists()
        else EmbeddingCache(model=provider.model, endpoint_hash=provider.endpoint_hash)
    )
    if cache.model != provider.model or (
        provider.endpoint_hash and cache.endpoint_hash != provider.endpoint_hash
    ):
        cache = EmbeddingCache(
            model=provider.model, endpoint_hash=provider.endpoint_hash
        )
    current = {text_hash(text): text for text in specification_texts(specification)}
    cache.behaviours = {
        version: {
            identifier: text_hash(text)
            for identifier, text in behaviour_texts(specification, version).items()
        }
        for version in BehaviourText
    }
    required = (
        current
        if include_metrics
        else {
            text_hash(text): text
            for version in BehaviourText
            for text in behaviour_texts(specification, version).values()
        }
    )
    cache.entries = {key: item for key, item in cache.entries.items() if key in current}
    try:
        for key, text in required.items():
            if key in cache.entries:
                continue
            entry = TextEmbedding(text=text, vector=provider.embed(text))
            if cache.entries and len(entry.vector) != len(
                next(iter(cache.entries.values())).vector
            ):
                raise ValueError(
                    "The provider changed embedding dimensions; rebuild this cache."
                )
            cache.entries[key] = entry
    finally:
        # Completed requests survive an interrupted run and can be reused on retry.
        save_cache(cache_path, cache)
    return EmbeddedSpecification(path, specification, cache)


class CachedSimilarity:
    """Calculate similarities locally, with no API fallback in the calculation."""

    def __init__(self, *caches: EmbeddingCache) -> None:
        if len({(cache.model, cache.endpoint_hash) for cache in caches}) > 1:
            raise ValueError(
                "Specifications must use the same embedding model and endpoint."
            )
        self.entries = {
            key: item for cache in caches for key, item in cache.entries.items()
        }
        if (
            len(
                {
                    len(item.vector)
                    for cache in caches
                    for item in cache.entries.values()
                }
            )
            > 1
        ):
            raise ValueError("Specifications must use the same embedding dimensions.")

    def matrix(self, left: list[str], right: list[str]) -> list[list[float]]:
        return [
            [
                max(
                    0.0,
                    min(
                        1.0,
                        cosine(
                            self.entries[text_hash(a)].vector,
                            self.entries[text_hash(b)].vector,
                        ),
                    ),
                )
                for b in right
            ]
            for a in left
        ]


def main(path: Path) -> None:
    """Save embeddings beside the YAML file in PATH."""
    from metis.core.console import console

    embedded = ensure_embeddings(path)
    console.print(f"Saved: {embedded.path.with_suffix('.embeddings.json')}")


if __name__ == "__main__":
    import typer

    typer.run(main)
