from __future__ import annotations

from types import SimpleNamespace

import pytest

from houdini_codemode.runtime_hda_source import HDA_SOURCE


class FakeSection:
    def __init__(self, size):
        self._size = size

    def size(self):
        return self._size


class FakeCategory:
    def name(self):
        return "Sop"


class FakeNodeType:
    def __init__(self, name, definition=None):
        self._name = name
        self._definition = definition

    def name(self):
        return self._name

    def category(self):
        return FakeCategory()

    def definition(self):
        return self._definition


class FakeTemplate:
    def __init__(self, name, children=()):
        self._name = name
        self._children = children

    def name(self):
        return self._name

    def label(self):
        return self._name.title()

    def type(self):
        return SimpleNamespace(name=lambda: "Folder" if self._children else "Float")

    def parmTemplates(self):
        return self._children


class FakeDefinition:
    def __init__(self, type_name="acme::tool::1.0", library="C:/otls/tool.hda"):
        self._node_type = FakeNodeType(type_name, self)
        self._library = library

    def nodeType(self):
        return self._node_type

    def description(self):
        return "Acme Tool"

    def libraryFilePath(self):
        return self._library

    def version(self):
        return "1.0"

    def icon(self):
        return "SOP_tool"

    def minNumInputs(self):
        return 1

    def maxNumInputs(self):
        return 2

    def isPreferred(self):
        return True

    def isCurrent(self):
        return True

    def sections(self):
        return {"PythonModule": FakeSection(128), "ExtraFile": FakeSection(64)}

    def tools(self):
        return {"tool": object(), "second": object()}

    def parmTemplateGroup(self):
        return SimpleNamespace(
            entries=lambda: (FakeTemplate("main", (FakeTemplate("scale"),)),)
        )


class FakeNode:
    def __init__(self, definition):
        self._type = FakeNodeType("acme::tool::1.0", definition)

    def path(self):
        return "/obj/geo1/tool1"

    def type(self):
        return self._type

    def isLockedHDA(self):
        return True

    def matchesCurrentDefinition(self):
        return True

    def parent(self):
        return SimpleNamespace(path=lambda: "/obj/geo1")


def _positive(value, name, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(name + " must be an integer")
    if value <= 0:
        raise ValueError(name + " must be positive")
    return min(value, maximum)


def _namespace(definitions):
    node = FakeNode(definitions[0])
    def components(type_name):
        parts = type_name.split("::")
        return ("", parts[0], parts[1], parts[2]) if len(parts) == 3 else ("", "", type_name, "")

    hda = SimpleNamespace(
        componentsFromFullNodeTypeName=components,
        loadedFiles=lambda: ("C:/otls/tool.hda", "C:/otls/other.hda"),
        definitionsInFile=lambda path: definitions if "tool.hda" in path else (),
    )
    namespace = {
        "_hcm_hou": SimpleNamespace(
            hda=hda,
            nodeFlag=SimpleNamespace(Compress="compress"),
            frame=lambda: 1.0,
        ),
        "_hcm_math": __import__("math"),
        "_hcm_resolve_node": lambda value: node,
        "_hcm_node_summary": lambda value: {"kind": "hou.Node", "path": value.path()},
        "_hcm_geometry_positive": _positive,
        "_hcm_error_text": lambda exc, _limit: str(exc),
    }
    exec(HDA_SOURCE, namespace)
    return namespace


def test_hda_inspect_is_bounded_and_does_not_read_section_contents() -> None:
    namespace = _namespace([FakeDefinition()])
    service = namespace["_HCMHdaService"]()

    result = service.inspect(
        "/obj/geo1/tool1", parms=True, sections=True, tools=True, max_items=1
    )

    assert result["definition"]["type_name"] == "acme::tool::1.0"
    assert result["definition"]["sections"] == {
        "count": 2,
        "items": [{"name": "PythonModule", "size": 128}],
        "truncated": True,
        "limit": 1,
    }
    assert result["parms"]["truncated"] is True
    assert result["tools"]["count"] == 2
    assert result["tools"]["truncated"] is True


def test_hda_definition_and_library_discovery_filters_and_caps() -> None:
    definitions = [FakeDefinition(), FakeDefinition("other::thing::2.0")]
    namespace = _namespace(definitions)
    service = namespace["_HCMHdaService"]()

    found = service.definitions(namespace="acme", max_items=1)
    libraries = service.libraries(definition="tool", max_types=1)

    assert found["count"] == 1
    assert found["definitions"][0]["components"]["namespace"] == "acme"
    assert found["meta"]["total_matches"] == 1
    assert libraries["count"] == 1
    assert libraries["libraries"][0]["definition_count"] == 2
    assert libraries["libraries"][0]["types_truncated"] is True


def test_hda_inspect_rejects_plain_nodes() -> None:
    namespace = _namespace([FakeDefinition()])
    namespace["_hcm_resolve_node"] = lambda _value: FakeNode(None)
    service = namespace["_HCMHdaService"]()

    with pytest.raises(ValueError, match="not an HDA instance"):
        service.inspect("/obj/plain")


def test_hda_validation_dry_run_returns_effect_plan_without_mutation() -> None:
    namespace = _namespace([FakeDefinition()])
    events = []
    service = namespace["_HCMHdaService"](events)

    plan = service.validate(
        "/obj/geo1/tool1",
        fresh=True,
        frames=[1.0, 2.0],
        dry_run=True,
        external_references=True,
    )

    assert plan["operation"] == "hda.validate"
    assert plan["dry_run"] is True
    assert plan["effects"] == {
        "temporary_node": True,
        "temporary_frame_changes": True,
        "cooks": 2,
        "library_writes": False,
        "hip_save": False,
    }
    assert plan["steps"][4] == {
        "kind": "audit_external_references",
        "enabled": True,
        "mutates": False,
    }
    assert events == []
