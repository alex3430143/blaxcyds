import pytest

from blaxcy.body import Body, DryRunBackend, SystemBackend
from blaxcy.models import Action, ActionKind
from blaxcy.policy import Policy
from blaxcy.tools import FilesystemTool, TerminalTool


@pytest.fixture
def body(policy: Policy) -> Body:
    return Body(DryRunBackend(), policy)


def test_terminal_tool_runs_safe_command(body: Body):
    result = TerminalTool(body).run("echo hello")
    assert result.ok
    assert result.output["simulated"] is True


def test_terminal_tool_refuses_destructive_command(body: Body):
    result = TerminalTool(body).run("rm -rf /")
    assert not result.ok
    assert "destructive" in (result.error or "").lower()


def test_terminal_tool_refuses_auth_boundary(body: Body):
    result = TerminalTool(body).run("sudo reboot")
    assert not result.ok


def test_terminal_tool_rejects_empty_command(body: Body):
    assert not TerminalTool(body).run("   ").ok


def test_filesystem_tool_write_and_read_simulated(body: Body, tmp_path):
    target = tmp_path / "note.txt"
    assert FilesystemTool(body).write(str(target), "hi").ok
    assert not target.exists()  # dry-run: nothing really written


def test_system_backend_confines_writes(tmp_path):
    import os

    backend = SystemBackend(allowed_write_roots=[str(tmp_path)])
    inside = tmp_path / "ok.txt"
    out = backend.perform(Action(kind=ActionKind.FS_WRITE,
                                 params={"path": str(inside), "content": "hello"}))
    assert out["bytes"] == 5
    assert inside.read_text() == "hello"

    outside = os.path.join(os.sep, "etc", "blaxcy_should_not_write.txt")
    with pytest.raises(PermissionError):
        backend.perform(Action(kind=ActionKind.FS_WRITE,
                               params={"path": outside, "content": "nope"}))


def test_system_backend_terminal_real(tmp_path):
    backend = SystemBackend(allowed_write_roots=[str(tmp_path)])
    out = backend.perform(Action(kind=ActionKind.TERMINAL_RUN, params={"command": "echo blaxcy"}))
    assert out["returncode"] == 0
    assert "blaxcy" in out["stdout"]
