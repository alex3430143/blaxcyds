"""Configuration and environment discovery.

Settings are read from environment variables (with safe defaults). The single
most important default is that **real input is disabled**: the Body will only
touch the real mouse/keyboard when both the environment gate is set and Policy
approves the specific action.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

REAL_INPUT_ENV = "BLAXCY_ENABLE_REAL_INPUT"
SPLIT_ENV = "BLAXCY_SPLIT"
ROOT_ENV = "BLAXCY_ROOT"
PLANNER_ENV = "BLAXCY_PLANNER"
_TRUTHY = {"1", "true", "yes", "on"}

# Every component that can run as its own supervised process. Order matters only
# for readability; the app starts them all the same way.
ALL_COMPONENTS = ("eye", "memory", "brain")


def _truthy(value: str | None) -> bool:
    return bool(value) and value.strip().lower() in _TRUTHY


def normalize_split(value: str | tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    """Normalize a split selection (string or sequence) into known components.

    ``all``/``full`` selects every splittable component. Unknown names are
    ignored rather than silently accepted, so a typo degrades to in-process
    (the safe default) instead of quietly doing nothing. This is the single
    place `BLAXCY_SPLIT`, `--split`, and programmatic callers are normalized, so
    `--split all` cannot silently mean "nothing".
    """
    if value is None:
        return ()
    if isinstance(value, str):
        names = [part.strip().lower() for part in value.split(",") if part.strip()]
    else:
        names = [str(part).strip().lower() for part in value if str(part).strip()]
    if any(name in {"all", "full"} for name in names):
        return ALL_COMPONENTS
    return tuple(dict.fromkeys(name for name in names if name in ALL_COMPONENTS))


def parse_split(value: str | None) -> tuple[str, ...]:
    """Parse `BLAXCY_SPLIT` into a de-duplicated tuple of components."""
    return normalize_split(value)


def project_root() -> Path:
    """Root of this project (the directory containing the `blaxcy` package)."""
    return Path(__file__).resolve().parent.parent


def load_env_file(path: str | os.PathLike[str] | None = None, *,
                  override: bool = False) -> int:
    """Load ``KEY=VALUE`` pairs from a project-local ``.env`` file.

    The file is gitignored (see `.gitignore`) and is the supported place for
    secrets such as provider API keys. **Real environment variables always win**
    unless ``override`` is true, so a shell/CI value is never clobbered. Supports
    blank lines, ``#`` comments, an optional ``export`` prefix and quoted values.
    Returns the number of variables that were set.
    """
    env_path = Path(path) if path is not None else (project_root() / ".env")
    if not env_path.exists():
        return 0
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    count = 0
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value
            count += 1
    return count


@dataclass
class Settings:
    root: Path = field(default_factory=project_root)
    display: str = ""
    session_type: str = ""
    real_input_enabled: bool = False
    persist_frames: bool = False
    frame_interval_s: float = 0.4
    max_risk: str = "medium"
    # Which components run as supervised subprocesses. Empty = all in-process.
    split_components: tuple[str, ...] = ()
    # Planner backend: "rules" (deterministic, default) or "model" (validated).
    planner: str = "rules"
    # paths
    runtime_dir: Path | None = None
    memory_path: Path | None = None
    log_path: Path | None = None
    state_dir: Path | None = None
    socket_path: Path | None = None
    build_state_dir: Path | None = None

    def __post_init__(self) -> None:
        self.runtime_dir = self.runtime_dir or (self.root / ".runtime")
        self.memory_path = self.memory_path or (self.runtime_dir / "memory.sqlite3")
        self.log_path = self.log_path or (self.runtime_dir / "blaxcy.jsonl")
        self.state_dir = self.state_dir or (self.runtime_dir / "state")
        self.socket_path = self.socket_path or (self.runtime_dir / "blaxcy.sock")
        self.build_state_dir = self.build_state_dir or (self.root / ".build-state")

    def ensure_dirs(self) -> None:
        for p in (self.runtime_dir, self.state_dir, self.runtime_dir / "logs"):
            Path(p).mkdir(parents=True, exist_ok=True)

    # secrets ---------------------------------------------------------------
    def ipc_secret(self) -> str:
        """Load or create the local IPC shared secret (mode 0600)."""
        self.ensure_dirs()
        path = Path(self.runtime_dir) / "ipc.secret"
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        secret = secrets.token_hex(32)
        path.write_text(secret, encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return secret


def load_settings(**overrides) -> Settings:
    load_env_file()
    env = os.environ
    root = Path(env[ROOT_ENV]).expanduser() if env.get(ROOT_ENV) else project_root()
    settings = Settings(
        root=root,
        display=env.get("DISPLAY", ""),
        session_type=env.get("XDG_SESSION_TYPE", ""),
        real_input_enabled=_truthy(env.get(REAL_INPUT_ENV)),
        persist_frames=_truthy(env.get("BLAXCY_PERSIST_FRAMES")),
        frame_interval_s=float(env.get("BLAXCY_FRAME_INTERVAL", "0.4")),
        max_risk=env.get("BLAXCY_MAX_RISK", "medium"),
        split_components=parse_split(env.get(SPLIT_ENV)),
        planner=env.get(PLANNER_ENV, "rules").strip().lower() or "rules",
    )
    for key, value in overrides.items():
        setattr(settings, key, value)
    settings.__post_init__()
    return settings
