from __future__ import annotations

import contextlib
import json
from types import ModuleType, SimpleNamespace

from houdini_codemode.protocol import ExecutionRequest
from houdini_codemode.runtime_source import RUNTIME_SOURCE


class FakeCategory:
    def name(self):
        return "Sop"


class FakeNodeType:
    def name(self):
        return "attribwrangle"

    def category(self):
        return FakeCategory()


class FakeTemplateType:
    def name(self):
        return "Float"


class FakeTemplate:
    def type(self):
        return FakeTemplateType()


class FakeParm:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name

    def parmTemplate(self):
        return FakeTemplate()


class FakeNode:
    def __init__(self):
        self._type = FakeNodeType()
        self._spares = [FakeParm("existing")]
        self._snippet = FakeParm("snippet")

    def path(self):
        return "/obj/geo1/wrangle1"

    def type(self):
        return self._type

    def parm(self, name):
        return self._snippet if name == "snippet" else None

    def spareParms(self):
        return tuple(self._spares)

    def removeSpareParms(self):
        self._spares = []


class FakeHipFile:
    def hasUnsavedChanges(self):
        return False

    def path(self):
        return "C:/project/test.hip"


class FakeUndos:
    @contextlib.contextmanager
    def group(self, _label):
        yield


def _load_runtime(monkeypatch, node):
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
    vex = ModuleType("vexpressionmenu")
    vex.createSpareParmsFromChCalls = lambda target, _parm: target._spares.append(
        FakeParm("amplitude")
    )
    monkeypatch.setitem(__import__("sys").modules, "hou", hou)
    monkeypatch.setitem(__import__("sys").modules, "hdefereval", hdefereval)
    monkeypatch.setitem(__import__("sys").modules, "vexpressionmenu", vex)
    namespace = {}
    exec(RUNTIME_SOURCE, namespace, namespace)
    return namespace["_houdini_codemode_execute_json"]


def _execute(runtime, source, run_id="wrangle-test"):
    request = ExecutionRequest.from_inputs(source, run_id=run_id)
    return json.loads(runtime(request.to_json()))


def test_wrangle_sync_and_clear_are_bounded_and_recorded(monkeypatch) -> None:
    node = FakeNode()
    runtime = _load_runtime(monkeypatch, node)

    synced = _execute(
        runtime,
        "result.emit(ctx.wrangle.sync('/obj/geo1/wrangle1'))",
    )
    cleared = _execute(
        runtime,
        "result.emit(ctx.wrangle.clear('/obj/geo1/wrangle1'))",
        run_id="wrangle-clear",
    )

    assert synced["data"]["value"] == {
        "node_path": "/obj/geo1/wrangle1",
        "cleared": False,
        "before": ["existing"],
        "after": ["existing", "amplitude"],
        "created": ["amplitude"],
    }
    assert synced["meta"]["mutation"]["events"][0]["created_count"] == 1
    assert cleared["data"]["value"]["removed"] == ["existing", "amplitude"]
    assert cleared["meta"]["mutation"]["events"][0]["kind"] == "wrangle.spare_parms_clear"
