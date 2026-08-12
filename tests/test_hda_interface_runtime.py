from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from houdini_codemode.runtime_hda_interface_source import HDA_INTERFACE_SOURCE


class Template:
    def __init__(self, kind, name, label, components=1, **kwargs): self.kind, self._name, self.label, self.components, self.kwargs = kind, name, label, components, kwargs
    def name(self): return self._name
    def type(self): return SimpleNamespace(name=lambda: {"float": "Float", "int": "Int", "string": "String", "toggle": "Toggle", "menu": "Menu"}[self.kind])
    def numComponents(self): return self.components
    def clone(self): return copy.deepcopy(self)
    def setDefaultValue(self, value): self.kwargs["default_value"] = value
    def menuItems(self): return self.kwargs.get("menu_items", ())
    def itemGeneratorScript(self): return ""


class Group:
    def __init__(self, entries=()): self.entries_value = list(entries)
    def find(self, name): return next((x for x in self.entries_value if x.name() == name), None)
    def append(self, item): self.entries_value.append(item)
    def replace(self, name, item): self.entries_value[[x.name() for x in self.entries_value].index(name)] = item


class Definition:
    def __init__(self, library, group=None): self.library, self.group, self.order, self.set_kwargs = library, group or Group(), [], []
    def libraryFilePath(self): return self.library
    def parmTemplateGroup(self): return copy.deepcopy(self.group)
    def updateFromNode(self, _node): self.order.append("checkpoint"); Path(self.library).write_bytes(Path(self.library).read_bytes() + b"U")
    def setParmTemplateGroup(self, group, **kwargs): self.order.append("interface"); self.group = copy.deepcopy(group); self.set_kwargs.append(kwargs); Path(self.library).write_bytes(Path(self.library).read_bytes() + b"I")
    def nodeType(self): return SimpleNamespace(name=lambda: "acme::interface::1.0")


class Parm:
    def __init__(self, value): self.value = value
    def expression(self): raise RuntimeError("no expression")


class ParmTuple:
    def __init__(self, values): self.values = tuple(values); self.components = [Parm(value) for value in values]
    def eval(self): return self.values
    def __iter__(self): return iter(self.components)


class Node:
    def __init__(self, definition): self.definition, self.locked, self.matched, self.tuples = definition, False, False, {}; self.type_value = SimpleNamespace(definition=lambda: definition, name=lambda: "acme::interface::1.0", instances=lambda: (self,))
    def path(self): return "/obj/interface_asset"
    def type(self): return self.type_value
    def isLockedHDA(self): return self.locked
    def matchCurrentDefinition(self): self.matched = True; self.locked = True
    def parmTuple(self, name): return self.tuples.get(name)


def _service(tmp_path, group=None):
    library = tmp_path / "owned.hda"; library.write_bytes(b"base")
    definition, node = Definition(str(library), group), None
    node = Node(definition)
    def menu(name, label, menu_items, menu_labels, **kwargs): return Template("menu", name, label, menu_items=menu_items, menu_labels=menu_labels, **kwargs)
    hou = SimpleNamespace(expandString=lambda value: "" if value == "$HFS" else value, hda=SimpleNamespace(definitionsInFile=lambda _path: [definition]), FloatParmTemplate=lambda *a, **k: Template("float", *a, **k), IntParmTemplate=lambda *a, **k: Template("int", *a, **k), StringParmTemplate=lambda *a, **k: Template("string", *a, **k), ToggleParmTemplate=lambda name, label, default: Template("toggle", name, label, default_value=default), MenuParmTemplate=menu)
    namespace = {"_hcm_hou": hou, "_hcm_resolve_node": lambda value, _label="node": node}; exec(HDA_INTERFACE_SOURCE, namespace)
    return namespace["_HCMHdaInterfaceService"](), node, definition, library


