from __future__ import annotations

import contextlib
import json
from types import ModuleType, SimpleNamespace

from houdini_codemode.protocol import ExecutionRequest
from houdini_codemode.runtime_source import RUNTIME_SOURCE


class FakeCategory:
    def name(self):
        return "Object"


class FakeNodeType:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name

    def category(self):
        return FakeCategory()

    def definition(self):
        return None


class FakeNode:
    def __init__(self, path, type_name="geo", parent=None, data=None):
        self._path = path
        self._type = FakeNodeType(type_name)
        self._parent = parent
        self._children = []
        self._data = data or {"type": type_name, "parms": {}}
        self._display = False
        self._value_data_calls = []
        self._parms_data_calls = []
        self._inputs_data_calls = []
        self._set_from_data_calls = []

    def path(self):
        return self._path

    def name(self):
        return self._path.rsplit("/", 1)[-1]

    def type(self):
        return self._type

    def children(self):
        return tuple(self._children)

    def allItems(self):
        return tuple(self._children)

    def matchesCurrentDefinition(self):
        return True

    def asData(self, **kwargs):
        return {
            key: value
            for key, value in self._data.items()
            if key != "children" or kwargs.get("children", False)
        }

    def setFromData(self, data, **_kwargs):
        self._set_from_data_calls.append(data)
        self._data = data
        child_data = data.get("children", {}) if isinstance(data, dict) else {}
        self._children = [
            FakeNode(self.path() + "/" + name, row.get("type", "null"), parent=self)
            for name, row in child_data.items()
        ]

    def parm(self, name):
        return FakeParm(self, name)

    def setParmsFromData(self, data):
        self._parms_data_calls.append(data)

    def setInputsFromData(self, data):
        self._inputs_data_calls.append(data)

    def setDisplayFlag(self, value):
        self._display = bool(value)

    def isEditable(self):
        return True

    def node(self, name):
        return next((child for child in self._children if child.name() == name), None)

    def createNode(self, type_name, name):
        candidate = name
        suffix = 1
        while self.node(candidate) is not None:
            candidate = f"{name}{suffix}"
            suffix += 1
        node = FakeNode(self.path().rstrip("/") + "/" + candidate, type_name, parent=self)
        self._children.append(node)
        return node

    def destroy(self):
        if self._parent is not None:
            self._parent._children.remove(self)

    def errors(self):
        return ()

    def warnings(self):
        return ()


class FakeParm:
    def __init__(self, node, name):
        self._node = node
        self._name = name

    def setValueFromData(self, data):
        self._node._value_data_calls.append((self._name, data))


class FakeHipFile:
    def hasUnsavedChanges(self):
        return False

    def path(self):
        return "C:/project/test.hip"


class FakeUndos:
    @contextlib.contextmanager
    def group(self, _label):
        yield


def _load_runtime(monkeypatch, artifact_root, *, large=False):
    root = FakeNode("/obj", "obj")
    data = {
        "type": "geo",
        "parms": {"text": "x" * (5_000 if large else 20)},
        "children": {"box1": {"type": "box"}},
    }
    source = FakeNode("/obj/source", "geo", parent=root, data=data)
    source._children = [FakeNode("/obj/source/box1", "box", parent=source)]
    root._children.append(source)

    def find(path):
        pending = [root]
        while pending:
            node = pending.pop()
            if node.path() == path:
                return node
            pending.extend(node.children())
        return None

    hou = ModuleType("hou")
    hou.Node = FakeNode
    hou.Parm = type("UnusedParm", (), {})
    hou.NodeType = FakeNodeType
    hou.session = SimpleNamespace()
    hou.hipFile = FakeHipFile()
    hou.undos = FakeUndos()
    hou.applicationVersionString = lambda: "22.0.368"
    hou.node = find
    hou.expandString = lambda value: value
    hou.updateMode = SimpleNamespace(Manual="manual")
    hou._update_mode = "auto"
    hou.updateModeSetting = lambda: hou._update_mode
    hou.setUpdateMode = lambda value: setattr(hou, "_update_mode", value)

    hdefereval = ModuleType("hdefereval")
    hdefereval.executeInMainThreadWithResult = lambda callback: callback()
    monkeypatch.setenv("HOUDINI_CODEMODE_ARTIFACT_ROOT", str(artifact_root))
    monkeypatch.setitem(__import__("sys").modules, "hou", hou)
    monkeypatch.setitem(__import__("sys").modules, "hdefereval", hdefereval)
    namespace = {}
    exec(RUNTIME_SOURCE, namespace, namespace)
    return namespace["_houdini_codemode_execute_json"], hou


def _execute(runtime, source, run_id="artifact-test"):
    request = ExecutionRequest.from_inputs(source, run_id=run_id)
    return json.loads(runtime(request.to_json()))


