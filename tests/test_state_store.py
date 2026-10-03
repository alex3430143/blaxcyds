import json

from blaxcy.state_store import StateStore


def test_set_get_and_atomic_write(tmp_state: StateStore):
    tmp_state.set("phase", "test")
    assert tmp_state.get("phase") == "test"
    assert tmp_state.path.exists()


def test_task_lifecycle_and_pending(tmp_state: StateStore):
    tmp_state.begin_task("t1", description="d", expected_result="e")
    assert any(t["task_id"] == "t1" for t in tmp_state.pending_tasks())
    assert tmp_state.finish_task("t1", status="success", note="done")
    assert tmp_state.pending_tasks() == []


def test_mark_interrupted_flags_running_tasks(tmp_state: StateStore):
    tmp_state.begin_task("t1")
    tmp_state.begin_task("t2")
    tmp_state.finish_task("t2", status="success")
    interrupted = tmp_state.mark_interrupted()
    assert interrupted == ["t1"]
    assert tmp_state.load()["tasks"][0]["status"] == "interrupted"


def test_checkpoint_and_last_checkpoint(tmp_state: StateStore):
    tmp_state.checkpoint("cp1", note="first", data={"k": "v"})
    tmp_state.checkpoint("cp2", note="second")
    last = tmp_state.last_checkpoint()
    assert last["name"] == "cp2"
    assert tmp_state.get("k") == "v"
    assert len(tmp_state.history()) == 2


def test_corruption_recovered_from_backup(tmp_state: StateStore):
    tmp_state.set("a", 1)
    tmp_state.set("a", 2)  # second write leaves a .bak of the first
    tmp_state.path.write_text("{ this is not json", encoding="utf-8")

    store = StateStore(tmp_state.path)
    data = store.load()
    assert store.recovered_from_corruption
    assert data["data"].get("a") == 1


def test_corruption_without_backup_resets_with_notice(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("not json at all", encoding="utf-8")
    store = StateStore(path)
    data = store.load()
    assert store.recovered_from_corruption
    assert any("corrupt" in n["msg"] for n in data["notices"])
    assert data["data"] == {}
