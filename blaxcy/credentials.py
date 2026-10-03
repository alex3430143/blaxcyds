"""Secure credential storage.

Credentials (API keys, tokens) must never live in source code, plain
configuration, `.build-state/`, or logs. This module provides a `CredentialStore`
that uses, in order of preference:

1. the OS keyring (python-`keyring` to Secret Service / KWallet),
2. `secret-tool` (libsecret CLI),
3. `cryptography`-encrypted file in the runtime directory (0600) — a genuinely
   encrypted fallback that still never stores plaintext on disk,
4. a 0600 plaintext file as a last resort, clearly flagged as degraded.

The chosen backend is always reported via `backend_name()` so callers can be
honest about the security level in force.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

SERVICE = "blaxcy"


def _have_keyring() -> bool:
    try:
        import keyring  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _have_secret_tool() -> bool:
    return bool(shutil.which("secret-tool"))


def _have_cryptography() -> bool:
    try:
        import cryptography  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


class CredentialStore:
    def __init__(self, file_path: str | os.PathLike[str] | None = None) -> None:
        self.file_path = Path(file_path) if file_path else Path(
            os.environ.get("BLAXCY_HOME", Path.home() / ".local" / "share" / "blaxcy")) / "credentials.enc"

    # backend selection -----------------------------------------------------
    def backend_name(self) -> str:
        if _have_keyring():
            return "keyring"
        if _have_secret_tool():
            return "secret-tool"
        if _have_cryptography():
            return "encrypted-file"
        return "plaintext-file (DEGRADED)"

    # public API ------------------------------------------------------------
    def set(self, key: str, value: str) -> str:
        backend = self.backend_name()
        if backend == "keyring":
            import keyring

            keyring.set_password(SERVICE, key, value)
        elif backend == "secret-tool":
            subprocess.run(["secret-tool", "store", "--label", f"blaxcy:{key}",
                            "service", SERVICE, "key", key],
                           input=value.encode(), check=True)
        else:
            data = self._read_file()
            data[key] = self._protect(value)
            self._write_file(data)
        return backend

    def get(self, key: str) -> str | None:
        backend = self.backend_name()
        if backend == "keyring":
            import keyring

            return keyring.get_password(SERVICE, key)
        if backend == "secret-tool":
            r = subprocess.run(["secret-tool", "lookup", "service", SERVICE, "key", key],
                               capture_output=True, text=True)
            return r.stdout.rstrip("\n") if r.returncode == 0 and r.stdout else None
        data = self._read_file()
        if key in data:
            return self._unprotect(data[key])
        return None

    def delete(self, key: str) -> bool:
        backend = self.backend_name()
        if backend == "keyring":
            import keyring

            try:
                keyring.delete_password(SERVICE, key)
                return True
            except Exception:  # noqa: BLE001
                return False
        if backend == "secret-tool":
            r = subprocess.run(["secret-tool", "clear", "service", SERVICE, "key", key],
                               capture_output=True)
            return r.returncode == 0
        data = self._read_file()
        existed = key in data
        data.pop(key, None)
        self._write_file(data)
        return existed

    def list_keys(self) -> list[str]:
        if self.backend_name() == "keyring":
            return []  # keyring has no portable enumeration
        return sorted(self._read_file().keys())

    # encrypted / plaintext file backend -----------------------------------
    def _read_file(self) -> dict[str, Any]:
        if not self.file_path.exists():
            return {}
        try:
            return json.loads(self.file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_file(self, data: dict[str, Any]) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file_path.with_suffix(self.file_path.suffix + ".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.file_path)

    def _machine_key(self) -> bytes:
        # Derive a machine-local key from the user id + home path + a stored salt.
        salt_path = self.file_path.with_suffix(".salt")
        if not salt_path.exists():
            salt_path.parent.mkdir(parents=True, exist_ok=True)
            salt_path.write_bytes(os.urandom(16))
            try:
                os.chmod(salt_path, 0o600)
            except OSError:
                pass
        salt = salt_path.read_bytes()
        material = f"{os.getuid()}::{Path.home()}::blaxcy".encode()
        import hashlib

        return hashlib.pbkdf2_hmac("sha256", material, salt, 200_000)

    def _protect(self, value: str) -> str:
        if not _have_cryptography():
            return "plain:" + value
        from cryptography.fernet import Fernet
        import hashlib

        key = base64.urlsafe_b64encode(hashlib.sha256(self._machine_key()).digest())
        return "enc:" + Fernet(key).encrypt(value.encode()).decode()

    def _unprotect(self, token: str) -> str:
        if token.startswith("plain:"):
            return token[len("plain:"):]
        if token.startswith("enc:"):
            from cryptography.fernet import Fernet
            import hashlib

            key = base64.urlsafe_b64encode(hashlib.sha256(self._machine_key()).digest())
            return Fernet(key).decrypt(token[len("enc:"):].encode()).decode()
        return token

    # app-credential helper -------------------------------------------------
    def provider_key(self, provider: str) -> str | None:
        """Load a provider API key, preferring the environment over the store."""
        env_names = {
            "openai": "BLAXCY_OPENAI_API_KEY",
            "anthropic": "BLAXCY_ANTHROPIC_API_KEY",
        }
        env = env_names.get(provider)
        if env and os.environ.get(env):
            return os.environ[env]
        return self.get(f"{provider}_api_key")

    def status(self) -> dict[str, Any]:
        return {
            "backend": self.backend_name(),
            "encrypted": self.backend_name() in ("encrypted-file", "keyring", "secret-tool"),
            "path": str(self.file_path) if "file" in self.backend_name() else None,
        }