def test_artifact_round_trip_returns_only_manifest_and_records_effects(monkeypatch, tmp_path) -> None:
    runtime, hou = _load_runtime(monkeypatch, tmp_path)

    response = _execute(
        runtime,
        "exported = ctx.artifacts.export_node('/obj/source', name='snapshot', children=True)\n"
        "inspected = ctx.artifacts.inspect(exported)\n"
        "restored = ctx.artifacts.import_node(exported, '/obj', name='restored')\n"
        "result.emit({'exported': exported, 'inspected': inspected, "
        "'restored': restored, 'listed': ctx.artifacts.list()})",
    )

    assert response["ok"] is True
    value = response["data"]["value"]
    artifact = value["exported"]["artifact"]
    assert artifact["id"] == "snapshot.hcm-node.json"
    assert artifact["bytes"] > 0
    assert len(artifact["sha256"]) == 64
    assert artifact["runtime_version"] == "0.2"
    assert artifact["houdini_version"] == "22.0.368"
    assert artifact["captured_records"] >= 1
    assert artifact["captured_items"] == 1
    assert value["exported"]["summary"]["direct_nodes"] == 1
    assert value["inspected"]["artifact"]["sha256"] == artifact["sha256"]
    assert value["restored"]["path"] == "/obj/restored"
    assert value["restored"]["verified"] is True
    assert value["listed"]["rows"][0][0] == artifact["id"]
    assert "data" not in value["exported"]
    assert "data" not in value["inspected"]
    assert hou.node("/obj/restored/box1") is not None
    assert hou._update_mode == "auto"
    assert [event["kind"] for event in response["meta"]["mutation"]["events"]] == [
        "artifact.write",
        "artifact.read",
        "node.create_from_artifact",
    ]

    removed = _execute(
        runtime,
        "result.emit(ctx.artifacts.remove('snapshot.hcm-node.json'))",
        run_id="artifact-remove",
    )
    assert removed["ok"] is True
    assert removed["data"]["value"]["removed"] is True
    assert removed["meta"]["mutation"]["events"][0]["kind"] == "artifact.remove"
    assert not (tmp_path / "snapshot.hcm-node.json").exists()


def test_artifact_write_limit_leaves_no_final_or_temporary_file(monkeypatch, tmp_path) -> None:
    runtime, _hou = _load_runtime(monkeypatch, tmp_path, large=True)

    response = _execute(
        runtime,
        "result.emit(ctx.artifacts.export_node('/obj/source', name='too-large', "
        "children=True, max_bytes=1024))",
    )

    assert response["ok"] is False
    assert response["error"]["type"] == "ValueError"
    assert "1024-byte limit" in response["error"]["message"]
    assert list(tmp_path.iterdir()) == []


def test_artifact_import_uses_value_inverse_with_inner_parm_payload(monkeypatch, tmp_path) -> None:
    runtime, hou = _load_runtime(monkeypatch, tmp_path)

    response = _execute(
        runtime,
        "exported = ctx.artifacts.export_node('/obj/source', name='value', children=False)\n"
        "result.emit(ctx.artifacts.import_node(exported, '/obj', name='restored'))",
    )

    assert response["ok"] is True
    assert response["data"]["value"]["inverse_methods"] == ["setValueFromData"]
    restored = hou.node("/obj/restored")
    assert restored._value_data_calls == [("text", "x" * 20)]
    assert restored._set_from_data_calls == []


def test_artifact_import_uses_parms_and_inputs_inverses(monkeypatch, tmp_path) -> None:
    runtime, hou = _load_runtime(monkeypatch, tmp_path)
    source = hou.node("/obj/source")
    source._data = {
        "type": "geo",
        "parms": {"first": 1, "second": 2},
        "inputs": [{"from": "upstream", "from_index": 0, "to_index": 0}],
    }

    response = _execute(
        runtime,
        "exported = ctx.artifacts.export_node('/obj/source', name='narrow', children=False)\n"
        "result.emit(ctx.artifacts.import_node(exported, '/obj', name='restored'))",
    )

    assert response["ok"] is True
    assert response["data"]["value"]["inverse_methods"] == [
        "setParmsFromData",
        "setInputsFromData",
    ]
    restored = hou.node("/obj/restored")
    assert restored._parms_data_calls == [{"first": 1, "second": 2}]
    assert restored._inputs_data_calls == [source._data["inputs"]]
    assert restored._set_from_data_calls == []


def test_artifact_import_falls_back_for_broad_node_data(monkeypatch, tmp_path) -> None:
    runtime, hou = _load_runtime(monkeypatch, tmp_path)
    source = hou.node("/obj/source")
    source._data["flags"] = {"display": True}

    response = _execute(
        runtime,
        "exported = ctx.artifacts.export_node('/obj/source', name='broad', children=False)\n"
        "result.emit(ctx.artifacts.import_node(exported, '/obj', name='restored'))",
    )

    assert response["ok"] is True
    assert response["data"]["value"]["inverse_methods"] == ["setFromData"]
    restored = hou.node("/obj/restored")
    assert restored._set_from_data_calls == [
        {key: value for key, value in source._data.items() if key != "children"}
    ]


def test_artifact_service_rejects_paths_outside_its_root(monkeypatch, tmp_path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.hcm-node.json"
    outside.write_text("{}", encoding="utf-8")
    runtime, _hou = _load_runtime(monkeypatch, root)

    response = _execute(
        runtime,
        f"result.emit(ctx.artifacts.inspect({str(outside)!r}))",
    )

    assert response["ok"] is False
    assert response["error"]["type"] == "ValueError"
    assert "outside" in response["error"]["message"]
