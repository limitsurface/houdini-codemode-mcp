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
        return "pythonsnippet"

    def category(self):
        return FakeCategory()


class FakeTemplateType:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class FakeTemplate:
    def __init__(self, name, type_name="Float", components=1):
        self._name = name
        self._type_name = type_name
        self._components = components

    def name(self):
        return self._name

    def type(self):
        return FakeTemplateType(self._type_name)

    def numComponents(self):
        return self._components


class FakeFolder:
    def __init__(self, templates=()):
        self.templates = list(templates)

    def parmTemplates(self):
        return tuple(self.templates)

    def clone(self):
        return FakeFolder(self.templates)

    def setParmTemplates(self, templates):
        self.templates = list(templates)


class FakeParmTemplateGroup:
    def __init__(self, folder):
        self.folder = folder

    def find(self, name):
        return self.folder if name == "folder_generatedparms_pythoncode" else None

    def replace(self, _name, folder):
        self.folder = folder


class FakeParm:
    def __init__(self, name, value, *, raw=None, template=None):
        self._name = name
        self.value = value
        self._raw = raw
        self._template = template or FakeTemplate(name)

    def name(self):
        return self._name

    def eval(self):
        return self.value

    def evalAsString(self):
        return str(self.value)

    def rawValue(self):
        return self._raw if self._raw is not None else str(self.value)

    def set(self, value):
        self.value = value

    def parmTemplate(self):
        return self._template

    def expression(self):
        raise RuntimeError("no expression")


class FakeNode:
    def __init__(self, clean=True):
        self._type = FakeNodeType()
        self.folder = FakeFolder([FakeTemplate("amplitude")]) if clean else FakeFolder()
        self.group = FakeParmTemplateGroup(self.folder)
        self._parms = {
            "pythoncode": FakeParm("pythoncode", "#bind parm amplitude float val=0.25"),
            "bindings": FakeParm("bindings", 1 if clean else 0),
        }
        if clean:
            self.install_binding(binding_type="float")

    def path(self):
        return "/obj/geo1/python1"

    def type(self):
        return self._type

    def parm(self, name):
        return self._parms.get(name)

    def parmTuple(self, name):
        return None

    def spareParms(self):
        return tuple(
            parm
            for name, parm in self._parms.items()
            if name == "amplitude"
        )

    def parmTemplateGroup(self):
        return self.group

    def setParmTemplateGroup(self, group):
        self.group = group
        self.folder = group.folder

    def install_binding(self, binding_type="float"):
        self._parms["bindings"].value = 1
        self._parms["bindings1_name"] = FakeParm("bindings1_name", "amplitude")
        self._parms["bindings1_type"] = FakeParm("bindings1_type", binding_type)
        self._parms["bindings1_fval"] = FakeParm(
            "bindings1_fval", 0.25, raw='ch("./amplitude")'
        )
        self._parms["amplitude"] = FakeParm("amplitude", 0.25)
        self.folder.templates = [FakeTemplate("amplitude")]


class FakeText:
    def oclExtractBindings(self, _code):
        return [
            {
                "name": "amplitude",
                "type": "float",
                "readable": True,
                "writeable": False,
                "optional": False,
            }
        ]


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
    hou.text = FakeText()

    hdefereval = ModuleType("hdefereval")
    hdefereval.executeInMainThreadWithResult = lambda callback: callback()
    vex = ModuleType("vexpressionmenu")
    vex.createSpareParmsFromOCLBindings = lambda target, _parm: target.install_binding()
    monkeypatch.setitem(__import__("sys").modules, "hou", hou)
    monkeypatch.setitem(__import__("sys").modules, "hdefereval", hdefereval)
    monkeypatch.setitem(__import__("sys").modules, "vexpressionmenu", vex)
    namespace = {}
    exec(RUNTIME_SOURCE, namespace, namespace)
    return namespace["_houdini_codemode_execute_json"]


def _execute(runtime, source):
    request = ExecutionRequest.from_inputs(source, run_id="python-test")
    return json.loads(runtime(request.to_json()))


def test_python_sop_validate_compact_and_details(monkeypatch) -> None:
    node = FakeNode(clean=True)
    runtime = _load_runtime(monkeypatch, node)

    compact = _execute(runtime, "result.emit(ctx.python.validate('/obj/geo1/python1'))")
    details = _execute(
        runtime,
        "result.emit(ctx.python.validate('/obj/geo1/python1', details=True))",
    )

    assert compact["data"]["value"]["clean"] is True
    assert compact["data"]["value"]["control_count"] == 1
    assert details["data"]["value"]["controls"] == [
        {
            "binding": "amplitude",
            "control": "amplitude",
            "generated": True,
            "linked": True,
            "missing": False,
            "type": "float",
        }
    ]


def test_python_sop_sync_rebuilds_rows_controls_and_records_mutation(monkeypatch) -> None:
    node = FakeNode(clean=False)
    runtime = _load_runtime(monkeypatch, node)

    response = _execute(
        runtime,
        "result.emit(ctx.python.sync('/obj/geo1/python1', details=True))",
    )

    assert response["ok"] is True
    value = response["data"]["value"]
    assert value["clean"] is True
    assert value["validation"]["bindings_match_code"] is True
    assert node.parm("amplitude").eval() == 0.25
    assert response["meta"]["mutation"]["events"] == [
        {
            "kind": "python.interface_sync",
            "helper": "ctx.python.sync",
            "node_path": "/obj/geo1/python1",
            "context": "sop",
            "status": "complete",
            "clean": True,
        }
    ]
