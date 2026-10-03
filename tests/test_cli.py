import json

from blaxcy.cli import main


def test_doctor_json(capsys):
    code = main(["doctor", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code in (0, 1)
    assert "checks" in out
    names = {c["name"] for c in out["checks"]}
    assert {"python", "display", "models", "state_store"} <= names


def test_state_json(capsys):
    code = main(["state", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert "build_state_files" in out
    assert out["build_state_files"]["STATE.md"] is True


def test_models_command(capsys):
    code = main(["models", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert any(row["name"] == "offline-deterministic" for row in out)


def test_resume_command_reports_mode(capsys):
    code = main(["resume", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["mode"] in ("first_execution", "recovery")
    assert out["next_action"]


def test_services_lists_every_component(capsys):
    code = main(["services", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    names = {row["name"] for row in out}
    assert {"eye", "memory", "brain"} <= names
    for row in out:
        assert row["mode"] in ("split", "in-process")
        assert "running" in row and "pid" in row


def test_doctor_reports_the_service_split(capsys):
    code = main(["doctor", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code in (0, 1)
    checks = {c["name"] for c in out["checks"]}
    assert "services" in checks
    assert "split" in out


def test_version_action(capsys):
    try:
        main(["--version"])
    except SystemExit:
        pass
    assert "blaxcy" in capsys.readouterr().out
