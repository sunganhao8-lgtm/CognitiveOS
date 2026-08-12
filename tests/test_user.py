"""测试 用于 cogos.user — UserLayer layout."""

from pathlib import Path

from cogos.user import UserLayer


def test_user_layer_paths():
    user = UserLayer(root=Path("/tmp/u").resolve())
    assert user.preferences.name == "preferences.md"
    assert user.style.name == "style.md"
    assert user.projects.name == "projects"
    assert user.experience.name == "experience"
    assert user.cognitive.name == "cognitive"


def test_ensure_creates_dirs_without_raising(tmp_path):
    user = UserLayer(root=tmp_path / "user")
    user.ensure()
    assert (tmp_path / "user" / "projects").is_dir()
    assert (tmp_path / "user" / "experience").is_dir()
    assert (tmp_path / "user" / "cognitive").is_dir()