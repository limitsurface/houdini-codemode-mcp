from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from houdini_codemode.runtime_hda_section_source import HDA_SECTION_SOURCE


class FakeSection:
    def __init__(self, contents): self.contents_value = contents
    def size(self): return len(self.contents_value.encode("utf-8"))
    def contents(self): return self.contents_value


class FakeDefinition:
    def __init__(self, library, sections=()):
        self.library, self._sections, self.calls = library, dict(sections), []
    def libraryFilePath(self): return self.library
    def sections(self): return dict(self._sections)
    def addSection(self, name, contents):
        self.calls.append(("add", name, contents))
        self._sections[name] = FakeSection(contents)
        Path(self.library).write_bytes(Path(self.library).read_bytes() + b"A")
    def removeSection(self, name):
        if name not in self._sections: raise RuntimeError("missing")
        self.calls.append(("remove", name))
        del self._sections[name]
        Path(self.library).write_bytes(Path(self.library).read_bytes() + b"R")
    def nodeType(self): return SimpleNamespace(name=lambda: "acme::section::1.0")


class FakeType:
    def __init__(self, definition, instances): self.definition_value, self.instances_value = definition, instances
    def definition(self): return self.definition_value
    def name(self): return "acme::section::1.0"
    def instances(self): return tuple(self.instances_value)


class FakeNode:
    def __init__(self, definition):
        self.definition_value = definition
        self.type_value = FakeType(definition, [self])
    def path(self): return "/obj/section_asset"
    def type(self): return self.type_value


class FakeHda:
    def __init__(self, definition): self.definition = definition
    def definitionsInFile(self, _path): return [self.definition]


class Guard:
    def __init__(self): self.install_calls = self.save_calls = 0
    def installFile(self, *_args): self.install_calls += 1; raise AssertionError("must not install")
    def save(self, *_args): self.save_calls += 1; raise AssertionError("must not save HIP")


def _service(tmp_path, sections=(), hfs=""):
    library = tmp_path / "owned.hda"; library.write_bytes(b"base")
    definition = FakeDefinition(str(library), sections)
    node = FakeNode(definition)
    guard = Guard()
    namespace = {
        "_hcm_resolve_node": lambda value, _label="node": node,
        "_hcm_hou": SimpleNamespace(expandString=lambda value: hfs if value == "$HFS" else value, hda=FakeHda(definition), hipFile=guard),
    }
    exec(HDA_SECTION_SOURCE, namespace)
    return namespace["_HCMHdaSectionService"](), node, definition, library, guard


def test_plan_and_read_are_owned_bounded_and_non_mutating(tmp_path):
    service, node, definition, library, guard = _service(tmp_path, (("Readme", FakeSection("hello")),))
    plan = service.plan(node, "Readme", "set", "replacement", str(library))
    read = service.read(node, "Readme", str(library), max_content_bytes=10)
    assert plan["dry_run"] is True and plan["ok"] is True
    assert plan["section"]["content_utf8_bytes"] == len(b"replacement")
    assert read["section"]["contents"] == "hello"
    assert definition.calls == [] and library.read_bytes() == b"base"
    assert guard.install_calls == guard.save_calls == 0


def test_apply_writes_only_after_opt_in_with_verified_backup_and_exact_events(tmp_path):
    events = []
    service, node, definition, library, guard = _service(tmp_path)
    service._mutation_events = events
    with pytest.raises(ValueError, match="allow_library_write=True"):
        service.apply(node, "Readme", contents="hello", owned_library=str(library))
    result = service.apply(node, "Readme", contents="hello", owned_library=str(library), allow_library_write=True)
    assert definition.calls == [("add", "Readme", "hello")]
    assert result["library"]["before"]["sha256"] != result["library"]["after"]["sha256"]
    assert Path(result["library"]["backup"]["path"]).read_bytes() == b"base"
    assert [event["kind"] for event in result["events"]] == ["hda.sections.preflight", "hda.sections.backup", "hda.definition.addSection"]
    assert result["events"][-1]["status"] == "complete"
    assert result["library"]["hda_definition_save_called"] is False
    assert guard.install_calls == guard.save_calls == 0


def test_rejects_tools_managed_sections_nonsole_or_foreign_library_and_caps(tmp_path):
    service, node, definition, library, _guard = _service(tmp_path)
    with pytest.raises(ValueError, match="Tools.shelf"):
        service.plan(node, "Tools.shelf", contents="xml", owned_library=str(library))
    with pytest.raises(ValueError, match="Houdini-managed"):
        service.plan(node, "Contents.gz", contents="no", owned_library=str(library))
    with pytest.raises(ValueError, match="exceeds"):
        service.plan(node, "Readme", contents="x" * 5, owned_library=str(library), max_content_bytes=4)
    other = tmp_path / "other.hda"; other.write_bytes(b"other")
    with pytest.raises(ValueError, match="exactly match"):
        service.plan(node, "Readme", contents="ok", owned_library=str(other))
    second = FakeNode(definition); node.type_value.instances_value.append(second)
    with pytest.raises(ValueError, match="sole instance"):
        service.plan(node, "Readme", contents="ok", owned_library=str(library))


def test_delete_requires_existing_section_and_emits_remove_event(tmp_path):
    service, node, definition, library, _guard = _service(tmp_path, (("Readme", FakeSection("hello")),))
    result = service.apply(node, "Readme", action="delete", owned_library=str(library), allow_library_write=True, create_backup=False)
    assert definition.calls == [("remove", "Readme")]
    assert [event["kind"] for event in result["events"]] == ["hda.sections.preflight", "hda.definition.removeSection"]
    with pytest.raises(ValueError, match="not found"):
        service.apply(node, "Readme", action="delete", owned_library=str(library), allow_library_write=True)
