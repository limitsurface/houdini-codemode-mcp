from __future__ import annotations

import contextlib
import json
from types import ModuleType, SimpleNamespace

from houdini_codemode.protocol import ExecutionRequest
from houdini_codemode.runtime_source import RUNTIME_SOURCE


class FakeNode:
    def __init__(self, path):
        self._path = path

    def path(self):
        return self._path


class FakeViewport:
    def name(self):
        return "persp1"

    def type(self):
        return "Perspective"

    def camera(self):
        return None


class FakeViewer:
    def __init__(self, name="scene1"):
        self._name = name

    def name(self):
        return self._name

    def type(self):
        return "SceneViewer"

    def curViewport(self):
        return FakeViewport()

    def pwd(self):
        return FakeNode("/obj")

    def currentNode(self):
        return FakeNode("/obj/geo1")

    def currentState(self):
        return "select"


class FakeDesktop:
    def __init__(self, viewers):
        self._viewers = viewers

    def paneTabs(self):
        return list(self._viewers)

    def currentPaneTabs(self):
        return list(self._viewers)


class FakeHipFile:
    def hasUnsavedChanges(self):
        return False

    def path(self):
        return "C:/project/test.hip"


class FakeUndos:
    @contextlib.contextmanager
    def group(self, _label):
        yield


def _load_runtime(monkeypatch, viewers):
    hou = ModuleType("hou")
    hou.Node = FakeNode
    hou.Parm = type("FakeParm", (), {})
    hou.NodeType = type("FakeNodeType", (), {})
    hou.session = SimpleNamespace()
    hou.hipFile = FakeHipFile()
    hou.undos = FakeUndos()
    hou.applicationVersionString = lambda: "22.0.368"
    hou.node = lambda _path: None
    hou.frame = lambda: 24.0
    hou.expandString = lambda value: value
    hou.paneTabType = SimpleNamespace(SceneViewer="SceneViewer")
    hou.ui = SimpleNamespace(curDesktop=lambda: FakeDesktop(viewers))

    hdefereval = ModuleType("hdefereval")
    hdefereval.executeInMainThreadWithResult = lambda callback: callback()

    assetutils = ModuleType("husd.assetutils")

    def save_thumbnail(*, sceneviewer, frame, res, output):
        assert sceneviewer is viewers[0]
        assert frame == 24
        assert res == (640, 360)
        with open(output, "wb") as stream:
            stream.write(b"fake-png")

    assetutils.saveThumbnailFromViewer = save_thumbnail
    husd = ModuleType("husd")
    husd.assetutils = assetutils

    system_modules = __import__("sys").modules
    monkeypatch.setitem(system_modules, "hou", hou)
    monkeypatch.setitem(system_modules, "hdefereval", hdefereval)
    monkeypatch.setitem(system_modules, "husd", husd)
    monkeypatch.setitem(system_modules, "husd.assetutils", assetutils)

    namespace = {}
    exec(RUNTIME_SOURCE, namespace, namespace)
    return namespace["_houdini_codemode_execute_json"]


def _execute(runtime, source):
    request = ExecutionRequest.from_inputs(source, run_id="viewport-test")
    return json.loads(runtime(request.to_json()))


def test_capture_writes_bounded_png_and_reports_viewer(monkeypatch, tmp_path):
    viewer = FakeViewer()
    runtime = _load_runtime(monkeypatch, [viewer])
    output = tmp_path / "viewport.png"

    response = _execute(
        runtime,
        "result.emit(ctx.viewport.capture({!r}, width=640, height=360))".format(
            str(output)
        ),
    )

    assert response["ok"] is True
    value = response["data"]["value"]
    assert value["file"] == {"path": str(output.resolve()), "bytes": 8}
    assert value["frame"] == 24
    assert value["viewer"] == {
        "pane_name": "scene1",
        "viewport_name": "persp1",
        "viewport_type": "Perspective",
        "current_network": "/obj",
        "current_node": "/obj/geo1",
        "current_state": "select",
        "camera": None,
    }
    assert value["hip_saved"] is False
    assert response["meta"]["mutation"]["events"] == [{
        "kind": "viewport.capture",
        "helper": "ctx.viewport.capture",
        "output_path": str(output.resolve()),
        "pane_name": "scene1",
    }]


def test_capture_rejects_overwrite_and_ambiguous_viewers(monkeypatch, tmp_path):
    viewers = [FakeViewer("scene1"), FakeViewer("scene2")]
    runtime = _load_runtime(monkeypatch, viewers)
    output = tmp_path / "viewport.png"
    output.write_bytes(b"existing")

    overwrite = _execute(
        runtime, "result.emit(ctx.viewport.capture({!r}))".format(str(output))
    )
    assert overwrite["ok"] is False
    assert overwrite["error"]["type"] == "FileExistsError"

    output.unlink()
    ambiguous = _execute(
        runtime, "result.emit(ctx.viewport.capture({!r}))".format(str(output))
    )
    assert ambiguous["ok"] is False
    assert "Multiple Scene Viewers" in ambiguous["error"]["message"]
