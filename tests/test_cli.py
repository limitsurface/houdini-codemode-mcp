from __future__ import annotations

import io
import json

from houdini_codemode import cli


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
