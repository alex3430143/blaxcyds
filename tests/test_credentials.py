"""Tests for secure credential storage (requirement L3).

The OS keyring / libsecret backends are force-disabled so tests exercise the
encrypted-file path deterministically and never touch a real keyring.
"""

from __future__ import annotations

from blaxcy import credentials
from blaxcy.credentials import CredentialStore


def _file_backend_store(tmp_path, monkeypatch) -> CredentialStore:
    monkeypatch.setattr(credentials, "_have_keyring", lambda: False)
    monkeypatch.setattr(credentials, "_have_secret_tool", lambda: False)
    monkeypatch.setattr(credentials, "_have_cryptography", lambda: True)
    return CredentialStore(tmp_path / "creds.enc")


def test_backend_is_encrypted_file(tmp_path, monkeypatch):
    store = _file_backend_store(tmp_path, monkeypatch)
    assert store.backend_name() == "encrypted-file"
    status = store.status()
    assert status["encrypted"] is True
    assert status["path"] == str(store.file_path)


def test_set_get_delete_roundtrip(tmp_path, monkeypatch):
    store = _file_backend_store(tmp_path, monkeypatch)
    store.set("openai_api_key", "sk-secret")
    assert store.get("openai_api_key") == "sk-secret"
    assert "openai_api_key" in store.list_keys()
    assert store.delete("openai_api_key") is True
    assert store.get("openai_api_key") is None
    assert store.delete("openai_api_key") is False


def test_secret_is_not_stored_in_plaintext(tmp_path, monkeypatch):
    store = _file_backend_store(tmp_path, monkeypatch)
    store.set("token", "super-secret-value")
    raw = store.file_path.read_bytes()
    assert b"super-secret-value" not in raw
    assert raw.startswith(b"{")


def test_file_permissions_are_private(tmp_path, monkeypatch):
    store = _file_backend_store(tmp_path, monkeypatch)
    store.set("k", "v")
    assert (store.file_path.stat().st_mode & 0o777) == 0o600


def test_provider_key_prefers_environment(tmp_path, monkeypatch):
    store = _file_backend_store(tmp_path, monkeypatch)
    store.set("openai_api_key", "from-store")
    monkeypatch.setenv("BLAXCY_OPENAI_API_KEY", "from-env")
    assert store.provider_key("openai") == "from-env"
    monkeypatch.delenv("BLAXCY_OPENAI_API_KEY", raising=False)
    assert store.provider_key("openai") == "from-store"


def test_plaintext_fallback_is_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(credentials, "_have_keyring", lambda: False)
    monkeypatch.setattr(credentials, "_have_secret_tool", lambda: False)
    monkeypatch.setattr(credentials, "_have_cryptography", lambda: False)
    store = CredentialStore(tmp_path / "c.enc")
    assert "DEGRADED" in store.backend_name()
    assert store.status()["encrypted"] is False
    store.set("k", "v")
    assert store.get("k") == "v"
