"""Phase 3C tests — embedding providers, vector (de)serialization, cosine."""

import math
import os

from cogos import embedding as emb


def test_pack_unpack_roundtrip():
    vec = [0.1, -0.25, 0.5, 1.0]
    blob = emb.pack_vector(vec)
    got = emb.unpack_vector(blob)
    for a, b in zip(got, vec):
        assert abs(a - b) < 1e-6  # float32 precision


def test_cosine_identity_and_orthogonal():
    a = [1.0, 0.0, 0.0]
    assert abs(emb.cosine(a, a) - 1.0) < 1e-9
    assert abs(emb.cosine(a, [0.0, 1.0, 0.0])) < 1e-9
    assert emb.cosine([], [1.0]) == 0.0  # degenerate
    assert emb.cosine([1.0], [1.0, 2.0]) == 0.0  # dim mismatch


def test_content_hash_stable_and_sensitive():
    h1 = emb.content_hash("SQL 不用 SELECT *")
    assert h1 == emb.content_hash("SQL 不用 SELECT *")
    assert h1 != emb.content_hash("SQL 不用 SELECT *。")
    assert len(h1) == 16


def test_null_provider_refuses_to_embed():
    p = emb.NullEmbeddingProvider()
    assert p.name == "none" and p.dimension == 0
    try:
        p.embed(["x"])
        raise AssertionError("should have raised")
    except RuntimeError:
        pass


def test_get_provider_respects_none_mode(monkeypatch):
    monkeypatch.setenv("COGOS_EMBEDDING", "none")
    assert emb.get_provider() is None


def test_remote_provider_requires_full_config(monkeypatch):
    monkeypatch.setenv("COGOS_EMBEDDING", "remote")
    monkeypatch.delenv("COGOS_EMBEDDING_REMOTE_BASE_URL", raising=False)
    monkeypatch.delenv("COGOS_EMBEDDING_REMOTE_API_KEY", raising=False)
    monkeypatch.delenv("COGOS_EMBEDDING_REMOTE_MODEL", raising=False)
    assert emb.load_remote_provider() is None, "partial config must not enable remote"


class FakeProvider:
    """Deterministic character-feature vectors — used across retrieval tests."""

    name = "fake-64"
    dimension = 64

    def embed(self, texts):
        import hashlib
        import re

        out = []
        for text in texts:
            vec = [0.0] * 64
            tokens = re.findall(r"[a-zA-Z0-9_]+", text.lower())
            zh = re.sub(r"[^\u4e00-\u9fff]", "", text)
            tokens += [zh[i:i + 2] for i in range(max(0, len(zh) - 1))]
            for t in set(tokens):
                h = int(hashlib.md5(t.encode("utf-8")).hexdigest()[:8], 16)
                vec[h % 64] += 1.0
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / norm for x in vec])
        return out
