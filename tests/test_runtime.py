from __future__ import annotations

import contextlib
import json
import threading
from types import ModuleType, SimpleNamespace

from houdini_codemode.protocol import ExecutionRequest
from houdini_codemode.runtime_source import RUNTIME_SOURCE


class FakeCategory:
    def name(self):
        return "Object"


class FakeNodeType:
    def __init__(self, name="geo") -> None:
        self._name = name

    def name(self):
        return self._name

    def category(self):
        return FakeCategory()


class FakeNode:
    def __init__(self, path="/obj/geo1", type_name="geo") -> None:
        self._path = path
        self._type = FakeNodeType(type_name)

    def path(self):
        return self._path

    def name(self):
        return self._path.rsplit("/", 1)[-1]

    def type(self):
        return self._type

    def children(self):
        return ()

    def inputs(self):
        return ()

    def outputs(self):
        return ()

    def isDisplayFlagSet(self):
        return True

    def isRenderFlagSet(self):
        return False

    def isBypassed(self):
        return False


class FakeParmTemplateType:
    def name(self):
        return "Float"


class FakeParmTemplate:
    def type(self):
        return FakeParmTemplateType()


class FakeParmTuple:
    def name(self):
        return "size"


class FakeParm:
    def __init__(self, node) -> None:
        self._node = node

    def path(self):
        return self._node.path() + "/sizex"

    def name(self):
        return "sizex"

    def node(self):
        return self._node

    def tuple(self):
        return FakeParmTuple()

    def parmTemplate(self):
        return FakeParmTemplate()


class FakeHipFile:
    def __init__(self) -> None:
        self.dirty = False

    def hasUnsavedChanges(self):
        return self.dirty

    def path(self):
        return "C:/project/test.hip"


class FakeUndos:
    def __init__(self) -> None:
        self.labels = []

    @contextlib.contextmanager
    def group(self, label):
        self.labels.append(label)
        yield


def load_runtime(monkeypatch):
    node = FakeNode()
    hou = ModuleType("hou")
    hou.Node = FakeNode
    hou.Parm = FakeParm
    hou.NodeType = FakeNodeType
    hou.session = SimpleNamespace()
    hou.hipFile = FakeHipFile()
    hou.undos = FakeUndos()
    hou.applicationVersionString = lambda: "22.0.368"
    hou.node = lambda path: node if path == node.path() else None

    hdefereval = ModuleType("hdefereval")
    hdefereval.executeInMainThreadWithResult = lambda callback: callback()
    monkeypatch.setitem(__import__("sys").modules, "hou", hou)
    monkeypatch.setitem(__import__("sys").modules, "hdefereval", hdefereval)

    namespace = {}
    exec(RUNTIME_SOURCE, namespace, namespace)
    return namespace["_houdini_codemode_execute_json"], hou, node


def execute(runtime, source, *, args=None, policy=None, run_id="test-run"):
    request = ExecutionRequest.from_inputs(
        source,
        args=args,
        policy=policy,
        run_id=run_id,
    )
    return json.loads(runtime(request.to_json()))


def test_runtime_uses_args_fresh_globals_and_one_structured_result(monkeypatch) -> None:
    runtime, _hou, _node = load_runtime(monkeypatch)

    first = execute(
        runtime,
        "hidden = 7\nresult.emit({'value': args['value'], 'hidden': hidden})",
        args={"value": 3},
    )
    second = execute(runtime, "result.emit(hidden)", run_id="second-run")

    assert first["ok"] is True
    assert first["data"]["value"] == {"hidden": 7, "value": 3}
    assert first["meta"]["thread"] == "MainThread"
    assert second["ok"] is False
    assert second["error"]["category"] == "execution"
    assert second["error"]["type"] == "NameError"


def test_runtime_normalizes_node_parm_and_type(monkeypatch) -> None:
    runtime, _hou, _node = load_runtime(monkeypatch)

    response = execute(
        runtime,
        "node = hou.node('/obj/geo1')\n"
        "result.emit({'node': node, 'parm': hou.Parm(node), 'type': node.type()})",
    )

    assert response["ok"] is True
    assert response["data"]["value"]["node"]["path"] == "/obj/geo1"
    assert response["data"]["value"]["node"]["flags"] == ["display"]
    assert response["data"]["value"]["parm"]["kind"] == "hou.Parm"
    assert response["data"]["value"]["type"] == {
        "kind": "hou.NodeType",
        "name": "geo",
        "category": "Object",
    }


def test_runtime_caps_unicode_logs_and_container_items(monkeypatch) -> None:
    runtime, _hou, _node = load_runtime(monkeypatch)

    response = execute(
        runtime,
        "print('éééé', end='')\nresult.emit(list(range(5)))",
        policy={"max_log_bytes": 5, "max_container_items": 2},
    )

    assert response["ok"] is True
    assert len(response["data"]["logs"]["stdout"].encode("utf-8")) <= 5
    assert response["data"]["logs"]["stdout_truncated"] is True
    assert response["data"]["value"] == [0, 1]
    reasons = {item["reason"] for item in response["meta"]["truncations"]}
    assert reasons == {"max_container_items", "max_log_bytes"}


