from __future__ import annotations

import io
import json

from houdini_codemode import cli
from houdini_codemode.xfer import NodeTransferError


class FakeController:
    calls = []

    def run(self, source, args=None, instance=None, policy=None):
        self.calls.append((source, args, instance, policy))
        return {"ok": True, "data": {"value": args}, "meta": {}}

    def doctor(self, instance=None, policy=None):
        self.calls.append(("doctor", None, instance, policy))
        return {"ok": True, "data": {"healthy": True}, "meta": {}}


def test_check_reads_source_file(tmp_path, capsys) -> None:
    source = tmp_path / "task.py"
    source.write_text("result.emit(1)\n", encoding="utf-8")

    exit_code = cli.main(["check", "--file", str(source)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["data"]["valid"] is True


def test_run_parses_json_and_delegates_to_controller(monkeypatch, capsys) -> None:
    FakeController.calls = []
    monkeypatch.setattr(cli, "Controller", FakeController)

    exit_code = cli.main(
        [
            "run",
            "--code",
            "result.emit(args)",
            "--args",
            '{"value":3}',
            "--port",
            "18812",
            "--max-container-items",
            "5",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["data"]["value"] == {"value": 3}
    source, args, instance, policy = FakeController.calls[0]
    assert source == "result.emit(args)"
    assert args == {"value": 3}
    assert instance["port"] == 18812
    assert policy["max_container_items"] == 5


def test_run_rejects_non_object_args_without_calling_controller(monkeypatch, capsys) -> None:
    FakeController.calls = []
    monkeypatch.setattr(cli, "Controller", FakeController)

    exit_code = cli.main(["run", "--code", "pass", "--args", "[]"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["error"]["category"] == "validation"
    assert FakeController.calls == []


def test_run_reads_file_and_stdin(monkeypatch, tmp_path, capsys) -> None:
    FakeController.calls = []
    monkeypatch.setattr(cli, "Controller", FakeController)
    source_file = tmp_path / "run.py"
    source_file.write_text("result.emit('file')\n", encoding="utf-8")

    file_exit = cli.main(["run", "--file", str(source_file)])
    capsys.readouterr()
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("result.emit('stdin')\n"))
    stdin_exit = cli.main(["run", "--input", "-"])
    capsys.readouterr()

    assert file_exit == 0
    assert stdin_exit == 0
    assert FakeController.calls[0][0] == "result.emit('file')\n"
    assert FakeController.calls[1][0] == "result.emit('stdin')\n"


def test_xfer_copy_parser_and_delegation(monkeypatch, capsys) -> None:
    calls = []

    def fake_transfer(node_path, destination_parent, **kwargs):
        calls.append((node_path, destination_parent, kwargs))
        return {
            "operation": "transfer",
            "destination": {"path": "/obj/restored", "verified": True},
            "cleanup_complete": True,
            "cleanup_errors": [],
            "effects": {"source_hip_saved": False, "destination_hip_saved": False},
        }

    monkeypatch.setattr(cli, "transfer_node", fake_transfer)
    exit_code = cli.main(
        [
            "xfer", "copy", "/obj/source", "--to-parent", "/obj",
            "--from-port", "18811", "--to-port", "18814",
            "--name", "restored", "--unique", "--children", "--all-parms",
            "--editables", "--max-artifact-bytes", "4096",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["meta"] == {
        "completion": "complete",
        "operation": "xfer.copy",
        "cleanup_complete": True,
        "protocol_version": cli.PROTOCOL_VERSION,
        "runtime_version": cli.RUNTIME_VERSION,
    }
    assert calls == [
        (
            "/obj/source",
            "/obj",
            {
                "source": {"host": "localhost", "port": 18811},
                "destination": {"host": "localhost", "port": 18814},
                "name": "restored",
                "unique": True,
                "children": True,
                "all_parms": True,
                "editables": True,
                "max_artifact_bytes": 4096,
            },
        )
    ]


def test_xfer_copy_completed_import_with_cleanup_warning_is_success(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "transfer_node",
        lambda *_args, **_kwargs: {
            "destination": {"path": "/obj/restored", "verified": True},
            "cleanup_complete": False,
            "cleanup_errors": ["localhost:18811: cleanup unavailable"],
        },
    )

    exit_code = cli.main(
        ["xfer", "copy", "/obj/source", "--to-parent", "/obj", "--from-port", "18811", "--to-port", "18814"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["data"]["value"]["destination"]["path"] == "/obj/restored"
    assert payload["meta"]["completion"] == "complete"
    assert payload["meta"]["cleanup_complete"] is False


def test_xfer_copy_rejects_invalid_endpoints_without_calling_transfer(monkeypatch, capsys) -> None:
    called = False

    def fake_transfer(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("transfer should not run")

    monkeypatch.setattr(cli, "transfer_node", fake_transfer)
    exit_code = cli.main(
        ["xfer", "copy", "/obj/source", "--to-parent", "/obj", "--from-port", "18811", "--to-port", "18811"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["error"]["category"] == "validation"
    assert payload["meta"]["completion"] == "not_started"
    assert called is False


def test_xfer_copy_maps_transfer_failure_to_operation_envelope(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "transfer_node",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(NodeTransferError("import failed")),
    )

    exit_code = cli.main(
        ["xfer", "copy", "/obj/source", "--to-parent", "/obj", "--from-port", "18811", "--to-port", "18814"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["error"] == {
        "category": "operation",
        "type": "NodeTransferError",
        "message": "import failed",
    }
    assert payload["meta"]["completion"] == "unknown"
