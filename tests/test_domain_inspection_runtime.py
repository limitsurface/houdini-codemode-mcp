from __future__ import annotations

import sys
import time
from types import ModuleType, SimpleNamespace

import pytest

from houdini_codemode.runtime_cop_source import COP_SOURCE
from houdini_codemode.runtime_geometry_source import GEOMETRY_SOURCE
from houdini_codemode.runtime_lop_source import LOP_SOURCE


class FakeAttrib:
    def __init__(self, name, size, data_type="hou.attribData.Float", array=False):
        self._name = name
        self._size = size
        self._data_type = data_type
        self._array = array

    def name(self):
        return self._name

    def size(self):
        return self._size

    def dataType(self):
        return self._data_type

    def isArrayType(self):
        return self._array


class FakeElement:
    def __init__(self, values):
        self.values = values

    def attribValue(self, attrib):
        return self.values[attrib.name()]


class FakePrim(FakeElement):
    def __init__(self, values, vertex_count=4, type_name="Polygon"):
        super().__init__(values)
        self._vertices = [FakeElement(values) for _ in range(vertex_count)]
        self._type_name = type_name

    def vertices(self):
        return self._vertices

    def type(self):
        return SimpleNamespace(name=lambda: self._type_name)


class FakeGeometry:
    def __init__(self):
        self.position = FakeAttrib("P", 3)
        self.name = FakeAttrib("name", 1, "hou.attribData.String")
        self.id = FakeAttrib("id", 1, "hou.attribData.Int")
        self.points = [
            FakeElement({"P": (0.0, 0.0, 0.0)}),
            FakeElement({"P": (1.0, 0.0, 0.0)}),
            FakeElement({"P": (1.0, 1.0, 0.0)}),
        ]
        self.prims = [FakePrim({"name": "piece"}, 3)]

    def pointCount(self):
        return len(self.points)

    def primCount(self):
        return len(self.prims)

    def vertexCount(self):
        return sum(len(prim.vertices()) for prim in self.prims)

    def iterPoints(self):
        return iter(self.points)

    def iterPrims(self):
        return iter(self.prims)

    def pointAttribs(self):
        return [self.position, self.id]

    def primAttribs(self):
        return [self.name]

    def vertexAttribs(self):
        return []

    def globalAttribs(self):
        return []

    def findPointAttrib(self, name):
        return self.position if name == "P" else self.id if name == "id" else None

    def findPrimAttrib(self, name):
        return self.name if name == "name" else None

    def findVertexAttrib(self, _name):
        return None

    def findGlobalAttrib(self, _name):
        return None


class FakeGeometryNode:
    def __init__(self):
        self.geo = FakeGeometry()

    def path(self):
        return "/obj/geo1/OUT"

    def geometry(self):
        return self.geo


