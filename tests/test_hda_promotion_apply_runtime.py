from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from houdini_codemode.runtime_hda_promotion_apply_source import HDA_PROMOTION_APPLY_SOURCE
from houdini_codemode.runtime_hda_promotion_source import HDA_PROMOTION_SOURCE


class FakeTemplate:
    def __init__(self, name, template_type="Float", components=1, label=None):
        self._name = name
        self._type = template_type
        self._components = components
        self._label = label or name.title()

    def name(self): return self._name
    def label(self): return self._label
    def type(self): return SimpleNamespace(name=lambda: self._type)
    def numComponents(self): return self._components
    def clone(self): return copy.deepcopy(self)
    def setName(self, name): self._name = name


class FakeGroup:
    def __init__(self, templates=(), folders=()):
        self._templates = {item.name(): item for item in templates}
        self._folders = {item.name(): item for item in folders}

    def find(self, name): return self._templates.get(name) or self._folders.get(name)
    def findFolder(self, name): return self._folders.get(name)
    def append(self, template): self._templates[template.name()] = template
    def appendToFolder(self, _folder, template): self.append(template)


class FakeParmTuple:
    def __init__(self, name, components): self._name, self._components = name, tuple(components)
    def name(self): return self._name
    def __iter__(self): return iter(self._components)


class FakeParm:
    def __init__(self, node, name, template, fail_on_set=False):
        self._node, self._name, self._template = node, name, template
        self._expression, self._language, self._value = None, None, 3.0
        self._keyframes, self._fail_on_set = [], fail_on_set
        self._tuple = None

    def path(self): return self._node.path() + "/" + self._name
    def name(self): return self._name
    def node(self): return self._node
    def parmTemplate(self): return self._template
    def tuple(self): return self._tuple
    def keyframes(self): return tuple(self._keyframes)
    def deleteAllKeyframes(self): self._keyframes = []
    def setKeyframes(self, values): self._keyframes = list(values)
    def expression(self):
        if self._expression is None: raise RuntimeError("no expression")
        return self._expression
    def expressionLanguage(self): return self._language
    def eval(self): return self._value
    def set(self, value): self._value = value; self._expression = None
    def referenceExpression(self, destination, language=None): return 'ch("../' + destination.tuple().name() + '")'
    def setExpression(self, expression, language=None):
        if self._fail_on_set: raise RuntimeError("injected channel failure")
        self._expression, self._language = expression, language


class FakeDefinition:
    def __init__(self, library, group, fail_update_at=None):
        self._library, self._group, self.set_calls = library, group, []
        self._fail_update_at, self._update_calls, self.call_order = fail_update_at, 0, []
    def libraryFilePath(self): return self._library
    def parmTemplateGroup(self): return copy.deepcopy(self._group)
    def setParmTemplateGroup(self, group, **kwargs):
        self._group = copy.deepcopy(group); self.set_calls.append(kwargs); self.call_order.append("interface")
        Path(self._library).write_bytes(Path(self._library).read_bytes() + b"I")
    def updateFromNode(self, _node):
        self._update_calls += 1; self.call_order.append("contents")
        Path(self._library).write_bytes(Path(self._library).read_bytes() + b"U")
        if self._fail_update_at == self._update_calls: raise RuntimeError("injected definition update failure")
    def save(self, *_args, **_kwargs): raise AssertionError("apply must not explicitly save")


class FakeNodeType:
    def __init__(self, definition, instances): self._definition, self._instances = definition, instances
    def definition(self): return self._definition
    def name(self): return "acme::isolated::1.0"
    def instances(self): return tuple(self._instances)


class FakeNode:
    def __init__(self, definition):
        self._definition, self._parms, self._tuples = definition, {}, {}
        self._locked = False
        self._type = FakeNodeType(definition, [self])
    def path(self): return "/obj/geo1/tool1"
    def type(self): return self._type
    def isLockedHDA(self): return self._locked
    def matchCurrentDefinition(self): self._locked = True; self.refresh_interface()
    def allowEditingOfContents(self): self._locked = False
    def parm(self, path): return self._parms.get(path)
    def parmTuple(self, name): return self._tuples.get(name)
    def add_internal_tuple(self, relative, names, fail_component=None):
        child = SimpleNamespace(path=lambda: self.path() + "/" + relative.rsplit("/", 1)[0])
        template = FakeTemplate(names[0], components=len(names))
        components = [FakeParm(child, name, template, fail_on_set=index == fail_component) for index, name in enumerate(names)]
        parm_tuple = FakeParmTuple(names[0], components)
        for component in components: component._tuple = parm_tuple
        self._parms[relative] = components[0]
        return components
    def refresh_interface(self):
        for template in self._definition._group._templates.values():
            if template.name() not in self._tuples:
                components = [FakeParm(self, template.name() + (str(i) if template.numComponents() > 1 else ""), template) for i in range(template.numComponents())]
                parm_tuple = FakeParmTuple(template.name(), components)
                for component in components: component._tuple = parm_tuple
                self._tuples[template.name()] = parm_tuple


