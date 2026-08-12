from __future__ import annotations

import contextlib
import json
from types import ModuleType, SimpleNamespace

from houdini_codemode.protocol import ExecutionRequest
from houdini_codemode.runtime_source import RUNTIME_SOURCE


class FakeCategory:
    def __init__(self, name: str = "Object") -> None:
        self._name = name

    def name(self):
        return self._name


class FakeNodeType:
    def __init__(self, name: str, category: str = "Object") -> None:
        self._name = name
        self._category = FakeCategory(category)

    def name(self):
        return self._name

    def category(self):
        return self._category

    def definition(self):
        return None


class FakeConnection:
    def __init__(self, source, destination, output_index=0, input_index=0) -> None:
        self._source = source
        self._destination = destination
        self._output_index = output_index
        self._input_index = input_index

    def inputNode(self):
        return self._source

    def outputNode(self):
        return self._destination

    def outputIndex(self):
        return self._output_index

    def inputIndex(self):
        return self._input_index


class FakeParmTemplateType:
    def __init__(self, name: str) -> None:
        self._name = name

    def name(self):
        return self._name


class FakeParmTemplate:
    def __init__(self, type_name: str) -> None:
        self._type = FakeParmTemplateType(type_name)

    def type(self):
        return self._type


class FakeParmTuple:
    def __init__(self, name: str, members) -> None:
        self._name = name
        self._members = list(members)

    def name(self):
        return self._name

    def __iter__(self):
        return iter(self._members)

    def __len__(self):
        return len(self._members)

    def __getitem__(self, index):
        return self._members[index]


class FakeRamp:
    def keys(self):
        return (0.0, 0.5, 1.0)

    def basis(self):
        return ("hou.rampBasis.Linear", "hou.rampBasis.Linear", "hou.rampBasis.Constant")


class FakeParm:
    def __init__(
        self,
        node,
        name: str,
        value,
        *,
        type_name: str = "Float",
        is_default: bool = True,
        value_error: Exception | None = None,
    ) -> None:
        self._node = node
        self._name = name
        self._value = value
        self._type_name = type_name
        self._is_default = is_default
        self._value_error = value_error
        self._tuple = FakeParmTuple(name, [self])

    def path(self):
        return self._node.path() + "/" + self._name

    def name(self):
        return self._name

    def node(self):
        return self._node

    def tuple(self):
        return self._tuple

    def parmTemplate(self):
        return FakeParmTemplate(self._type_name)

    def isAtDefault(self):
        return self._is_default

    def valueAsData(self):
        if self._value_error is not None:
            raise self._value_error
        return self._value

    def multiParmInstances(self):
        return ()

    def keyframes(self):
        return ()

    def eval(self):
        return self._value


class FakeNode:
    def __init__(self, path: str, type_name: str, *, network: bool = False) -> None:
        self._path = path
        self._type = FakeNodeType(type_name)
        self._network = network
        self._children = []
        self._parms = []
        self._inputs = []
        self._outputs = []
        self._input_connections = []
        self._output_connections = []

    def path(self):
        return self._path

    def name(self):
        return self._path.rsplit("/", 1)[-1]

    def type(self):
        return self._type

    def children(self):
        return tuple(self._children)

    def inputs(self):
        return tuple(self._inputs)

    def outputs(self):
        return tuple(self._outputs)

    def inputConnections(self):
        return tuple(self._input_connections)

    def outputConnections(self):
        return tuple(self._output_connections)

    def parms(self):
        return tuple(self._parms)

    def parmsAsData(self, **_kwargs):
        return None

    def parm(self, name):
        return next((parm for parm in self._parms if parm.name() == name), None)

    def parmTuple(self, name):
        for parm in self._parms:
            if parm.tuple().name() == name:
                return parm.tuple()
        return None

    def isDisplayFlagSet(self):
        return self.name() == "geo2"

    def isRenderFlagSet(self):
        return False

    def isBypassed(self):
        return False

    def isNetwork(self):
        return self._network

    def errors(self):
        return ()

    def warnings(self):
        return ()


class FakeHipFile:
    def hasUnsavedChanges(self):
        return False

    def path(self):
        return "C:/project/test.hip"


class FakeUndos:
    @contextlib.contextmanager
    def group(self, _label):
        yield


def _connect(source: FakeNode, destination: FakeNode) -> None:
    connection = FakeConnection(source, destination)
    source._outputs.append(destination)
    source._output_connections.append(connection)
    destination._inputs.append(source)
    destination._input_connections.append(connection)


