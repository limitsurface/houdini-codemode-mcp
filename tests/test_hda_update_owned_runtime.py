from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from houdini_codemode.runtime_hda_update_owned_source import HDA_UPDATE_OWNED_SOURCE


class FakeSection:
    def __init__(self, contents: str):
        self._contents = contents

    def size(self):
        return len(self._contents.encode("utf-8"))

    def contents(self):
        return self._contents


class FakeDefinition:
    def __init__(self, library: str, *, fail_update=False):
        self._library = library
        self._fail_update = fail_update
        self.update_calls = 0
        self.interface_calls = []
        self.sections_added = []
        self._sections = {
            "Contents.gz": FakeSection("managed"),
            "DialogScript": FakeSection("managed-ui"),
            "ExtraFile": FakeSection("preserve"),
            "Tools.shelf": FakeSection("preserve-tool"),
        }

    def libraryFilePath(self):
        return self._library

    def sections(self):
        return dict(self._sections)

    def updateFromNode(self, _node):
        self.update_calls += 1
        with open(self._library, "ab") as handle:
            handle.write(b"U")
        if self._fail_update:
            raise RuntimeError("simulated update failure")

    def parmTemplateGroup(self):
        return "definition-group"

    def setParmTemplateGroup(self, group, **kwargs):
        self.interface_calls.append((group, kwargs))
        with open(self._library, "ab") as handle:
            handle.write(b"I")

    def addSection(self, name, contents):
        self.sections_added.append((name, contents))


class FakeType:
    def __init__(self, definition, instances):
        self._definition = definition
        self._instances = instances

    def definition(self):
        return self._definition

    def instances(self):
        return tuple(self._instances)


class FakeNode:
    def __init__(self, definition, path="/obj/asset", locked=False):
        self._path = path
        self._locked = locked
        self._type = FakeType(definition, [self])
        self.matched = False

    def path(self):
        return self._path

    def type(self):
        return self._type

    def isLockedHDA(self):
        return self._locked

    def parmTemplateGroup(self):
        return "instance-group"

    def matchCurrentDefinition(self):
        self.matched = True
        self._locked = True


class FakeValidationService:
    def __init__(self, events):
        self.events = events

    def validate(self, node, **kwargs):
        return {"ok": True, "node_path": node.path(), "kwargs": kwargs}


def _service(tmp_path: Path, *, fail_update=False, locked=False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    library = tmp_path / "owned.hda"
    library.write_bytes(b"before")
    definition = FakeDefinition(str(library), fail_update=fail_update)
    node = FakeNode(definition, locked=locked)
    events = []
    namespace = {
        "_hcm_hou": SimpleNamespace(expandString=lambda value: value),
        "_hcm_resolve_node": lambda value, _label="node": node,
        "_HCMHdaService": FakeValidationService,
    }
    exec(HDA_UPDATE_OWNED_SOURCE, namespace)
    return namespace["_HCMHdaUpdateOwnedService"](events), node, definition, library, events


def test_update_owned_requires_explicit_ownership_and_opt_in_before_write(tmp_path: Path) -> None:
    service, node, definition, library, _events = _service(tmp_path)

    with pytest.raises(ValueError, match="allow_library_write=True"):
        service.update_owned(node, str(library))
    with pytest.raises(ValueError, match="exactly match"):
        service.update_owned(node, str(tmp_path / "other.hda"), allow_library_write=True)

    assert library.read_bytes() == b"before"
    assert definition.update_calls == 0


def test_update_owned_checkpoints_preserves_sections_backs_up_and_validates(tmp_path: Path) -> None:
    service, node, definition, library, events = _service(tmp_path)

    result = service.update_owned(
        node,
        str(library),
        allow_library_write=True,
        contents=True,
        interface=True,
        match_current=True,
    )

    assert definition.update_calls == 1
    assert definition.interface_calls == [
        ("instance-group", {"rename_conflicting_parms": False, "create_backup": False})
    ]
    assert definition.sections_added == [
        ("ExtraFile", "preserve"), ("Tools.shelf", "preserve-tool")
    ]
    assert node.matched is True
    assert result["library"]["before"]["sha256"] != result["library"]["after"]["sha256"]
    backup = Path(result["library"]["backup"]["path"])
    assert backup.read_bytes() == b"before"
    assert result["validation"]["ok"] is True
    assert result["validation"]["kwargs"]["fresh"] is True
    assert result["library"]["install_called"] is False
    assert result["library"]["hda_definition_save_called"] is False
    assert result["library"]["hip_save_called"] is False
    assert [event["kind"] for event in events] == [
        "hda.update_owned.preflight",
        "hda.update_owned.backup",
        "hda.update_owned.updateFromNode",
        "hda.update_owned.setParmTemplateGroup",
        "hda.update_owned.restore_section",
        "hda.update_owned.restore_section",
        "hda.update_owned.matchCurrentDefinition",
        "hda.update_owned.validate",
    ]


def test_interface_only_still_checkpoints_before_optional_match(tmp_path: Path) -> None:
    service, node, definition, library, _events = _service(tmp_path)

    result = service.update_owned(
        node, str(library), allow_library_write=True,
        contents=False, interface=True, match_current=False, validate=False,
    )

    assert definition.update_calls == 1
    assert result["surfaces"] == {
        "contents": False,
        "interface": True,
        "interface_source": "instance.parmTemplateGroup",
        "contents_checkpointed": True,
        "checkpoint_reason": "mandatory preservation checkpoint before an interface-only definition mutation",
    }
    assert result["match_current_called"] is False
    assert node.matched is False


def test_update_owned_failure_retains_verified_backup_and_never_auto_rolls_back(tmp_path: Path) -> None:
    service, node, definition, library, events = _service(tmp_path, fail_update=True)

    with pytest.raises(RuntimeError, match="no automatic rollback was attempted"):
        service.update_owned(node, str(library), allow_library_write=True, validate=False)

    backups = list(tmp_path.glob(".owned.hda.hcm-backup-*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"before"
    assert library.read_bytes() == b"beforeU"
    assert definition.interface_calls == []
    assert events[-1]["kind"] == "hda.update_owned.failure"
    assert "not attempted" in events[-1]["rollback"]


def test_update_owned_rejects_locked_or_multiple_instances_without_mutation(tmp_path: Path) -> None:
    service, node, definition, library, _events = _service(tmp_path, locked=True)
    with pytest.raises(ValueError, match="unlocked"):
        service.update_owned(node, str(library), allow_library_write=True)
    assert library.read_bytes() == b"before"

    service, node, definition, library, _events = _service(tmp_path / "multiple")
    other = FakeNode(definition, path="/obj/other")
    node.type()._instances = [node, other]
    with pytest.raises(ValueError, match="sole HDA instance"):
        service.update_owned(node, str(library), allow_library_write=True)
    assert library.read_bytes() == b"before"
