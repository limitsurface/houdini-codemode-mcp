from __future__ import annotations

from types import SimpleNamespace

import pytest

from houdini_codemode.runtime_hda_update_source import HDA_UPDATE_SOURCE


class FakeDefinition:
    def __init__(self, library, sections=()):
        self._library = library
        self._sections = {name: object() for name in sections}

    def libraryFilePath(self):
        return self._library

    def sections(self):
        return self._sections

    def updateFromNode(self, _node):
        raise AssertionError("planner must not update a definition")

    def save(self, *_args, **_kwargs):
        raise AssertionError("planner must not write a library")

    def copyToHDAFile(self, *_args, **_kwargs):
        raise AssertionError("planner must not copy a library")


class FakeNodeType:
    def __init__(self, definition, name="acme::tool::2.0"):
        self._definition = definition
        self._name = name

    def definition(self):
        return self._definition

    def name(self):
        return self._name


class FakeNode:
    def __init__(self, definition, locked=False, matches=False):
        self._definition = definition
        self._locked = locked
        self._matches = matches

    def path(self):
        return "/obj/geo1/tool1"

    def type(self):
        return FakeNodeType(self._definition)

    def isLockedHDA(self):
        return self._locked

    def matchesCurrentDefinition(self):
        return self._matches

    def matchCurrentDefinition(self):
        raise AssertionError("planner must not match an instance")


class FakeHdaModule:
    def __init__(self, destination_types=()):
        self._destination_types = tuple(destination_types)
        self.definition_reads = []

    def componentsFromFullNodeTypeName(self, type_name):
        bits = type_name.split("::")
        return "", bits[0], bits[1], bits[2] if len(bits) > 2 else ""

    def definitionsInFile(self, path):
        self.definition_reads.append(path)
        return tuple(
            SimpleNamespace(nodeType=lambda name=name: SimpleNamespace(name=lambda: name))
            for name in self._destination_types
        )


class FakeReferenceService:
    calls = []

    def audit(self, node, **kwargs):
        self.calls.append((node, kwargs))
        return {
            "count": 1,
            "items": [{"source_parm": "/obj/geo1/tool1/a", "target_parm": "/obj/outside/b"}],
            "errors": [],
            "meta": {"truncated": False},
        }


def _service(node, destination_types=()):
    FakeReferenceService.calls = []
    fake_hda = FakeHdaModule(destination_types)
    namespace = {
        "_hcm_hou": SimpleNamespace(hda=fake_hda, expandString=lambda value: value),
        "_hcm_resolve_node": lambda value, _label="node": node,
        "_hcm_error_text": lambda exc, _maximum=512: str(exc),
        "_HCMHdaReferenceService": FakeReferenceService,
    }
    exec(HDA_UPDATE_SOURCE, namespace)
    return namespace["_HCMHdaUpdateService"](), fake_hda


def test_update_plan_is_no_effect_and_describes_ordered_apply(tmp_path) -> None:
    library = tmp_path / "tool.hda"
    node = FakeNode(FakeDefinition(str(library), ("Contents.gz", "DialogScript", "Tools.shelf", "OnCreated")))
    service, _hda = _service(node)

    plan = service.plan(node, contents=True, interface=True, match_current=True)

    assert plan["dry_run"] is True
    assert plan["ok"] is True
    assert [effect["kind"] for effect in plan["future_effects"]] == [
        "audit_external_references",
        "snapshot_preserved_sections",
        "update_definition_contents",
        "update_parameter_interface",
        "restore_preserved_sections",
        "write_destination_library",
        "match_current_definition",
    ]
    assert plan["surfaces"]["retained_sections"]["names"] == ["OnCreated", "Tools.shelf"]
    assert plan["reference_audit"]["external_reference_count"] == 1
    assert plan["expected_effects"]["current_call"] == {
        "mutates_instance": False,
        "mutates_definition": False,
        "writes_library": False,
        "installs_library": False,
        "saves_hip": False,
    }


def test_update_plan_requires_editable_hda_for_contents(tmp_path) -> None:
    node = FakeNode(FakeDefinition(str(tmp_path / "tool.hda")), locked=True)

    plan = _service(node)[0].plan(node)

    assert plan["ok"] is False
    assert "contents update requires an unlocked HDA instance" in plan["blockers"]


def test_copy_plan_reports_destination_type_overwrite_without_writing(tmp_path) -> None:
    library = tmp_path / "published.hda"
    library.write_bytes(b"not an HDA, fake HOM reads it only")
    node = FakeNode(FakeDefinition(str(tmp_path / "source.hda")))
    service, fake_hda = _service(node, ("acme::published::3.0",))

    plan = service.plan(
        node,
        mode="copy",
        library=str(library),
        type_name="acme::published::3.0",
        contents=False,
    )

    assert plan["ok"] is False
    assert plan["destination"]["target_type_exists"] is True
    assert plan["destination"]["overwrite_required"] is True
    assert "set overwrite=True" in plan["blockers"][-1]
    assert fake_hda.definition_reads == [str(library)]


def test_copy_plan_blocks_when_bounded_destination_scan_cannot_prove_no_conflict(tmp_path) -> None:
    library = tmp_path / "published.hda"
    library.write_bytes(b"not an HDA, fake HOM reads it only")
    node = FakeNode(FakeDefinition(str(tmp_path / "source.hda")))
    service, _hda = _service(node, ("acme::first::1.0", "acme::later::2.0"))

    plan = service.plan(
        node,
        mode="copy",
        library=str(library),
        contents=False,
        max_items=1,
    )

    assert plan["destination"]["definitions"]["truncated"] is True
    assert plan["destination"]["definitions"]["count_complete"] is False
    assert any("conflict is unknown" in blocker for blocker in plan["blockers"])


def test_plan_rejects_non_hda_invalid_library_and_rename_update(tmp_path) -> None:
    plain = FakeNode(None)
    with pytest.raises(ValueError, match="not an HDA instance"):
        _service(plain)[0].plan(plain)

    node = FakeNode(FakeDefinition(str(tmp_path / "source.hda")))
    service, _hda = _service(node)
    with pytest.raises(ValueError, match="library must use one of"):
        service.plan(node, library=str(tmp_path / "not-an-hda.txt"))

    plan = service.plan(node, type_name="acme::renamed::4.0")
    assert plan["ok"] is False
    assert any("update cannot rename" in blocker for blocker in plan["blockers"])