def _scene():
    root = FakeNode("/obj", "obj", network=True)
    geo1 = FakeNode("/obj/geo1", "geo")
    geo2 = FakeNode("/obj/geo2", "geo")
    root._children.extend([geo1, geo2])
    _connect(geo1, geo2)

    tx = FakeParm(geo1, "tx", (1.0, 2.0), is_default=False)
    ty = FakeParm(geo1, "ty", (1.0, 2.0))
    translate = FakeParmTuple("t", [tx, ty])
    tx._tuple = translate
    ty._tuple = translate
    text = FakeParm(geo1, "text", "x" * 200, type_name="String")
    ramp = FakeParm(geo1, "ramp", FakeRamp(), type_name="Ramp")
    broken = FakeParm(
        geo1,
        "broken",
        None,
        value_error=RuntimeError("value unavailable"),
    )
    button = FakeParm(geo1, "execute", None, type_name="Button")
    geo1._parms.extend([tx, ty, text, ramp, broken, button])
    return root, geo1, geo2


def _load_runtime(monkeypatch, scene=None):
    root, geo1, geo2 = scene or _scene()
    nodes = {}
    pending = [root]
    while pending:
        node = pending.pop()
        nodes[node.path()] = node
        pending.extend(node.children())
    hou = ModuleType("hou")
    hou.Node = FakeNode
    hou.Parm = FakeParm
    hou.NodeType = FakeNodeType
    hou.session = SimpleNamespace()
    hou.hipFile = FakeHipFile()
    hou.undos = FakeUndos()
    hou.applicationVersionString = lambda: "22.0.368"
    hou.node = nodes.get

    hdefereval = ModuleType("hdefereval")
    hdefereval.executeInMainThreadWithResult = lambda callback: callback()
    monkeypatch.setitem(__import__("sys").modules, "hou", hou)
    monkeypatch.setitem(__import__("sys").modules, "hdefereval", hdefereval)
    namespace = {}
    exec(RUNTIME_SOURCE, namespace, namespace)
    return namespace["_houdini_codemode_execute_json"]


def _execute(runtime, source):
    request = ExecutionRequest.from_inputs(source, run_id="inspection-test")
    return json.loads(runtime(request.to_json()))


def test_context_capabilities_are_bounded_and_targeted_help_is_callable(monkeypatch) -> None:
    runtime = _load_runtime(monkeypatch)

    response = _execute(
        runtime,
        "catalog = ctx.capabilities(query='image', max_items=2)\n"
        "detail = ctx.help('ctx.cop_files.export_image')\n"
        "result.emit({'catalog': catalog, 'detail': detail})",
    )

    assert response["ok"] is True
    value = response["data"]["value"]
    assert value["catalog"]["schema"] == "houdini-codemode.ctx-capabilities/v1"
    assert value["catalog"]["globals"] == ["hou", "ctx", "args", "result"]
    assert value["catalog"]["count"] <= 2
    assert value["detail"]["name"] == "ctx.cop_files.export_image"
    assert value["detail"]["methods"][0]["effect"] == "file-write"
    assert "overwrite=False" in value["detail"]["methods"][0]["signature"]


def test_context_registry_covers_every_public_service_and_method(monkeypatch) -> None:
    runtime = _load_runtime(monkeypatch)

    response = _execute(
        runtime,
        "catalog = ctx.capabilities(max_items=100)\n"
        "registered = {item['name'].split('.', 1)[1] for item in catalog['services']}\n"
        "public = {name for name in dir(ctx) if not name.startswith('_')} - {'capabilities', 'help'}\n"
        "method_mismatches = {}\n"
        "for service_name in sorted(registered):\n"
        "    detail = ctx.help('ctx.' + service_name)\n"
        "    expected = {item['signature'].split('(', 1)[0] for item in detail['methods']}\n"
        "    actual = {name for name in dir(getattr(ctx, service_name)) if not name.startswith('_')}\n"
        "    if expected != actual:\n"
        "        method_mismatches[service_name] = {'expected': sorted(expected), 'actual': sorted(actual)}\n"
        "result.emit({'missing_services': sorted(public - registered), "
        "'stale_services': sorted(registered - public), 'method_mismatches': method_mismatches})",
    )

    assert response["ok"] is True
    assert response["data"]["value"] == {
        "missing_services": [],
        "stale_services": [],
        "method_mismatches": {},
    }


