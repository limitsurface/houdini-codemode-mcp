from __future__ import annotations

import contextlib
import json
import threading

import pytest
from rpyc.core.async_ import AsyncResultTimeout

from houdini_codemode.backend import BackendConnectionError, BackendWaitTimeoutError
from houdini_codemode.protocol import ExecutionRequest
from houdini_codemode.transport import rpyc as transport


class FakeConnection:
    def __init__(self, events, *, timeout=False, cached=False) -> None:
        self.events = events
        self.timeout = timeout
        self._config = {}
        self.namespace = {}
        self.runtime_hash = transport.RUNTIME_SOURCE_HASH if cached else None
        self.runtime_version = transport.RUNTIME_VERSION if cached else None

    def execute(self, source):
        if source == "import hou as _hcm_bootstrap_hou":
            self.events.append(("bootstrap",))
        elif source == transport.RUNTIME_SOURCE:
            self.events.append(("install",))
        else:
            self.events.append(("publish",))
            if "_houdini_codemode_execute_json" in source:
                self.runtime_hash = self.namespace["_houdini_codemode_install_hash"]
                self.runtime_version = self.namespace["_houdini_codemode_install_version"]

    def eval(self, expression):
        self.events.append(("eval", expression))
        if "_houdini_codemode_runtime_hash" in expression:
            return self.runtime_hash
        if "_houdini_codemode_runtime_version" in expression:
            return self.runtime_version
        if self.timeout and "_houdini_codemode_execute_json" in expression:
            raise AsyncResultTimeout("expired")
        request = json.loads(self.namespace["_houdini_codemode_request_json"])
        return json.dumps(
            {
                "ok": True,
                "data": {"value": request["args"]},
                "meta": {"run_id": request["run_id"], "completion": "complete"},
            }
        )

    def close(self):
        self.events.append(("close",))


def test_backend_holds_gate_for_install_execute_obtain_and_close(monkeypatch) -> None:
    events = []
    connection = FakeConnection(events)

    @contextlib.contextmanager
    def fake_gate(host, port, timeout):
        events.append(("gate-enter", host, port, timeout))
        yield
        events.append(("gate-exit",))

    def fake_connect(host, port):
        events.append(("connect", host, port))
        return connection

    monkeypatch.setattr(transport, "connection_gate", fake_gate)
    monkeypatch.setattr(transport.rpyc.classic, "connect", fake_connect)
    monkeypatch.setattr(transport, "obtain", lambda value: value)
    request = ExecutionRequest.from_inputs("pass", args={"answer": 42})

    response = transport.RPyCBackend().execute_json(
        request.to_json(), request.instance, 9.5
    )

    assert json.loads(response)["data"]["value"] == {"answer": 42}
    assert connection._config["sync_request_timeout"] is None
    assert [event[0] for event in events] == [
        "gate-enter",
        "connect",
        "bootstrap",
        "eval",
        "eval",
        "install",
        "publish",
        "eval",
        "close",
        "gate-exit",
    ]


def test_backend_reuses_matching_houdini_runtime(monkeypatch) -> None:
    events = []
    connection = FakeConnection(events, cached=True)

    @contextlib.contextmanager
    def fake_gate(host, port, timeout):
        yield

    monkeypatch.setattr(transport, "connection_gate", fake_gate)
    monkeypatch.setattr(transport.rpyc.classic, "connect", lambda host, port: connection)
    monkeypatch.setattr(transport, "obtain", lambda value: value)
    request = ExecutionRequest.from_inputs("pass")

    transport.RPyCBackend().execute_json(request.to_json(), request.instance, 1.0)

    assert "install" not in [event[0] for event in events]
    assert "publish" not in [event[0] for event in events]


def test_backend_reports_remote_wait_timeout_as_unknown(monkeypatch) -> None:
    events = []
    connection = FakeConnection(events, timeout=True)

    @contextlib.contextmanager
    def fake_gate(host, port, timeout):
        yield

    monkeypatch.setattr(transport, "connection_gate", fake_gate)
    monkeypatch.setattr(transport.rpyc.classic, "connect", lambda host, port: connection)
    request = ExecutionRequest.from_inputs("pass")

    with pytest.raises(BackendWaitTimeoutError, match="may still be running") as caught:
        transport.RPyCBackend().execute_json(
            request.to_json(), request.instance, 0.1
        )

    assert caught.value.completion == "unknown"
    assert ("close",) in events


def test_background_waiter_retains_gate_after_local_wait_timeout(monkeypatch) -> None:
    events = []
    remote_started = threading.Event()
    release_remote = threading.Event()

    class BlockingConnection(FakeConnection):
        def eval(self, expression):
            if "_houdini_codemode_execute_json" not in expression:
                return super().eval(expression)
            events.append(("remote-start",))
            remote_started.set()
            release_remote.wait(2.0)
            events.append(("remote-finish",))
            request = json.loads(self.namespace["_houdini_codemode_request_json"])
            return json.dumps(
                {
                    "ok": True,
                    "data": {"value": request["args"]},
                    "meta": {"run_id": request["run_id"], "completion": "complete"},
                }
            )

    connection = BlockingConnection(events, cached=True)

    @contextlib.contextmanager
    def fake_gate(host, port, timeout):
        events.append(("gate-enter",))
        yield
        events.append(("gate-exit",))

    monkeypatch.setattr(transport, "connection_gate", fake_gate)
    monkeypatch.setattr(transport.rpyc.classic, "connect", lambda host, port: connection)
    monkeypatch.setattr(transport, "obtain", lambda value: value)
    request = ExecutionRequest.from_inputs("pass")

    with pytest.raises(BackendWaitTimeoutError, match="retaining the endpoint gate"):
        transport.RPyCBackend().execute_json(
            request.to_json(), request.instance, 0.01
        )

    assert remote_started.wait(1.0)
    assert ("gate-exit",) not in events
    assert ("close",) not in events
    release_remote.set()
    for _ in range(100):
        if ("gate-exit",) in events:
            break
        threading.Event().wait(0.01)
    assert events.index(("remote-finish",)) < events.index(("close",))
    assert events.index(("close",)) < events.index(("gate-exit",))


def test_backend_wraps_connection_refusal(monkeypatch) -> None:
    @contextlib.contextmanager
    def fake_gate(host, port, timeout):
        yield

    monkeypatch.setattr(transport, "connection_gate", fake_gate)
    monkeypatch.setattr(
        transport.rpyc.classic,
        "connect",
        lambda host, port: (_ for _ in ()).throw(ConnectionRefusedError("refused")),
    )
    request = ExecutionRequest.from_inputs("pass")

    with pytest.raises(BackendConnectionError, match="Failed to connect"):
        transport.RPyCBackend().execute_json(
            request.to_json(), request.instance, 1.0
        )
