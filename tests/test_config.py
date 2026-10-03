"""Tests for the project-local `.env` loader (provider keys without exporting)."""

from __future__ import annotations

import os

from blaxcy.config import load_env_file


def test_missing_file_is_a_noop(tmp_path):
    assert load_env_file(tmp_path / "does-not-exist.env") == 0


def test_parses_values_comments_and_quotes(tmp_path, monkeypatch):
    for name in ("BLAXCY_TEST_PLAIN", "BLAXCY_TEST_SINGLE", "BLAXCY_TEST_DOUBLE"):
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "# comment, ignored\n"
        "\n"
        "BLAXCY_TEST_PLAIN=abc123\n"
        "export BLAXCY_TEST_SINGLE='quoted value'\n"
        'BLAXCY_TEST_DOUBLE="double value"\n'
        "NOT_A_PAIR\n",
        encoding="utf-8",
    )

    assert load_env_file(env) == 3
    assert os.environ["BLAXCY_TEST_PLAIN"] == "abc123"
    assert os.environ["BLAXCY_TEST_SINGLE"] == "quoted value"
    assert os.environ["BLAXCY_TEST_DOUBLE"] == "double value"


def test_env_file_configures_a_remote_provider(tmp_path, monkeypatch):
    """Integration: a `.env` at the project root makes a remote provider available
    in the default registry, without the key ever being exported manually."""
    import blaxcy.config as config
    from blaxcy.brain.registry import default_registry

    for var in ("BLAXCY_OPENAI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / ".env").write_text("BLAXCY_OPENAI_API_KEY=sk-from-dotenv\n",
                                   encoding="utf-8")
    monkeypatch.setattr(config, "project_root", lambda: tmp_path)

    registry = default_registry()
    assert registry.spec("openai") is not None
    assert registry.provider("openai").is_available() is True
    assert os.environ["BLAXCY_OPENAI_API_KEY"] == "sk-from-dotenv"
    monkeypatch.delenv("BLAXCY_OPENAI_API_KEY", raising=False)


def test_parse_split_filters_unknown_and_dedupes():
    from blaxcy.config import ALL_COMPONENTS, parse_split

    assert parse_split(None) == ()
    assert parse_split("") == ()
    assert parse_split("eye,memory,eye") == ("eye", "memory")
    assert parse_split("bogus") == ()          # a typo degrades to in-process
    assert parse_split("all") == ALL_COMPONENTS
    assert parse_split("full") == ALL_COMPONENTS


def test_load_settings_reads_split_and_root(tmp_path, monkeypatch):
    from blaxcy.config import load_settings

    monkeypatch.setenv("BLAXCY_ROOT", str(tmp_path))
    monkeypatch.setenv("BLAXCY_SPLIT", "memory,brain")
    settings = load_settings()
    assert settings.root == tmp_path
    assert settings.split_components == ("memory", "brain")
    assert settings.runtime_dir == tmp_path / ".runtime"


def test_load_settings_defaults_to_all_in_process(tmp_path, monkeypatch):
    from blaxcy.config import load_settings

    monkeypatch.setenv("BLAXCY_ROOT", str(tmp_path))
    monkeypatch.delenv("BLAXCY_SPLIT", raising=False)
    settings = load_settings()
    assert settings.split_components == ()
    assert settings.planner == "rules"


def test_existing_environment_wins_unless_overridden(tmp_path, monkeypatch):
    monkeypatch.setenv("BLAXCY_TEST_KEEP", "from-shell")
    env = tmp_path / ".env"
    env.write_text("BLAXCY_TEST_KEEP=from-file\n", encoding="utf-8")

    assert load_env_file(env) == 0
    assert os.environ["BLAXCY_TEST_KEEP"] == "from-shell"

    assert load_env_file(env, override=True) == 1
    assert os.environ["BLAXCY_TEST_KEEP"] == "from-file"
