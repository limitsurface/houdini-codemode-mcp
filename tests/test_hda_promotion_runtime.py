from __future__ import annotations

from types import SimpleNamespace

import pytest

from houdini_codemode.runtime_hda_promotion_source import HDA_PROMOTION_SOURCE


class FakeTemplate:
    def __init__(self, name, template_type="Float", label=None):
        self._name = name
        self._type = template_type
        self._label = label or name.title()

    def name(self):
        return self._name

    def label(self):
        return self._label

    def type(self):
        return SimpleNamespace(name=lambda: self._type)


class FakeGroup:
    def __init__(self, templates=(), folders=()):
        self._templates = {template.name(): template for template in templates}
        self._folders = {folder.name(): folder for folder in folders}

    def find(self, name):
        return self._templates.get(name) or self._folders.get(name)

    def findFolder(self, name):
        return self._folders.get(name)


class FakeDefinition:
    def __init__(self, group):
        self._group = group

    def parmTemplateGroup(self):
        return self._group

    def libraryFilePath(self):
        return "C:/otls/acme_tool.hda"


class FakeNodeType:
    def __init__(self, definition):
        self._definition = definition

    def definition(self):
        return self._definition

    def name(self):
        return "acme::tool::1.0"


class FakeParmTuple:
    def __init__(self, name, components):
        self._name = name
        self._components = tuple(components)

    def name(self):
        return self._name

    def __iter__(self):
        return iter(self._components)


class FakeParm:
    def __init__(self, node, name, template, tuple_name=None, expression=None):
        self._node = node
        self._name = name
        self._template = template
        self._expression = expression
        self._tuple = FakeParmTuple(tuple_name or name, (self,))

    def path(self):
        return self._node.path() + "/" + self._name

    def name(self):
        return self._name

    def node(self):
        return self._node

    def parmTemplate(self):
        return self._template

    def tuple(self):
        return self._tuple

    def expression(self):
        if self._expression is None:
            raise RuntimeError("no expression")
        return self._expression

    def keyframes(self):
        return ()


class FakeNode:
    def __init__(self, definition):
        self._definition = definition
        self._parms = {}
        self._children = {}

    def path(self):
        return "/obj/geo1/tool1"

    def type(self):
        return FakeNodeType(self._definition)

    def isLockedHDA(self):
        return True

    def parm(self, path):
        return self._parms.get(path)

    def add_internal(self, relative_path, name, template_type="Float", expression=None):
        child = SimpleNamespace(path=lambda: self.path() + "/" + relative_path.rsplit("/", 1)[0])
        parm = FakeParm(child, name, FakeTemplate(name, template_type), expression=expression)
        self._parms[relative_path] = parm
        return parm


def _service(group=None):
    node = FakeNode(FakeDefinition(group or FakeGroup()))
    node.add_internal("transform/scale", "scale", expression='ch("../old")')
    namespace = {"_hcm_resolve_node": lambda value, _label="node": node}
    exec(HDA_PROMOTION_SOURCE, namespace)
    return namespace["_HCMHdaPromotionService"](), node


def test_promotion_plan_is_read_only_and_describes_template_and_link() -> None:
    service, node = _service()

    plan = service.plan("/obj/geo1/tool1", "transform/scale", destination_names="ui_scale")

    assert plan["dry_run"] is True
    assert plan["ok"] is True
    assert plan["items"][0]["template_copy"] == {
        "source_name": "scale",
        "source_label": "Scale",
        "type": "Float",
        "components": 1,
        "operation": "clone_then_set_name",
        "destination_name": "ui_scale",
    }
    assert plan["items"][0]["channel_link"]["direction"] == "internal_references_promoted_parameter"
    assert plan["expected_effects"]["current_call"] == {
        "mutates_instance": False,
        "mutates_definition": False,
        "writes_library": False,
        "saves_hip": False,
    }
    assert node._definition._group.find("ui_scale") is None


def test_promotion_plan_reports_conflicts_without_mutating() -> None:
    service, _node = _service(FakeGroup((FakeTemplate("ui_scale"),)))

    plan = service.plan("/obj/geo1/tool1", ["transform/scale"], ["ui_scale"])

    assert plan["ok"] is False
    assert plan["conflicts"] == [
        {"destination_name": "ui_scale", "conflicts": ["definition_template"]}
    ]
    assert plan["items"][0]["destination"]["available"] is False


def test_promotion_plan_rejects_non_internal_unsupported_and_duplicate_targets() -> None:
    service, node = _service()
    node._parms["outer"] = FakeParm(node, "outer", FakeTemplate("outer"))
    node.add_internal("transform/action", "action", "Button")

    with pytest.raises(ValueError, match="inside the HDA"):
        service.plan("/obj/geo1/tool1", "outer")
    with pytest.raises(ValueError, match="Unsupported promotion template type Button"):
        service.plan("/obj/geo1/tool1", "transform/action")
    with pytest.raises(ValueError, match="same internal parameter tuple"):
        service.plan("/obj/geo1/tool1", ["transform/scale", "transform/scale"])