def test_project_parms_preserves_order_and_distinguishes_outcomes(monkeypatch) -> None:
    runtime = _load_runtime(monkeypatch)

    response = _execute(
        runtime,
        "result.emit(ctx.parms.project('/obj/geo1', ['t', 'missing', 'broken']))",
    )

    assert response["ok"] is True
    projection = response["data"]["value"]
    assert [item["p"] for item in projection["items"]] == ["t", "missing", "broken"]
    assert [item["status"] for item in projection["items"]] == ["ok", "missing", "error"]
    assert projection["items"][0]["v"] == {
        "kind": "sequence",
        "item_count": 2,
        "items": [1.0, 2.0],
        "truncated": False,
    }
    assert projection["items"][0]["default"] is False
    assert projection["counts"] == {"requested": 3, "ok": 1, "missing": 1, "errors": 1}


def test_parm_list_is_tuple_collapsed_bounded_and_does_not_use_parms_as_data(monkeypatch) -> None:
    runtime = _load_runtime(monkeypatch)

    response = _execute(
        runtime,
        "result.emit(ctx.parms.list('/obj/geo1', max_parms=2, max_items=2))",
    )

    assert response["ok"] is True
    listing = response["data"]["value"]
    assert listing["cols"] == ["p", "t", "v", "f"]
    assert [row[0] for row in listing["rows"]] == ["t", "text"]
    assert listing["rows"][1][2] == {
        "kind": "string",
        "length": 200,
        "preview": "x" * 40,
        "truncated": True,
    }
    assert listing["total"] == 4
    assert listing["truncated"] is True


def test_node_discovery_neighbors_and_network_summary_match_cli_shapes(monkeypatch) -> None:
    runtime = _load_runtime(monkeypatch)

    response = _execute(
        runtime,
        "found = ctx.nodes.find('/obj', type_name='geo')\n"
        "graph = ctx.nodes.neighbors('/obj/geo2', direction='upstream')\n"
        "summary = ctx.nodes.network_summary('/obj', include_boundaries=True)\n"
        "result.emit({'found': found, 'graph': graph, 'summary': summary})",
    )

    assert response["ok"] is True
    value = response["data"]["value"]
    assert value["found"]["nodes"]["cols"] == ["p", "t", "cc", "in", "out", "f"]
    assert [row[0] for row in value["found"]["nodes"]["rows"]] == ["geo1", "geo2"]
    assert value["graph"]["nodes"]["rows"] == [
        [0, "geo2", "geo", "d"],
        [1, "geo1", "geo", ""],
    ]
    assert value["graph"]["edges"]["rows"] == [[1, 0, 0, 0]]
    summary = value["summary"]
    assert summary["counts"]["nodes"] == 2
    assert summary["type_histogram"] == [{"count": 2, "type": "geo"}]
    assert summary["boundaries"]["entry_nodes"]["rows"] == [["geo1", "geo"]]
    assert summary["boundaries"]["terminal_nodes"]["rows"] == [["geo2", "geo"]]


def test_inspection_helpers_validate_local_work_limits(monkeypatch) -> None:
    runtime = _load_runtime(monkeypatch)

    response = _execute(runtime, "result.emit(ctx.nodes.find('/obj', max_nodes=0))")

    assert response["ok"] is False
    assert response["error"]["category"] == "execution"
    assert response["error"]["type"] == "ValueError"
    assert "max_nodes" in response["error"]["message"]


def test_large_scene_fixture_stays_bounded_before_response_normalization(monkeypatch) -> None:
    root = FakeNode("/obj", "obj", network=True)
    children = [
        FakeNode(f"/obj/node_{index:04d}", "null" if index % 2 else "geo")
        for index in range(2_000)
    ]
    root._children.extend(children)
    runtime = _load_runtime(monkeypatch, scene=(root, children[0], children[1]))

    response = _execute(
        runtime,
        "found = ctx.nodes.find('/obj', max_nodes=50)\n"
        "summary = ctx.nodes.network_summary('/obj', max_nodes=75, top_types=2)\n"
        "result.emit({'found': found, 'summary': summary})",
    )

    assert response["ok"] is True
    value = response["data"]["value"]
    assert value["found"]["visited_nodes"] == 50
    assert value["found"]["nodes"]["count"] == 49
    assert value["found"]["truncated"] is True
    assert value["summary"]["visited_nodes"] == 75
    assert value["summary"]["truncated"] is True
    assert response["meta"]["result_bytes"] < 20_000
    assert response["meta"]["truncations"] == []
