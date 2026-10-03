import json
import socket as _socket
import time

import pytest

from blaxcy.ipc import IPCClient, IPCServer, sign
from blaxcy.models import IPC_VERSION, IPCMessage


@pytest.fixture
def server(tmp_path):
    sock = tmp_path / "blaxcy.sock"
    secret = "test-secret"

    def handler(message: IPCMessage):
        if message.type == "ping":
            return {"pong": message.payload}
        if message.type == "boom":
            raise ValueError("handler blew up")
        return {"unknown": message.type}

    srv = IPCServer(sock, secret, handler)
    srv.start()
    yield sock, secret
    srv.stop()


def test_round_trip(server):
    sock, secret = server
    client = IPCClient(sock, secret)
    reply = client.request("ping", {"n": 41})
    assert reply.type == "result"
    assert reply.payload["pong"] == {"n": 41}
    assert reply.correlation_id


def test_correlation_id_is_echoed(server):
    sock, secret = server
    reply = IPCClient(sock, secret).request("ping", {"n": 1}, correlation_id="req-123")
    assert reply.type == "result"
    assert reply.correlation_id == "req-123"


def test_bad_token_rejected(server):
    sock, _ = server
    client = IPCClient(sock, "wrong-secret")
    reply = client.request("ping")
    assert reply.type == "error"
    assert "authentication" in reply.payload["error"]


def test_bad_version_rejected(server):
    sock, secret = server
    msg = IPCMessage(type="ping", version=IPC_VERSION + 1)
    msg.token = sign(secret, msg)
    # send a version-mismatched message directly
    import socket as _socket

    with _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM) as s:
        s.connect(str(sock))
        s.sendall(msg.to_json().encode() + b"\n")
        data = b""
        while b"\n" not in data:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
    reply = IPCMessage.from_json(data.split(b"\n", 1)[0].decode())
    assert reply.type == "error"
    assert "version" in reply.payload["error"]


def test_handler_exception_returns_error(server):
    sock, secret = server
    reply = IPCClient(sock, secret).request("boom")
    assert reply.type == "error"
    assert "handler error" in reply.payload["error"]


# --------------------------------------------------------------------------- #
# security: freshness, replay, duplicate fields, tampering
# --------------------------------------------------------------------------- #
def _send_raw(sock, raw: str) -> IPCMessage:
    with _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM) as s:
        s.connect(str(sock))
        s.sendall(raw.encode() + b"\n")
        data = b""
        while b"\n" not in data:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
    return IPCMessage.from_json(data.split(b"\n", 1)[0].decode())


def test_stale_message_is_rejected(server):
    sock, secret = server
    msg = IPCMessage(type="ping", ts=time.time() - 3600)
    msg.token = sign(secret, msg)
    reply = _send_raw(sock, msg.to_json())
    assert reply.type == "error"
    assert "stale" in reply.payload["error"]


def test_replayed_message_is_rejected(server):
    sock, secret = server
    msg = IPCMessage(type="ping")
    msg.token = sign(secret, msg)
    first = _send_raw(sock, msg.to_json())
    second = _send_raw(sock, msg.to_json())
    assert first.type == "result"
    assert second.type == "error"
    assert "replay" in second.payload["error"]


def test_tampered_timestamp_breaks_the_hmac(server):
    sock, secret = server
    msg = IPCMessage(type="ping")
    msg.token = sign(secret, msg)
    msg.ts = time.time() - 5          # change it after signing
    reply = _send_raw(sock, msg.to_json())
    assert reply.type == "error"
    assert "authentication" in reply.payload["error"]


def test_duplicate_json_fields_are_rejected(server):
    sock, secret = server
    msg = IPCMessage(type="ping")
    msg.token = sign(secret, msg)
    d = json.loads(msg.to_json())
    raw = json.dumps(d) + "\n"
    # Splice a second "type" key into the object to make it ambiguous.
    raw = raw.replace('"type":', '"type": "ping", "type":', 1)
    reply = _send_raw(sock, raw)
    assert reply.type == "error"
    assert "duplicate" in reply.payload["error"]