def _positive(value, name, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(name + " must be an integer")
    if value <= 0:
        raise ValueError(name + " must be positive")
    return min(value, maximum)


def test_geometry_service_bounds_definitions_topology_and_values() -> None:
    node = FakeGeometryNode()
    namespace = {"_hcm_resolve_node": lambda value: node if isinstance(value, str) else value}
    exec(GEOMETRY_SOURCE, namespace)
    service = namespace["_HCMGeometryService"]()

    summary = service.summary(node, topology=True, max_prims=1, max_histogram=1)
    attributes = service.attributes(node, max_attribs=2)
    values = service.get(node, "P", limit=2)

    assert summary["counts"] == {"point": 3, "prim": 1, "vertex": 3}
    assert summary["prim_types"]["rows"] == [["Polygon", 1]]
    assert attributes["count"] == 2
    assert attributes["meta"]["total"] == 3
    assert attributes["meta"]["truncated"] is True
    assert values["values"][1]["value"] == (1.0, 0.0, 0.0)
    assert values["meta"] == {
        "limit": 2,
        "returned": 2,
        "total_elements": 3,
        "truncated": True,
    }


class FakeRect:
    def min(self):
        return (0, 0)

    def max(self):
        return (3, 1)

    def size(self):
        return (4, 2)


class FakeLayer:
    def bufferResolution(self):
        return (4, 2)

    def dataWindow(self):
        return FakeRect()

    def displayWindow(self):
        return FakeRect()

    def pixelScale(self):
        return (1.0, 1.0)

    def pixelAspectRatio(self):
        return 1.0

    def channelCount(self):
        return 4

    def storageType(self):
        return "Float32"

    def border(self):
        return "Clamp"

    def typeInfo(self):
        return "Color"

    def isConstant(self):
        return True

    def onCPU(self):
        return True

    def onGPU(self):
        return False

    def storesIntegers(self):
        return False

    def cameraPosition(self):
        return (0.0, 0.0, 1.0)

    def projection(self):
        return "Perspective"

    def focalLength(self):
        return 50.0

    def aperture(self):
        return 41.4214

    def clippingRange(self):
        return (0.1, 1000.0)

    def pixelToBuffer(self, point):
        return point

    def bufferIndex(self, x, y):
        return (x / 4.0, y / 2.0, 0.5, 1.0)


class FakeCopNode:
    def path(self):
        return "/img/cops/constant1"

    def outputNames(self):
        return ("C",)

    def outputLabels(self):
        return ("Color",)

    def outputDataTypes(self):
        return ("Image",)

    def outputs(self):
        return ()

    def inputConnections(self):
        return ()

    def type(self):
        return SimpleNamespace(name=lambda: "constant")

    def layer(self, _index=0):
        return FakeLayer()


def test_cop_service_returns_bounded_layer_info_and_samples() -> None:
    node = FakeCopNode()
    namespace = {
        "_hcm_resolve_node": lambda value: node if isinstance(value, str) else value,
        "_hcm_geometry_positive": _positive,
        "_hcm_error_text": lambda exc, _limit: str(exc),
    }
    exec(COP_SOURCE, namespace)
    service = namespace["_HCMCopService"]()

    info = service.info(node, output="Color")
    sampled = service.sample(node, [{"x": 1, "y": 1}], max_points=1)

    assert info["output_name"] == "C"
    assert info["resolution"]["buffer"] == [4, 2]
    assert info["storage"]["is_constant"] is True
    assert sampled["samples"] == [
        {
            "x": 1,
            "y": 1,
            "buffer_x": 1,
            "buffer_y": 1,
            "value": [0.25, 0.5, 0.5, 1.0],
        }
    ]
    with pytest.raises(ValueError, match="exceeding the 1-point limit"):
        service.sample(node, [(0, 0), (1, 1)], max_points=1)


class FakeUsdPath:
    def __init__(self, text, depth):
        self.text = text
        self.pathElementCount = depth

    def __str__(self):
        return self.text


class FakeUsdPrim:
    def __init__(self, path, depth, type_name="Xform"):
        self.path = FakeUsdPath(path, depth)
        self.type_name = type_name

    def GetPath(self):
        return self.path

    def IsActive(self):
        return True

    def IsInstance(self):
        return False

    def GetTypeName(self):
        return self.type_name

    def IsA(self, _schema):
        return False

    def HasAPI(self, _schema):
        return False

    def GetAppliedSchemas(self):
        return ()

    def HasAuthoredReferences(self):
        return False

    def HasAuthoredPayloads(self):
        return False


class FakePrimIterator:
    def __init__(self, items):
        self.items = iter(items)

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.items)

    def PruneChildren(self):
        return None


class FakeStage:
    def __init__(self):
        self.prims = [FakeUsdPrim("/World", 1), FakeUsdPrim("/World/geo", 2, "Mesh")]
        self.root = SimpleNamespace(identifier="anon:test", subLayerPaths=[])

    def GetPrototypes(self):
        return ()

    def GetDefaultPrim(self):
        return None

    def GetRootLayer(self):
        return self.root

    def GetTimeCodesPerSecond(self):
        return 24.0

    def GetMetadata(self, _name):
        return None


class FakeLopNode:
    def __init__(self):
        self.cooks = 0

    def path(self):
        return "/stage/test"

    def type(self):
        return SimpleNamespace(category=lambda: SimpleNamespace(name=lambda: "Lop"))

    def outputNames(self):
        return ("stage",)

    def cookCount(self):
        return self.cooks

    def needsToCook(self):
        return self.cooks == 0

    def stage(self, output_index=0):
        assert output_index == 0
        self.cooks += 1
        return FakeStage()


def test_lop_summary_caps_traversal_and_records_cook(monkeypatch) -> None:
    pxr = ModuleType("pxr")
    pxr.Usd = SimpleNamespace(
        PrimRange=SimpleNamespace(Stage=lambda stage, _predicate: FakePrimIterator(stage.prims)),
        PrimAllPrimsPredicate=object(),
    )
    pxr.UsdGeom = SimpleNamespace(
        Camera=object(),
        GetStageUpAxis=lambda _stage: "Y",
        GetStageMetersPerUnit=lambda _stage: 1.0,
    )
    pxr.UsdLux = SimpleNamespace(LightAPI=object())
    pxr.UsdRender = SimpleNamespace(
        Settings=SimpleNamespace(
            GetStageRenderSettings=lambda _stage: None,
            Get=lambda _stage, _path: None,
        ),
        Product=object(),
    )
    pxr.UsdShade = SimpleNamespace(Material=object())
    monkeypatch.setitem(sys.modules, "pxr", pxr)
    node = FakeLopNode()
    namespace = {
        "_hcm_resolve_node": lambda value: node if isinstance(value, str) else value,
        "_hcm_geometry_positive": _positive,
        "_hcm_time": time,
    }
    exec(LOP_SOURCE, namespace)
    events = []
    service = namespace["_HCMLopService"](events)

    summary = service.summary(node, max_prims=1, include_paths=True, path_limit=1)

    assert summary["counts"]["prims"] == 1
    assert summary["meta"]["truncated"] is True
    assert summary["paths"]["top_level"]["paths"] == ["/World"]
    assert summary["cook"]["occurred"] is True
    assert events[0]["kind"] == "houdini.cook"
