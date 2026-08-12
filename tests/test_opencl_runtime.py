from __future__ import annotations

import contextlib
import json
from types import ModuleType, SimpleNamespace

from houdini_codemode.protocol import ExecutionRequest
from houdini_codemode.runtime_source import RUNTIME_SOURCE


class FakeCategory:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class FakeNodeType:
    def __init__(self, name, category):
        self._name = name
        self._category = FakeCategory(category)

    def name(self):
        return self._name

    def category(self):
        return self._category


class FakeParm:
    def __init__(self, value, expression=None):
        self.value = value
        self._expression = expression

    def eval(self):
        return self.value

    def evalAsString(self):
        return str(self.value)

    def expression(self):
        if self._expression is None:
            raise RuntimeError("no expression")
        return self._expression


class FakeConnection:
    def __init__(self, source, input_index=0, output_index=0):
        self._source = source
        self._input_index = input_index
        self._output_index = output_index

    def inputNode(self):
        return self._source

    def outputNode(self):
        return None

    def inputIndex(self):
        return self._input_index

    def outputIndex(self):
        return self._output_index

    def inputName(self):
        return "out"

    def inputLabel(self):
        return "Output"


class FakeNode:
    def __init__(self, path, type_name, category, parms=None):
        self._path = path
        self._type = FakeNodeType(type_name, category)
        self._parms = parms or {}
        self._connections = []
        self._output_types = []
        self.cooked = False

    def path(self):
        return self._path

    def type(self):
        return self._type

    def parm(self, name):
        return self._parms.get(name)

    def cook(self, force=False):
        self.cooked = bool(force)

    def errors(self):
        return ()

    def warnings(self):
        return ()

    def messages(self):
        return ()

    def inputConnections(self):
        return tuple(self._connections)

    def inputDataTypes(self):
        return tuple(self._input_types)

    def outputDataTypes(self):
        return tuple(self._output_types)


class FakeText:
    def __init__(self, bindings, runover="attribute"):
        self.bindings = bindings
        self.runover = runover

    def oclExtractBindings(self, _code):
        return self.bindings

    def oclExtractRunOver(self, _code):
        return self.runover


class FakeHipFile:
    def hasUnsavedChanges(self):
        return False

    def path(self):
        return "C:/project/test.hip"


class FakeUndos:
    @contextlib.contextmanager
    def group(self, _label):
        yield


def _binding(name, binding_type, **overrides):
    row = {
        "name": name,
        "type": binding_type,
        "portname": name,
        "precision": "32",
        "optional": False,
        "readable": True,
        "writeable": False,
        "attribclass": "point",
        "attribtype": "float",
        "attribsize": 3,
        "layertype": "RGBA",
    }
    row.update(overrides)
    return row


def _load_runtime(monkeypatch, node, bindings, extra_nodes=()):
    nodes = {item.path(): item for item in (node, *extra_nodes)}
    hou = ModuleType("hou")
    hou.Node = FakeNode
    hou.Parm = type("UnusedParm", (), {})
    hou.NodeType = FakeNodeType
    hou.session = SimpleNamespace()
    hou.hipFile = FakeHipFile()
    hou.undos = FakeUndos()
    hou.applicationVersionString = lambda: "22.0.368"
    hou.applicationVersion = lambda: (22, 0, 368)
    hou.node = nodes.get
    hou.text = FakeText(bindings)

    hdefereval = ModuleType("hdefereval")
    hdefereval.executeInMainThreadWithResult = lambda callback: callback()
    monkeypatch.setitem(__import__("sys").modules, "hou", hou)
    monkeypatch.setitem(__import__("sys").modules, "hdefereval", hdefereval)
    namespace = {}
    exec(RUNTIME_SOURCE, namespace, namespace)
    return namespace["_houdini_codemode_execute_json"]


def _execute(runtime, source):
    request = ExecutionRequest.from_inputs(source, run_id="opencl-test")
    return json.loads(runtime(request.to_json()))


def _sop_node(current_type="attribute"):
    return FakeNode(
        "/obj/geo1/opencl1",
        "opencl",
        "Sop",
        {
            "kernelcode": FakeParm("#bind point P float3\n@KERNEL {}"),
            "usecode": FakeParm(True),
            "atbinding": FakeParm(True),
            "bindings": FakeParm(2),
            "bindings1_name": FakeParm("P"),
            "bindings1_type": FakeParm(current_type),
            "bindings2_name": FakeParm("amplitude"),
            "bindings2_type": FakeParm("float"),
        },
    )


