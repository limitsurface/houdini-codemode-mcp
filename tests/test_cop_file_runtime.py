from __future__ import annotations

import contextlib
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

from houdini_codemode.protocol import ExecutionRequest
from houdini_codemode.runtime_cop_file_source import COP_FILE_SOURCE
from houdini_codemode.runtime_source import RUNTIME_SOURCE


class FakeCategory:
    def name(self):
        return "Cop2"


class FakeNodeType:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name

    def category(self):
        return FakeCategory()


class FakeTemplate:
    def __init__(self, items):
        self._items = items

    def menuItems(self):
        return self._items


class FakeParm:
    def __init__(self, value=None, menu_items=(), callback=None):
        self.value = value
        self._menu_items = menu_items
        self._callback = callback
        self.pressed = False

    def set(self, value):
        self.value = value

    def eval(self):
        return self.value

    def parmTemplate(self):
        return FakeTemplate(self._menu_items)

    def pressButton(self):
        self.pressed = True
        if self._callback:
            self._callback()


class FakeNode:
    def __init__(self, path, type_name, parent=None):
        self._path = path
        self._type = FakeNodeType(type_name)
        self._parent = parent
        self._children = []
        self._parms = {}
        self.destroyed = False
        self.display = False
        self.render = False
        self._output_names = ["C"]
        self._output_labels = ["Color"]
        self._output_types = ["RGBA"]

    def path(self):
        return self._path

    def name(self):
        return self._path.rsplit("/", 1)[-1]

    def type(self):
        return self._type

    def parent(self):
        return self._parent

    def parm(self, name):
        return self._parms.get(name)

    def node(self, name):
        return next((item for item in self._children if item.name() == name), None)

    def createNode(self, type_name, name):
        child = FakeNode(self.path().rstrip("/") + "/" + name, type_name, self)
        self._children.append(child)
        if type_name == "rop_image":
            def write_file():
                target = Path(child.parm("copoutput").value)
                target.write_bytes(b"cop-image")

            child._parms = {
                "coppath": FakeParm(),
                "copoutput": FakeParm(),
                "colorconversion": FakeParm(0, ("raw", "bakeocio")),
                "mkpath": FakeParm(),
                "outputaovs": FakeParm(),
                "aov1": FakeParm(),
                "useport1": FakeParm(),
                "port1": FakeParm(),
                "ociodisplay": FakeParm(),
                "ocioview": FakeParm(),
                "execute": FakeParm(callback=write_file),
            }
        elif type_name == "file":
            child._parms = {
                "filename": FakeParm(),
                "colorspace": FakeParm("ocio", ("ocio", "raw")),
                "reload": FakeParm(),
                "addaovs": FakeParm(),
            }
        return child

    def destroy(self):
        self.destroyed = True
        if self._parent:
            self._parent._children.remove(self)

    def outputNames(self):
        return self._output_names

    def outputLabels(self):
        return self._output_labels

    def outputDataTypes(self):
        return self._output_types

    def outputs(self):
        return ()

    def inputConnections(self):
        return ()

    def layer(self, _index=0):
        return object()

    def setDisplayFlag(self, value):
        self.display = value

    def setRenderFlag(self, value):
        self.render = value


class FakeHipFile:
    def hasUnsavedChanges(self):
        return False

    def path(self):
        return "C:/project/test.hip"


class FakeUndos:
    @contextlib.contextmanager
    def group(self, _label):
        yield


def _runtime(monkeypatch, root):
    copnet = FakeNode("/obj/cops", "copnet")
    source = FakeNode("/obj/cops/constant1", "constant", copnet)
    copnet._children.append(source)
    nodes = {copnet.path(): copnet, source.path(): source}
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
    hou.expandString = lambda value: value
    hdefereval = ModuleType("hdefereval")
    hdefereval.executeInMainThreadWithResult = lambda callback: callback()
    monkeypatch.setitem(__import__("sys").modules, "hou", hou)
    monkeypatch.setitem(__import__("sys").modules, "hdefereval", hdefereval)
    namespace = {}
    exec(RUNTIME_SOURCE + "\n" + COP_FILE_SOURCE, namespace, namespace)
    return namespace["_houdini_codemode_execute_json"], copnet, source