def test_runtime_returns_structured_execution_and_result_errors(monkeypatch) -> None:
    runtime, _hou, _node = load_runtime(monkeypatch)

    execution = execute(runtime, "raise ValueError('problem')")
    duplicate = execute(
        runtime,
        "result.emit(1)\nresult.emit(2)",
        run_id="duplicate-run",
    )
    unsupported = execute(
        runtime,
        "result.emit(object())",
        run_id="unsupported-run",
    )

    assert execution["error"]["category"] == "execution"
    assert execution["error"]["type"] == "ValueError"
    assert "problem" in execution["error"]["message"]
    assert duplicate["error"]["category"] == "result"
    assert unsupported["error"]["category"] == "result"
    assert "Unsupported result type" in unsupported["error"]["message"]


def test_runtime_rejects_cycles_and_non_finite_floats(monkeypatch) -> None:
    runtime, _hou, _node = load_runtime(monkeypatch)

    cycle = execute(
        runtime,
        "value = []\nvalue.append(value)\nresult.emit(value)",
    )
    non_finite = execute(
        runtime,
        "result.emit(float('nan'))",
        run_id="nan-run",
    )

    assert cycle["error"]["category"] == "result"
    assert "Cycle detected" in cycle["error"]["message"]
    assert non_finite["error"]["category"] == "result"
    assert "Non-finite" in non_finite["error"]["message"]


def test_runtime_reports_busy_without_starting(monkeypatch) -> None:
    runtime, hou, _node = load_runtime(monkeypatch)
    first = execute(runtime, "pass")
    lock = hou.session._houdini_codemode_run_lock
    lock.acquire()
    try:
        busy = execute(runtime, "raise AssertionError('must not run')", run_id="busy-run")
    finally:
        lock.release()

    assert first["ok"] is True
    assert busy["ok"] is False
    assert busy["error"]["category"] == "busy"
    assert busy["meta"]["completion"] == "not_started"


def test_runtime_returns_structured_internal_dispatch_error(monkeypatch) -> None:
    runtime, _hou, _node = load_runtime(monkeypatch)
    hdefereval = __import__("sys").modules["hdefereval"]
    hdefereval.executeInMainThreadWithResult = lambda callback: (_ for _ in ()).throw(
        RuntimeError("dispatch failed")
    )

    responses = []
    worker = threading.Thread(
        target=lambda: responses.append(execute(runtime, "result.emit(1)"))
    )
    worker.start()
    worker.join()
    response = responses[0]

    assert response["ok"] is False
    assert response["error"]["category"] == "internal"
    assert response["error"]["type"] == "RuntimeError"
    assert response["meta"]["completion"] == "unknown"


def test_runtime_uses_undo_group_but_never_saves(monkeypatch) -> None:
    runtime, hou, _node = load_runtime(monkeypatch)

    grouped = execute(runtime, "pass")
    ungrouped = execute(
        runtime,
        "pass",
        policy={"undo_group": False},
        run_id="ungrouped-run",
    )

    assert grouped["ok"] is True
    assert ungrouped["ok"] is True
    assert hou.undos.labels == ["Houdini Code Mode"]
    assert not hasattr(hou.hipFile, "save")


def test_runtime_enforces_result_and_complete_response_bytes(monkeypatch) -> None:
    runtime, _hou, _node = load_runtime(monkeypatch)

    result_too_large = execute(
        runtime,
        "result.emit('x' * 300)",
        policy={"max_result_bytes": 256, "max_string_bytes": 1000},
    )
    response_too_large = execute(
        runtime,
        "print('x' * 2000, end='')",
        policy={"max_response_bytes": 1024, "max_log_bytes": 3000},
        run_id="response-limit-run",
    )

    assert result_too_large["ok"] is False
    assert result_too_large["error"]["category"] == "result"
    assert "result limit" in result_too_large["error"]["message"]
    assert response_too_large["ok"] is False
    assert response_too_large["error"]["type"] == "ResponseTooLarge"
    assert response_too_large["meta"]["completion"] == "complete"


def test_runtime_enforces_string_depth_total_item_and_dict_key_limits(monkeypatch) -> None:
    runtime, _hou, _node = load_runtime(monkeypatch)

    string_limited = execute(
        runtime,
        "result.emit('é' * 20)",
        policy={"max_string_bytes": 16},
    )
    depth_limited = execute(
        runtime,
        "result.emit([[[1]]])",
        policy={"max_depth": 1},
        run_id="depth-run",
    )
    total_limited = execute(
        runtime,
        "result.emit(list(range(10)))",
        policy={"max_total_items": 3},
        run_id="total-run",
    )
    invalid_key = execute(
        runtime,
        "result.emit({1: 'value'})",
        run_id="key-run",
    )

    assert string_limited["data"]["value"] == "é" * 8
    assert string_limited["meta"]["truncations"][0]["reason"] == "max_string_bytes"
    assert depth_limited["data"]["value"] == [[{"$truncated": "max_depth"}]]
    assert depth_limited["meta"]["truncations"][0]["reason"] == "max_depth"
    assert total_limited["data"]["value"] == [0, 1]
    assert total_limited["meta"]["truncations"][0]["reason"] == "max_total_items"
    assert invalid_key["error"]["category"] == "result"
    assert "must be a string" in invalid_key["error"]["message"]