def test_opencl_sop_validate_compact_and_stale_details(monkeypatch) -> None:
    bindings = [
        _binding("P", "attribute", writeable=True),
        _binding("amplitude", "float"),
    ]
    clean_node = _sop_node()
    runtime = _load_runtime(monkeypatch, clean_node, bindings)

    clean = _execute(runtime, "result.emit(ctx.opencl.validate('/obj/geo1/opencl1'))")

    assert clean["ok"] is True
    assert clean_node.cooked is True
    assert clean["data"]["value"] == {
        "binding_cols": ["name", "type", "direction"],
        "binding_count": 2,
        "bindings": [["P", "attribute", "inout"], ["amplitude", "float", "parm"]],
        "clean": True,
        "context": "sop",
        "invalid_connection_count": 0,
        "missing_required_count": 0,
        "node_path": "/obj/geo1/opencl1",
        "runover": "attribute",
        "sync_required": False,
    }

    stale_node = _sop_node(current_type="float")
    runtime = _load_runtime(monkeypatch, stale_node, bindings)
    stale = _execute(
        runtime,
        "result.emit(ctx.opencl.validate('/obj/geo1/opencl1', details=True))",
    )
    value = stale["data"]["value"]
    assert value["ok"] is False
    assert value["sync_required"] is True
    assert value["current_bindings"][0]["type"] == "float"
    assert value["desired_bindings"][0]["type"] == "attribute"


def test_opencl_validate_rejects_invalid_bvh_directives(monkeypatch) -> None:
    node = _sop_node()
    node._parms["kernelcode"] = FakeParm(
        "#bind point P float3 pointbvhmask=active\n@KERNEL {}"
    )
    runtime = _load_runtime(monkeypatch, node, [_binding("P", "attribute")])

    response = _execute(runtime, "result.emit(ctx.opencl.validate('/obj/geo1/opencl1'))")

    assert response["ok"] is False
    assert response["error"]["type"] == "ValueError"
    assert "pointbvhmask" in response["error"]["message"]


def test_opencl_dop_and_cop_validation_paths(monkeypatch) -> None:
    dop_binding = _binding("density", "scalarfield")
    dop = FakeNode(
        "/obj/dopnet1/gasopencl1",
        "gasopencl",
        "Dop",
        {
            "kernelcode": FakeParm("kernel"),
            "usecode": FakeParm(True),
            "atbinding": FakeParm(True),
            "paramcount": FakeParm(1),
            "parameter1Name": FakeParm("density"),
            "parameter1Type": FakeParm("scalarfield"),
        },
    )
    runtime = _load_runtime(monkeypatch, dop, [dop_binding])
    dop_response = _execute(runtime, "result.emit(ctx.opencl.validate('/obj/dopnet1/gasopencl1'))")
    assert dop_response["data"]["value"]["clean"] is True
    assert dop_response["data"]["value"]["context"] == "dop"

    source = FakeNode("/obj/copnet1/source", "source", "Cop2")
    source._output_types = ["RGBA"]
    cop = FakeNode(
        "/obj/copnet1/opencl1",
        "opencl",
        "Cop2",
        {
            "kernelcode": FakeParm("kernel"),
            "usecode": FakeParm(True),
            "atbinding": FakeParm(True),
            "inputs": FakeParm(1),
            "input1_name": FakeParm("image"),
            "input1_type": FakeParm("RGBA"),
            "input1_optional": FakeParm(False),
            "outputs": FakeParm(1),
            "output1_name": FakeParm("image"),
            "output1_type": FakeParm("RGBA"),
            "bindings": FakeParm(0),
        },
    )
    cop._input_types = ["RGBA"]
    cop._connections = [FakeConnection(source)]
    layer = _binding("image", "layer", writeable=True)
    runtime = _load_runtime(monkeypatch, cop, [layer], extra_nodes=(source,))
    cop_response = _execute(
        runtime,
        "result.emit(ctx.opencl.validate('/obj/copnet1/opencl1', details=True))",
    )
    value = cop_response["data"]["value"]
    assert value["context"] == "cop"
    assert value["ok"] is True
    assert value["signature_matches_kernel"] is True
    assert value["inputs"][0]["compatible"] is True