def _execute(runtime, source):
    request = ExecutionRequest.from_inputs(source, run_id="cop-file-test")
    return json.loads(runtime(request.to_json()))


def test_export_requires_explicit_non_overwriting_output_and_cleans_helper(monkeypatch, tmp_path):
    runtime, parent, _source = _runtime(monkeypatch, tmp_path)
    output = tmp_path / "render.exr"
    response = _execute(
        runtime,
        "result.emit(ctx.cop_files.export_image('/obj/cops/constant1', {!r}, max_bytes=1024))".format(str(output)),
    )

    assert response["ok"] is True
    value = response["data"]["value"]
    assert value["file"] == {"path": str(output.resolve()), "bytes": 9}
    assert value["temporary_helper"]["removed"] is True
    assert value["hip_saved"] is False
    assert parent._children == [_source]
    assert response["meta"]["mutation"]["events"] == [{
        "kind": "cop.image_export",
        "helper": "ctx.cop_files.export_image",
        "node_path": "/obj/cops/constant1",
        "output_path": str(output.resolve()),
    }]

    blocked = _execute(
        runtime,
        "result.emit(ctx.cop_files.export_image('/obj/cops/constant1', {!r}))".format(str(output)),
    )
    assert blocked["ok"] is False
    assert blocked["error"]["type"] == "FileExistsError"

    original_bytes = output.read_bytes()
    capped = _execute(
        runtime,
        "result.emit(ctx.cop_files.export_image('/obj/cops/constant1', {!r}, overwrite=True, max_bytes=1))".format(str(output)),
    )
    assert capped["ok"] is False
    assert capped["error"]["type"] == "ValueError"
    assert output.read_bytes() == original_bytes
    assert parent._children == [_source]

    new_target = tmp_path / "too_large.exr"
    new_target_failure = _execute(
        runtime,
        "result.emit(ctx.cop_files.export_image('/obj/cops/constant1', {!r}, max_bytes=1))".format(str(new_target)),
    )
    assert new_target_failure["ok"] is False
    assert not new_target.exists()
    assert not list(tmp_path.glob(".too_large.hcm-*.exr"))


def test_import_validates_file_cap_then_creates_and_reports_mutation(monkeypatch, tmp_path):
    runtime, parent, _source = _runtime(monkeypatch, tmp_path)
    image = tmp_path / "albedo.png"
    image.write_bytes(b"pixels")
    response = _execute(
        runtime,
        "result.emit(ctx.cop_files.import_image({!r}, '/obj/cops', colorspace='raw', set_display=True))".format(str(image)),
    )

    assert response["ok"] is True
    value = response["data"]["value"]
    imported = parent.node("hcm_image_albedo")
    assert value["file"] == {"path": str(image.resolve()), "bytes": 6}
    assert imported.parm("filename").value == str(image.resolve())
    assert imported.parm("colorspace").value == "raw"
    assert imported.display is True and imported.render is True
    assert value["hip_saved"] is False
    assert response["meta"]["mutation"]["events"][0]["kind"] == "cop.image_import"

    capped = _execute(
        runtime,
        "result.emit(ctx.cop_files.import_image({!r}, '/obj/cops', max_bytes=2))".format(str(image)),
    )
    assert capped["ok"] is False
    assert capped["error"]["type"] == "ValueError"
    assert parent._children == [_source, imported]


def test_export_rejects_missing_parent_and_mode_extension(monkeypatch, tmp_path):
    runtime, parent, _source = _runtime(monkeypatch, tmp_path)
    missing_parent = tmp_path / "missing" / "render.exr"
    response = _execute(
        runtime,
        "result.emit(ctx.cop_files.export_image('/obj/cops/constant1', {!r}))".format(str(missing_parent)),
    )
    assert response["ok"] is False
    assert "parent directory" in response["error"]["message"]
    assert parent._children == [_source]

    bad_extension = _execute(
        runtime,
        "result.emit(ctx.cop_files.export_image('/obj/cops/constant1', {!r}, mode='raw'))".format(str(tmp_path / "render.png")),
    )
    assert bad_extension["ok"] is False
    assert "not allowed" in bad_extension["error"]["message"]