def test_plan_supports_bounded_scalar_vector_schema_and_reports_unsupported(tmp_path):
    service, node, definition, library = _service(tmp_path)
    items = [{"name": "gain", "label": "Gain", "type": "float", "components": 3, "default": [1, 2, 3]}, {"name": "mode", "type": "menu", "menu_items": ["a", "b"], "menu_labels": ["A", "B"], "default": 1}]
    plan = service.plan(node, items, str(library))
    assert plan["ok"] is True and plan["items"][0]["default"] == (1.0, 2.0, 3.0)
    with pytest.raises(ValueError, match="folders"):
        service.plan(node, [{"name": "ui", "type": "folder"}], str(library))
    assert definition.order == []


def test_apply_checkpoints_then_sets_interface_matches_and_backs_up(tmp_path):
    events = []
    service, node, definition, library = _service(tmp_path); service._mutation_events = events
    items = [{"name": "gain", "type": "float", "default": [2.5]}, {"name": "enabled", "type": "toggle", "default": True}, {"name": "title", "type": "string", "default": ["hello"]}]
    with pytest.raises(ValueError, match="allow_library_write=True"):
        service.apply(node, items, str(library))
    result = service.apply(node, items, str(library), allow_library_write=True)
    assert definition.order == ["checkpoint", "interface"] and node.matched is True
    assert [x.kind for x in definition.group.entries_value] == ["float", "toggle", "string"]
    assert definition.group.find("enabled").kwargs["default_value"] is True
    assert definition.set_kwargs == [{"rename_conflicting_parms": False, "create_backup": True}]
    assert Path(result["library"]["backup"]["path"]).read_bytes() == b"base"
    assert [e["kind"] for e in result["events"]] == ["hda.interface.preflight", "hda.interface.backup", "hda.interface.content_checkpoint", "hda.interface.set_group", "hda.interface.match_current"]
    assert result["library"]["before"]["sha256"] != result["library"]["after"]["sha256"]


def test_conflict_policy_and_sole_unlocked_boundary(tmp_path):
    service, node, definition, library = _service(tmp_path, Group([Template("float", "gain", "Gain")]))
    items = [{"name": "gain", "type": "int", "default": [4]}]
    assert service.plan(node, items, str(library))["ok"] is False
    result = service.apply(node, items, str(library), conflict_policy="replace", allow_library_write=True, create_backup=False)
    assert definition.group.find("gain").kind == "int" and result["conflict_policy"] == "replace"
    node.locked = True
    with pytest.raises(ValueError, match="unlocked"):
        service.plan(node, [{"name": "new", "type": "float"}], str(library))


def test_defaults_from_current_is_explicit_bounded_and_rejects_expressions(tmp_path):
    group = Group([Template("float", "gain", "Gain"), Template("toggle", "enabled", "Enabled"), Template("menu", "mode", "Mode", menu_items=("a", "b"))])
    service, node, definition, library = _service(tmp_path, group)
    node.tuples.update({"gain": ParmTuple((7.5,)), "enabled": ParmTuple((1,)), "mode": ParmTuple((1,))})
    plan = service.plan_defaults_from_current(node, ["gain", "enabled", "mode"], str(library))
    assert [item["current"] for item in plan["items"]] == [[7.5], [1], [1]]
    with pytest.raises(ValueError, match="allow_library_write=True"):
        service.set_defaults_from_current(node, ["gain"], str(library))
    result = service.set_defaults_from_current(node, ["gain", "enabled", "mode"], str(library), allow_library_write=True, create_backup=False)
    assert definition.group.find("gain").kwargs["default_value"] == (7.5,)
    assert definition.group.find("enabled").kwargs["default_value"] == 1
    assert [event["kind"] for event in result["events"]] == ["hda.interface.defaults.preflight", "hda.interface.defaults.content_checkpoint", "hda.interface.defaults.set_group", "hda.interface.defaults.match_current"]
    node.locked = False
    definition.group.find("mode").itemGeneratorScript = lambda: "return []"
    with pytest.raises(ValueError, match="Dynamic"):
        service.plan_defaults_from_current(node, ["mode"], str(library))
