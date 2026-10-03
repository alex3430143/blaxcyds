"""Tests for AT-SPI accessibility perception (requirement C8).

The unreachable-bus path is exercised with an injected connection so the tests
are deterministic and never depend on what happens to be running on the host.
"""

from __future__ import annotations

from blaxcy.eye.atspi import ROOT_PATH, AccessibleNode, AtspiBackend


def test_accessible_node_to_dict():
    node = AccessibleNode(name="gedit", role="frame", app="gedit",
                          x=1, y=2, width=3, height=4)
    data = node.to_dict()
    assert data["name"] == "gedit"
    assert data["width"] == 3
    assert data["bus"] == ""


def test_summary_is_unavailable_when_bus_missing(monkeypatch):
    backend = AtspiBackend()
    monkeypatch.setattr(backend, "_connect", lambda: None)
    assert backend.is_available() is False
    summary = backend.summary()
    assert summary["available"] is False
    assert summary["windows"] == []


def test_nodes_are_cached_within_ttl(monkeypatch):
    backend = AtspiBackend(cache_ttl=100.0)
    calls = {"n": 0}
    monkeypatch.setattr(backend, "_connect", lambda: object())

    def fake_scan():
        calls["n"] += 1
        return [AccessibleNode(name="w", width=10, height=10)]

    monkeypatch.setattr(backend, "_scan", fake_scan)
    assert backend.nodes() and calls["n"] == 1
    assert backend.nodes() and calls["n"] == 1            # served from cache
    assert backend.nodes(force=True) and calls["n"] == 2  # forced refresh


def test_windows_filter_zero_size_and_limit(monkeypatch):
    backend = AtspiBackend()
    monkeypatch.setattr(backend, "_connect", lambda: object())
    nodes = [AccessibleNode(name=f"w{i}", width=1, height=1) for i in range(5)]
    nodes.append(AccessibleNode(name="invisible", width=0, height=0))
    monkeypatch.setattr(backend, "_scan", lambda: nodes)
    windows = backend.windows(max_windows=2)
    assert len(windows) == 2
    assert all(w.width > 0 and w.height > 0 for w in windows)


def test_summary_shape_when_available(monkeypatch):
    backend = AtspiBackend()
    monkeypatch.setattr(backend, "_connect", lambda: object())
    monkeypatch.setattr(backend, "_scan", lambda: [
        AccessibleNode(name="Files", role="frame", app="thunar", width=100, height=80),
    ])
    summary = backend.summary()
    assert summary["available"] is True
    assert summary["window_count"] == 1
    assert summary["applications"] == ["thunar"]
    assert summary["windows"][0]["name"] == "Files"


def test_availability_at_this_host_never_raises():
    backend = AtspiBackend(timeout=0.2)
    assert isinstance(backend.is_available(), bool)
    assert ROOT_PATH.startswith("/org/a11y/")
