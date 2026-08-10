"""Tests for cogos.paths — pure data layout, no IO required."""

from pathlib import Path

from cogos.paths import Paths


def test_default_paths_are_relative_to_root():
    p = Paths(root=Path("/tmp/cogos-test").resolve())
    assert p.knowledge == Path("/tmp/cogos-test/knowledge").resolve()
    assert p.sources == Path("/tmp/cogos-test/knowledge/sources").resolve()
    assert p.normalized == Path("/tmp/cogos-test/knowledge/normalized").resolve()
    assert p.wiki == Path("/tmp/cogos-test/knowledge/wiki").resolve()
    assert p.dashboard_index == Path("/tmp/cogos-test/index.html").resolve()
    assert p.cache == Path("/tmp/cogos-test/.cogos").resolve()


def test_ensure_creates_all_required_dirs(tmp_path):
    p = Paths(root=tmp_path)
    p.ensure()
    for d in (p.knowledge, p.sources, p.normalized, p.wiki, p.cache):
        assert d.is_dir(), f"missing: {d}"


def test_ensure_is_idempotent(tmp_path):
    p = Paths(root=tmp_path)
    p.ensure()
    p.ensure()  # second call must not raise
    assert p.knowledge.is_dir()