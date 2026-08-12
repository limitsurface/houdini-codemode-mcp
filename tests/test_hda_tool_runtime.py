from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from houdini_codemode.runtime_hda_tool_source import HDA_TOOL_SOURCE


class FakeSection:
    def __init__(self, contents): self.value = contents
    def size(self): return len(self.value.encode("utf-8"))


class FakeDefinition:
    def __init__(self, library, sections=()): self.library, self._sections, self.calls = library, dict(sections), []
    def libraryFilePath(self): return self.library
    def sections(self): return dict(self._sections)
    def tools(self): return {"$HDA_DEFAULT_TOOL": object()} if "Tools.shelf" in self._sections else {}
    def addSection(self, name, contents):
        self.calls.append(("add", name, contents)); self._sections[name] = FakeSection(contents)
        Path(self.library).write_bytes(Path(self.library).read_bytes() + b"A")
    def removeSection(self, name):
        if name not in self._sections: raise RuntimeError("missing")
        self.calls.append(("remove", name)); del self._sections[name]
        Path(self.library).write_bytes(Path(self.library).read_bytes() + b"R")
    def nodeType(self): return SimpleNamespace(name=lambda: "acme::tool::1.0")


class FakeType:
    def __init__(self, definition, instances): self.definition_value, self.instances_value = definition, instances
    def definition(self): return self.definition_value
    def name(self): return "acme::tool::1.0"
    def instances(self): return tuple(self.instances_value)


class FakeNode:
    def __init__(self, definition): self.type_value = FakeType(definition, [self])
    def path(self): return "/obj/tool_asset"
    def type(self): return self.type_value


def _service(tmp_path, sections=(), hfs=""):
    library = tmp_path / "owned.hda"; library.write_bytes(b"base")
    definition = FakeDefinition(str(library), sections); node = FakeNode(definition)
    namespace = {"_hcm_resolve_node": lambda value, _label="node": node, "_hcm_hou": SimpleNamespace(expandString=lambda value: hfs if value == "$HFS" else value, hda=SimpleNamespace(definitionsInFile=lambda _path: [definition]))}
    exec(HDA_TOOL_SOURCE, namespace)
    return namespace["_HCMHdaToolService"](), node, definition, library


def test_inspect_is_bounded_read_only_and_does_not_require_ownership(tmp_path):
    service, node, definition, library = _service(tmp_path, (("Tools.shelf", FakeSection("xml")),))
    inspected = service.inspect(node, max_items=1)
    assert inspected["tools"] == {"count": 1, "items": ["$HDA_DEFAULT_TOOL"], "truncated": False, "limit": 1}
    assert inspected["tools_shelf"] == {"present": True, "size": 3, "contents_read": False}
    assert definition.calls == [] and library.read_bytes() == b"base"


def test_plan_set_is_structured_escaped_and_non_mutating(tmp_path):
    service, node, definition, library = _service(tmp_path)
    plan = service.plan(node, "set", "Studio & Tools", "sop", str(library))
    assert plan["dry_run"] is True and plan["ok"] is True
    assert plan["tool"]["context"] == "SOP"
    assert definition.calls == []
    with pytest.raises(ValueError, match="context must be"):
        service.plan(node, "set", "Studio", "OBJ", str(library))


def test_set_requires_opt_in_and_generates_h22_viewer_and_network_contexts(tmp_path):
    events = []
    service, node, definition, library = _service(tmp_path); service._mutation_events = events
    with pytest.raises(ValueError, match="allow_library_write=True"):
        service.set(node, "Studio", "SOP", str(library))
    result = service.set(node, "Studio & Tools", "SOP", str(library), allow_library_write=True)
    xml = definition.calls[0][2]
    assert "<contextNetType>SOP</contextNetType>" in xml
    assert '<toolMenuContext name="network"><contextOpType>$HDA_TABLE_AND_NAME</contextOpType>' in xml
    assert "<toolSubmenu>Studio &amp; Tools</toolSubmenu>" in xml
    assert "soptoolutils.genericTool(kwargs, '$HDA_NAME')" in xml
    assert result["library"]["before"]["sha256"] != result["library"]["after"]["sha256"]
    assert Path(result["library"]["backup"]["path"]).read_bytes() == b"base"
    assert [event["kind"] for event in result["events"]] == ["hda.tools.preflight", "hda.tools.backup", "hda.definition.addSection"]


def test_remove_and_strict_ownership_boundary(tmp_path):
    service, node, definition, library = _service(tmp_path, (("Tools.shelf", FakeSection("xml")),))
    result = service.remove(node, str(library), allow_library_write=True, create_backup=False)
    assert result["action"] == "remove" and definition.calls == [("remove", "Tools.shelf")]
    other = tmp_path / "other.hda"; other.write_bytes(b"x")
    with pytest.raises(ValueError, match="exactly match"):
        service.plan(node, "set", "Studio", "SOP", str(other))
    node.type_value.instances_value.append(FakeNode(definition))
    with pytest.raises(ValueError, match="sole instance"):
        service.plan(node, "set", "Studio", "SOP", str(library))
