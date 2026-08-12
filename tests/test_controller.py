from __future__ import annotations

import json

from houdini_codemode.backend import BackendWaitTimeoutError
from houdini_codemode.controller import Controller


class EchoBackend:
    def __init__(self) -> None:
        self.calls = []

    def execute_json(self, request_json, instance, wait_timeout_seconds):
        request = json.loads(request_json)
        self.calls.append((request, instance, wait_timeout_seconds))
        return json.dumps(
            {
                "ok": True,
                "data": {"value": request["args"]},
                "meta": {"run_id": request["run_id"], "completion": "complete"},
            }
        )


class TimeoutBackend:
    def execute_json(self, request_json, instance, wait_timeout_seconds):
        raise BackendWaitTimeoutError("still running", error_type="RemoteWaitTimeout")


class StaticBackend:
    def __init__(self, response) -> None:
        self.response = response

    def execute_json(self, request_json, instance, wait_timeout_seconds):
        return self.response


def test_controller_sends_one_json_request_and_returns_one_envelope() -> None:
    backend = EchoBackend()
    controller = Controller(lambda: backend)

    response = controller.run(
        "result.emit(args)",
        args={"name": "code-mode"},
        instance={"host": "127.0.0.1", "port": 18812},
        policy={"wait_timeout_seconds": 7.5},
    )

    assert response["ok"] is True
    assert response["data"]["value"] == {"name": "code-mode"}
    assert len(backend.calls) == 1
    request, instance, timeout = backend.calls[0]
    assert request["source"] == "result.emit(args)"
    assert instance.port == 18812
    assert timeout == 7.5


def test_controller_reports_wait_timeout_as_unknown_completion() -> None:
    response = Controller(TimeoutBackend).run("pass")

    assert response["ok"] is False
    assert response["error"]["category"] == "timeout"
    assert response["error"]["type"] == "RemoteWaitTimeout"
    assert response["meta"]["completion"] == "unknown"


def test_controller_does_not_call_backend_for_compile_failure() -> None:
    called = False

    def factory():
        nonlocal called
        called = True
        return EchoBackend()

    response = Controller(factory).run("if True print(1)")

    assert response["error"]["category"] == "compile"
    assert called is False


def test_controller_rejects_invalid_json_and_run_id_mismatch() -> None:
    invalid = Controller(lambda: StaticBackend("not json")).run("pass")
    mismatch = Controller(
        lambda: StaticBackend(
            json.dumps({"ok": True, "meta": {"run_id": "someone-else"}})
        )
    ).run("pass")

    assert invalid["error"]["type"] == "InvalidBackendJSON"
    assert mismatch["error"]["type"] == "RunIdMismatch"


def test_controller_enforces_local_response_limit() -> None:
    backend = EchoBackend()
    controller = Controller(lambda: backend)
    # The hard minimum is 1024; force a backend payload beyond it.
    oversized = StaticBackend(" " * 1025)

    response = Controller(lambda: oversized).run(
        "pass", policy={"max_response_bytes": 1024}
    )

    assert response["error"]["type"] == "ResponseTooLarge"
    assert response["meta"]["completion"] == "complete"
