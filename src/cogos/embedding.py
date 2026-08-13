"""Embedding providers — the semantic channel of retrieval (Phase 3C).

Contract (docs/cognitive-retrieval.md §5):

* EmbeddingProvider protocol: name + dimension + embed(texts) -> vectors.
* Local first (offline, CPU, nothing leaves the machine); remote only when
  explicitly configured; any failure degrades to keyword-only retrieval.
* Embeddings are DERIVED data — never canonical, always rebuildable.

Provider resolution chain (get_provider):
    COGOS_EMBEDDING=remote → remote provider (if configured) else local
    COGOS_EMBEDDING=none   → None (keyword-only, explicit)
    default                → local provider if importable, else None
"""

from __future__ import annotations

import os
from typing import Protocol


class EmbeddingProvider(Protocol):
    name: str
    dimension: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class NullEmbeddingProvider:
    """Explicit 'no embeddings' marker — keyword-only retrieval."""

    name = "none"
    dimension = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("NullEmbeddingProvider cannot embed")


_local_provider: EmbeddingProvider | None = None
_local_failed = False


def load_local_provider() -> EmbeddingProvider | None:
    """Lazy-load the local bge-small-zh provider (fastembed, CPU, offline).

    Caches the singleton; a failed import is remembered so we don't retry
    the heavy import on every query.
    """
    global _local_provider, _local_failed
    if _local_provider is not None:
        return _local_provider
    if _local_failed:
        return None
    try:
        from fastembed import TextEmbedding

        model = TextEmbedding("BAAI/bge-small-zh-v1.5", threads=2)
        # verify with a cheap probe so dimension/model name are real
        probe = list(model.embed(["你好"]))
        if not probe or len(probe[0]) == 0:  # numpy arrays: never use truthiness
            raise RuntimeError("fastembed returned empty vectors")
        dim = len(probe[0])

        class _FastEmbedProvider:
            name = "bge-small-zh-v1.5"
            dimension = dim

            def embed(self, texts: list[str]) -> list[list[float]]:
                # fastembed returns numpy arrays; convert to plain lists
                return [v.tolist() for v in model.embed(texts)]

        _local_provider = _FastEmbedProvider()
        return _local_provider
    except Exception:
        _local_failed = True
        return None


def load_remote_provider() -> EmbeddingProvider | None:
    """Remote embedding — ONLY when explicitly configured (never automatic).

    Env contract (nothing is uploaded unless all three are set):
      COGOS_EMBEDDING_REMOTE_BASE_URL  (OpenAI-compatible /v1/embeddings)
      COGOS_EMBEDDING_REMOTE_API_KEY
      COGOS_EMBEDDING_REMOTE_MODEL
    """
    base = os.environ.get("COGOS_EMBEDDING_REMOTE_BASE_URL", "")
    key = os.environ.get("COGOS_EMBEDDING_REMOTE_API_KEY", "")
    model = os.environ.get("COGOS_EMBEDDING_REMOTE_MODEL", "")
    if not (base and key and model):
        return None
    try:
        import urllib.request
        import json as _json

        class _RemoteProvider:
            name = f"remote:{model}"
            dimension = 0  # learned on first call

            def embed(self, texts: list[str]) -> list[list[float]]:
                req = urllib.request.Request(
                    base.rstrip("/") + "/embeddings",
                    data=_json.dumps({"model": model, "input": texts}).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {key}",
                    },
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = _json.loads(resp.read().decode("utf-8"))
                vecs = [d["embedding"] for d in data["data"]]
                if vecs and self.dimension == 0:
                    self.dimension = len(vecs[0])
                return vecs

        return _RemoteProvider()
    except Exception:
        return None


def get_provider() -> EmbeddingProvider | None:
    """Resolution chain (contract §5): explicit none → remote(configured)
    → local → keyword-only."""
    mode = os.environ.get("COGOS_EMBEDDING", "").strip().lower()
    if mode == "none":
        return None
    if mode == "remote":
        return load_remote_provider() or load_local_provider()
    return load_local_provider()


# ---------------------------------------------------------------------------
# vector (de)serialization — float32 little-endian, stored as SQLite BLOB
# ---------------------------------------------------------------------------


def pack_vector(vec: list[float]) -> bytes:
    import struct

    return struct.pack(f"<{len(vec)}f", *vec)


def unpack_vector(blob: bytes) -> list[float]:
    import struct

    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity; 0.0 on any degenerate input."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def content_hash(content: str) -> str:
    import hashlib

    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