def _service(tmp_path, vector=False, fail_component=None, fail_update_at=None):
    library = tmp_path / "owned.hda"; library.write_bytes(b"base")
    definition = FakeDefinition(str(library), FakeGroup(), fail_update_at=fail_update_at)
    node = FakeNode(definition)
    components = node.add_internal_tuple("inside/value", ["valuex", "valuey", "valuez"] if vector else ["value"], fail_component)
    namespace = {"_hcm_resolve_node": lambda value, _label="node": node, "_hcm_hou": SimpleNamespace(exprLanguage=SimpleNamespace(Hscript="Hscript"), expandString=lambda value: "")}
    exec(HDA_PROMOTION_SOURCE, namespace)
    exec(HDA_PROMOTION_APPLY_SOURCE, namespace)
    return namespace["_HCMHdaPromotionApplyService"](), node, definition, library, components


def test_apply_promotes_scalar_and_vector_with_hscript_references(tmp_path) -> None:
    # Build each isolated fake library under an explicit, caller-owned temp directory.
    scalar_dir = tmp_path / "scalar"; scalar_dir.mkdir()
    scalar, scalar_node, scalar_definition, scalar_library, scalar_components = _service(scalar_dir)
    vector_dir = tmp_path / "vector"; vector_dir.mkdir()
    vector, vector_node, vector_definition, vector_library, vector_components = _service(vector_dir, vector=True)

    scalar_result = scalar.apply(scalar_node, "inside/value", ["ui_value"], allow_library_write=True, owned_library=str(scalar_library))
    vector_result = vector.apply(vector_node, "inside/value", ["ui_vector"], allow_library_write=True, owned_library=str(vector_library), create_backup=False)

    assert scalar_result["items"] == [{"source": "/obj/geo1/tool1/inside/value", "destination": "/obj/geo1/tool1/ui_value", "components": 1}]
    assert vector_result["items"][0]["components"] == 3
    assert all(component.expression().startswith('ch("../ui_') for component in scalar_components + vector_components)
    assert scalar_result["library"]["before"]["sha256"] == hashlib.sha256(b"base").hexdigest()
    assert scalar_result["library"]["after"]["size"] > scalar_result["library"]["before"]["size"]
    assert scalar_definition.set_calls == [{"rename_conflicting_parms": False, "create_backup": True}]
    assert vector_definition.set_calls == [{"rename_conflicting_parms": False, "create_backup": False}]
    assert scalar_definition.call_order == ["contents", "interface", "contents"]
    assert vector_result["persistence"]["internal_channel_references"].startswith("saved into")


def test_apply_rejects_plan_conflicts_before_any_mutation(tmp_path) -> None:
    service, node, definition, library, _components = _service(tmp_path)
    definition._group.append(FakeTemplate("ui_value"))
    original = library.read_bytes()

    with pytest.raises(ValueError, match="destination conflicts"):
        service.apply(node, "inside/value", ["ui_value"], allow_library_write=True, owned_library=str(library))

    assert definition.set_calls == []
    assert library.read_bytes() == original


def test_apply_rolls_back_channels_and_interface_after_mid_apply_failure(tmp_path) -> None:
    service, node, definition, library, components = _service(tmp_path, vector=True, fail_component=1)
    original = library.read_bytes()

    with pytest.raises(RuntimeError, match="rollback attempted"):
        service.apply(node, "inside/value", ["ui_vector"], allow_library_write=True, owned_library=str(library))

    assert all(component._expression is None for component in components)
    assert definition._group.find("ui_vector") is None
    assert len(definition.set_calls) == 2
    assert library.read_bytes() == original + b"UII"
    assert definition.call_order == ["contents", "interface", "interface"]


def test_apply_reports_definition_content_rollback_limit_after_update_failure(tmp_path) -> None:
    service, node, definition, library, components = _service(tmp_path, fail_update_at=2)
    original = library.read_bytes()

    with pytest.raises(RuntimeError, match="cannot be restored if updateFromNode was entered"):
        service.apply(node, "inside/value", ["ui_value"], allow_library_write=True, owned_library=str(library))

    assert all(component._expression is None for component in components)
    assert definition._group.find("ui_value") is None
    assert definition.call_order == ["contents", "interface", "contents", "interface"]
    assert library.read_bytes() == original + b"UIUI"


def test_apply_never_calls_save_install_or_hip_save_and_requires_opt_in(tmp_path) -> None:
    service, node, definition, library, _components = _service(tmp_path)
    with pytest.raises(ValueError, match="allow_library_write=True"):
        service.apply(node, "inside/value", ["ui_value"], owned_library=str(library))

    result = service.apply(node, "inside/value", ["ui_value"], allow_library_write=True, owned_library=str(library))
    assert result["library"]["hda_definition_save_called"] is False
    assert result["library"]["update_from_node_called"] is True
    assert result["library"]["update_from_node_calls"] == 2
    assert result["library"]["install_called"] is False
    assert result["library"]["hip_save_called"] is False
    assert result["persistence"]["update_from_node_called"] is True
    assert definition.set_calls
