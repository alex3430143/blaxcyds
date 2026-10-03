from blaxcy.supervisor import Supervisor


class FakeComponent:
    def __init__(self, healthy=True):
        self.started = 0
        self.stopped = 0
        self.healthy = healthy

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def health(self):
        return {"alive": self.healthy}


class RecordingBody:
    def __init__(self):
        self.releases = 0

    def panic_release(self):
        self.releases += 1


class FlakyComponent(FakeComponent):
    def __init__(self):
        super().__init__(healthy=False)
        self.start_calls = 0

    def start(self):
        self.start_calls += 1


def test_register_start_stop_and_health():
    sup = Supervisor()
    comp = FakeComponent()
    sup.register("eye", comp.start, comp.stop, health=comp.health)
    sup.start_all()
    assert sup.health()["eye"]["state"] == "running"
    assert sup.all_healthy()
    sup.stop_all()
    assert sup.health()["eye"]["state"] == "stopped"


def test_heartbeat_loss_triggers_restart_with_safe_release():
    body = RecordingBody()
    sup = Supervisor(body=body, max_restarts=3)
    comp = FakeComponent(healthy=False)
    sup.register("eye", comp.start, comp.stop, health=comp.health)
    sup.start_all()
    events = sup.check_once()
    assert any(e["event"] == "heartbeat_lost" for e in events)
    assert any(e["event"] == "restarted" for e in events)
    assert body.releases == 1
    assert comp.stopped >= 1  # stopped before restart


def test_restart_exhaustion_marks_failed():
    sup = Supervisor(max_restarts=1)
    comp = FakeComponent(healthy=False)
    sup.register("eye", comp.start, comp.stop, health=comp.health)
    sup.start_all()
    sup.check_once()  # restart #1 -> becomes DEGRADED
    sup.check_once()  # exceeds max -> FAILED
    assert sup.health()["eye"]["state"] == "failed"
    assert not sup.all_healthy()


def test_start_failure_is_contained():
    sup = Supervisor()

    def boom():
        raise RuntimeError("cannot start")

    comp = FakeComponent()
    sup.register("bad", boom, comp.stop)
    sup.start_all()
    assert sup.health()["bad"]["state"] == "failed"
    assert any(e["kind"] == "start_failed" for e in sup.diagnostics())
