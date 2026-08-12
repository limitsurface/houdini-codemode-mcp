from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import pytest
from houdini_codemode.runtime_hda_create_owned_source import HDA_CREATE_OWNED_SOURCE

class Definition:
    def __init__(self, library, type_name): self.library, self.type_name = library, type_name
    def libraryFilePath(self): return self.library
    def nodeType(self): return SimpleNamespace(name=lambda: self.type_name)

class Asset:
    def __init__(self, path, definition): self.path_value, self.definition = path, definition
    def path(self): return self.path_value
    def type(self): return SimpleNamespace(definition=lambda: self.definition, name=lambda: self.definition.type_name)

class Source:
    def __init__(self, root): self.root, self.asset, self.calls = root, None, []
    def path(self): return "/obj/source_subnet"
    def type(self): return SimpleNamespace(definition=lambda: None, name=lambda: "subnet")
    def canCreateDigitalAsset(self): return True
    def createDigitalAsset(self, **kwargs):
        self.calls.append(kwargs); Path(kwargs["hda_file_name"]).write_bytes(b"created")
        definition = Definition(kwargs["hda_file_name"], kwargs["name"]); self.asset = Asset(self.path(), definition); return self.asset

def _service(tmp_path):
    source = Source(tmp_path); definitions = lambda path: [source.asset.definition] if source.asset is not None else []
    namespace = {"_hcm_resolve_node": lambda value, _label="node": source, "_hcm_hou": SimpleNamespace(expandString=lambda value: "" if value == "$HFS" else value, hda=SimpleNamespace(definitionsInFile=definitions))}
    exec(HDA_CREATE_OWNED_SOURCE, namespace); return namespace["_HCMHdaCreateOwnedService"](), source

def test_plan_is_new_path_only_and_non_mutating(tmp_path):
    service, source = _service(tmp_path); target = tmp_path / "asset.hda"
    plan = service.plan(source, "acme::asset", "Asset", str(target), 0, 2)
    assert plan["ok"] and plan["destination"]["manifest"]["exists"] is False and source.calls == []
    target.write_bytes(b"exists")
    with pytest.raises(FileExistsError, match="new"):
        service.plan(source, "acme::asset", "Asset", str(target))

def test_create_requires_opt_in_and_reports_unavoidable_install(tmp_path):
    service, source = _service(tmp_path); target = tmp_path / "asset.hda"
    with pytest.raises(ValueError, match="allow_library_write=True"):
        service.create_owned(source, "acme::asset", "Asset", str(target))
    result = service.create_owned(source, "acme::asset", "Asset", str(target), 1, 2, allow_library_write=True)
    assert target.read_bytes() == b"created" and result["library"]["installed_library"] is True
    assert source.calls[0]["change_node_type"] is True and source.calls[0]["create_backup"] is False
    assert [event["kind"] for event in result["events"]] == ["hda.create_owned.createDigitalAsset"]

def test_rejects_hda_source_bad_type_and_missing_parent(tmp_path):
    service, source = _service(tmp_path)
    with pytest.raises(ValueError, match="safe namespace"):
        service.plan(source, "unsafe", "Asset", str(tmp_path / "a.hda"))
    with pytest.raises(ValueError, match="parent directory"):
        service.plan(source, "acme::asset", "Asset", str(tmp_path / "nope" / "a.hda"))
