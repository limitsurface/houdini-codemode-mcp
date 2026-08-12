from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from houdini_codemode.runtime_recipe_source import RECIPE_SOURCE


class FakeSection:
    def __init__(self, contents: str, size: int | None = None):
        self._contents = contents
        self._size = len(contents.encode("utf-8")) if size is None else size
        self.read = False

    def size(self):
        return self._size

    def contents(self):
        self.read = True
        return self._contents


class FakeDefinition:
    def __init__(self, payload, library="C:/recipes/test.hda", scripts=()):
        self.section = FakeSection(json.dumps(payload))
        self._library = library
        self._scripts = scripts

    def sections(self):
        return {"data.recipe.json": self.section, **{name: FakeSection("") for name in self._scripts}}

    def libraryFilePath(self):
        return self._library


class FakeNodeType:
    def __init__(self, label, definition):
        self._label = label
        self._definition = definition

    def description(self):
        return self._label

    def definition(self):
        return self._definition


class FakeNode:
    def __init__(self, path):
        self._path = path

    def path(self):
        return self._path


class FakeParm:
    def __init__(self, path):
        self._path = path

    def path(self):
        return self._path


class FakeData:
    def __init__(self):
        self.node_calls = []
        self.parm_calls = []

    def applyNodePresetRecipe(self, *args, **kwargs):
        self.node_calls.append((args, kwargs))
        return {"node": args[1], "parms": (FakeParm(args[1].path() + "/size"),)}

    def applyParmPresetRecipe(self, *args, **kwargs):
        self.parm_calls.append((args, kwargs))
        node = FakeNode(args[1].path().rsplit("/", 1)[0])
        return {"node": node, "parm": args[1]}


def _payload(category, *, visible=True):
    return {
        "data": {"parms": {"size": 2}},
        "properties": {
            "name": "test_recipe", "recipe_category": category, "visible": visible,
            "nodetype_category": "Sop", "nodetype_name": "box", "nodetype_patterns": ["Sop/box"],
        },
        "tool": {"network_categories": ["Sop"], "tab_submenus": ["Recipes"], "icon": "BUTTONS_recipe"},
    }


def _service(node_types):
    data = FakeData()
    nodes = {"/obj/isolated": FakeNode("/obj/isolated")}
    parms = {"/obj/isolated/size": FakeParm("/obj/isolated/size")}
    hou = SimpleNamespace(
        data=data,
        dataNodeTypeCategory=lambda: SimpleNamespace(nodeTypes=lambda: node_types),
        node=lambda path: nodes.get(path),
        parmTuple=lambda path: None,
        parm=lambda path: parms.get(path),
    )
    namespace = {
        "_hcm_hou": hou,
        "_hcm_resolve_node": lambda value, _label="node": nodes[value] if isinstance(value, str) else value,
        "_hcm_error_text": lambda exc, _maximum=512: str(exc),
    }
    exec(RECIPE_SOURCE, namespace)
    events = []
    return namespace["_HCMRecipeService"](events), data, events


def test_list_filters_categories_visibility_and_returns_bounded_metadata() -> None:
    node_types = {
        "node": FakeNodeType("Node preset", FakeDefinition(_payload("node_preset_recipe"))),
        "parm": FakeNodeType("Parm preset", FakeDefinition(_payload("parm_preset_recipe", visible=False))),
        "plain": FakeNodeType("Plain data", FakeDefinition({})),
    }
    service, _data, _events = _service(node_types)

    result = service.list(category="node-preset", visible_only=True, max_items=10)

    assert result["count"] == 1
    assert result["items"][0]["key"] == "node"
    assert result["items"][0]["data"] == {"present": True, "kind": "dict", "top_level_keys": ["parms"]}
    assert result["items"][0]["scripts"] == {"prescript_present": False, "postscript_present": False}


def test_get_rejects_oversize_recipe_before_reading_contents() -> None:
    definition = FakeDefinition(_payload("node_preset_recipe"))
    definition.section._size = 999
    service, _data, _events = _service({"large": FakeNodeType("Large", definition)})

    with pytest.raises(ValueError, match="exceeds max_recipe_bytes"):
        service.get("large", max_recipe_bytes=100)

    assert definition.section.read is False


def test_apply_node_preset_always_disables_scripts_and_content_surfaces() -> None:
    definition = FakeDefinition(_payload("node_preset_recipe"), scripts=("pre-script.recipe.py", "post-script.recipe.py"))
    service, data, events = _service({"node": FakeNodeType("Node", definition)})

    result = service.apply_node_preset("node", "/obj/isolated")

    assert result["node"] == "/obj/isolated"
    assert result["parms"]["items"] == ["/obj/isolated/size"]
    assert data.node_calls[0][1] == {
        "prescript": False, "postscript": False, "parms": True,
        "parmtemplates": False, "children": False, "editables": False, "skip_notes": True,
    }
    assert events == [{
        "kind": "recipe.apply_node_preset", "helper": "ctx.recipes.apply_node_preset",
        "recipe": "node", "node_path": "/obj/isolated", "scripts_skipped": True,
    }]


def test_apply_parm_preset_is_explicit_and_scripts_are_suppressed() -> None:
    service, data, events = _service({"parm": FakeNodeType("Parm", FakeDefinition(_payload("parm_preset_recipe")))})

    result = service.apply_parm_preset("parm", "/obj/isolated/size", multiparm_operation="append", multiparm_start_index=2)

    assert result["parm"] == "/obj/isolated/size"
    assert data.parm_calls[0][1] == {
        "multiparm_operation": "append", "multiparm_start_index": 2,
        "prescript": False, "postscript": False,
    }
    assert events[0]["kind"] == "recipe.apply_parm_preset"
    assert events[0]["scripts_skipped"] is True


def test_apply_rejects_categories_without_script_suppression_before_mutating() -> None:
    service, data, _events = _service({"tool": FakeNodeType("Tool", FakeDefinition(_payload("tool_recipe")))})

    with pytest.raises(ValueError, match="node-preset"):
        service.apply_node_preset("tool", "/obj/isolated")

    assert data.node_calls == []
