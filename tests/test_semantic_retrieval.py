"""Phase 3C tests — the retrieval engine: eligibility, RRF, priority, fallback."""

from pathlib import Path

from cogos.benchmark import build_benchmark_dataset
from cogos.paths import Paths
from cogos.retrieve import (
    RetrievalRequest,
    eligibility_filter,
    retrieve_ranked,
    rrf,
)
from cogos.store import SearchHit, Store
from cogos.user import UserLayer

from test_embedding import FakeProvider


def _ws(tmp_path: Path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    user = UserLayer(root=tmp_path / "user")
    user.ensure()
    store = Store(paths.cache / "cognitive.db")
    return paths, user, store


def test_rrf_formula():
    assert abs(rrf(1, None) - 1 / 61) < 1e-5
    both = rrf(1, 1)
    assert abs(both - 2 / 61) < 1e-5
    assert rrf(None, None) == 0.0


def test_keyword_mode_works_without_provider(tmp_path):
    paths, user, store = _ws(tmp_path)
    build_benchmark_dataset(store)
    req = RetrievalRequest(task_text="写一个销售 SQL", domain="sql")
    items = retrieve_ranked(store, None, req, mode="keyword")
    assert items, "keyword mode must work with no provider"
    ids = [i.memory_id for i in items]
    assert "R-SQL-001" in ids
    assert all(i.retrieval_method == "keyword" for i in items)


def test_auto_mode_falls_back_to_keyword_without_provider(tmp_path):
    paths, user, store = _ws(tmp_path)
    build_benchmark_dataset(store)
    req = RetrievalRequest(task_text="写一个销售 SQL", domain="sql")
    items = retrieve_ranked(store, None, req, mode="auto")
    assert items and all(i.retrieval_method == "keyword" for i in items)


def test_hybrid_mode_with_provider_uses_both_channels(tmp_path):
    paths, user, store = _ws(tmp_path)
    build_benchmark_dataset(store)
    provider = FakeProvider()
    req = RetrievalRequest(task_text="写一个销售 SQL", domain="sql")
    # FakeProvider vectors are sparse; the similarity floor is relaxed for
    # mechanism testing (the floor itself is tested separately)
    items = retrieve_ranked(store, provider, req, mode="hybrid", min_similarity=0.0)
    assert items
    methods = {i.retrieval_method for i in items}
    assert "hybrid" in methods, "overlapping hits must be fused via RRF"
    for i in items:
        assert i.why_retrieved, "every item must carry why_retrieved"


def test_semantic_mode_returns_similarity_ranked(tmp_path):
    paths, user, store = _ws(tmp_path)
    build_benchmark_dataset(store)
    provider = FakeProvider()
    req = RetrievalRequest(task_text="写一个销售 SQL", domain="sql")
    items = retrieve_ranked(store, provider, req, mode="semantic", min_similarity=0.0)
    assert items
    assert all(i.retrieval_method == "semantic" for i in items)
    assert all(i.semantic_rank is not None and i.similarity is not None for i in items)
    # semantic_rank is the similarity order (1 = highest similarity); the
    # final list may be re-ordered by priority, so assert rank↔similarity
    # consistency instead of list order
    by_rank = sorted(items, key=lambda i: i.semantic_rank or 999)
    sims = [i.similarity for i in by_rank]
    assert sims == sorted(sims, reverse=True), "semantic rank must follow similarity"


def test_eligibility_excludes_conflicted(tmp_path):
    paths, user, store = _ws(tmp_path)
    build_benchmark_dataset(store)
    store.upsert_entity(
        "R-CONF-X", "memory", subtype="rule", domain="sql",
        content="SQL 必须使用 CTE", payload={}, status="conflicted",
    )
    store.add_fts("R-CONF-X", "memory", "rule", "sql", "SQL 必须使用 CTE")
    hits = store.search("SQL CTE", types=("memory",))
    eligible = eligibility_filter(store, RetrievalRequest(task_text="SQL"), hits)
    assert not any(h.ent_id == "R-CONF-X" for h in eligible)


def test_similarity_floor_blocks_weak_hits(tmp_path):
    """§24: semantic similarity alone (below the floor) never qualifies."""
    paths, user, store = _ws(tmp_path)
    build_benchmark_dataset(store)
    provider = FakeProvider()
    req = RetrievalRequest(task_text="写一个销售 SQL", domain="sql")
    items = retrieve_ranked(store, provider, req, mode="hybrid", min_similarity=0.99)
    # at a near-perfect floor, no semantic hit survives — hybrid degrades to
    # keyword-only results (never injects weak-similarity noise)
    assert all(i.semantic_rank is None for i in items)


def test_priority_scope_match_outranks_global(tmp_path):
    """Contract §3③: project-scoped cognition beats global in its project."""
    paths, user, store = _ws(tmp_path)
    build_benchmark_dataset(store)
    provider = FakeProvider()
    req = RetrievalRequest(task_text="帮我写一个销售查询 SQL", domain="sql",
                           scope="project", scope_id="bp")
    items = retrieve_ranked(store, provider, req, mode="hybrid")
    ids = [i.memory_id for i in items]
    assert "P-PROJ-BP" in ids
    pos_proj = ids.index("P-PROJ-BP")
    if "P-SQL-CTE" in ids:
        assert pos_proj < ids.index("P-SQL-CTE"), "project-scoped must outrank global CTE preference"
    bp_item = next(i for i in items if i.memory_id == "P-PROJ-BP")
    assert bp_item.scope_match


def test_confidence_does_not_override_relevance(tmp_path):
    """§20: a high-confidence irrelevant memory must not displace a relevant one."""
    paths, user, store = _ws(tmp_path)
    build_benchmark_dataset(store)
    # irrelevant high-confidence memory in sql domain (would be a strong
    # priority item if relevance were ignored)
    store.upsert_entity(
        "R-HICONF", "memory", subtype="rule", domain="sql",
        content="数据库备份策略：每天凌晨全量备份", payload={"source": "user_statement"},
        status="confirmed", confidence=0.99, user_confirmed=True,
    )
    store.add_fts("R-HICONF", "memory", "rule", "sql", "数据库备份策略：每天凌晨全量备份")
    provider = FakeProvider()
    req = RetrievalRequest(task_text="帮我写一个销售查询 SQL", domain="sql")
    items = retrieve_ranked(store, provider, req, mode="hybrid")
    ids = [i.memory_id for i in items]
    assert "R-SQL-001" in ids, "relevant rule must be retrieved"
    # the backup rule is irrelevant to sales queries — relevance keeps it out
    # of the pool even though confidence=0.99
    assert "R-HICONF" not in ids or ids.index("R-SQL-001") < ids.index("R-HICONF")


def test_unrelated_memory_not_retrieved(tmp_path):
    """§24 negative sample: cat-food plan must not surface for SQL tasks."""
    paths, user, store = _ws(tmp_path)
    build_benchmark_dataset(store)
    provider = FakeProvider()
    req = RetrievalRequest(task_text="帮我写一个销售 SQL", domain="sql")
    items = retrieve_ranked(store, provider, req, mode="hybrid")
    ids = [i.memory_id for i in items]
    assert "P-PET-001" not in ids, "pet-domain memory must not leak into SQL retrieval"


def test_vectors_cache_write_through(tmp_path):
    """Embedded vectors persist in the store (derived data)."""
    paths, user, store = _ws(tmp_path)
    build_benchmark_dataset(store)
    provider = FakeProvider()
    req = RetrievalRequest(task_text="写一个销售 SQL", domain="sql")
    retrieve_ranked(store, provider, req, mode="semantic")
    vec = store.get_vector("R-SQL-001")
    assert vec is not None and vec[0] == provider.name


def test_model_mismatch_marked_stale(tmp_path):
    paths, user, store = _ws(tmp_path)
    build_benchmark_dataset(store)
    provider = FakeProvider()
    req = RetrievalRequest(task_text="写一个销售 SQL", domain="sql")
    retrieve_ranked(store, provider, req, mode="semantic")
    # a different model name → everything is stale, nothing is silently mixed
    stale = store.stale_vector_ids("other-model-64")
    assert "R-SQL-001" in stale
