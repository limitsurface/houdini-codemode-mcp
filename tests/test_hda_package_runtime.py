from __future__ import annotations

from types import SimpleNamespace

import pytest

from houdini_codemode.runtime_hda_package_source import HDA_PACKAGE_SOURCE


class FakeDefinition:
    def __init__(self, library, payload=b"new-library", fail=False):
        self._library = library
        self._payload = payload
        self._fail = fail
        self.copy_calls = []

    def libraryFilePath(self):
        return self._library

    def copyToHDAFile(self, path, new_name=None, new_menu_name=None):
        self.copy_calls.append((path, new_name, new_menu_name))
        if self._fail:
            raise RuntimeError("simulated HOM write failure")
        with open(path, "wb") as stream:
            stream.write(self._payload)


class FakeNodeType:
    def __init__(self, definition, name="acme::tool::1.0"):
        self._definition = definition
        self._name = name

    def definition(self):
        return self._definition

    def name(self):
        return self._name


class FakeNode:
    def __init__(self, definition):
        self._definition = definition

    def path(self):
        return "/obj/geo1/tool1"

    def type(self):
        return FakeNodeType(self._definition)


class FakePlanner:
    def __init__(self, target_type="acme::tool::1.0", destination_types=(), ok=True):
        self.target_type = target_type
        self.destination_types = tuple(destination_types)
        self.ok = ok
        self.calls = []

    def plan(self, node, **kwargs):
        self.calls.append((node, kwargs))
        types = list(self.destination_types)
        return {
            "ok": self.ok,
            "blockers": [] if self.ok else ["fake preflight blocker"],
            "definition": {"target_type": self.target_type},
            "destination": {
                "definitions": {
                    "available": True,
                    "count": len(types),
                    "count_complete": True,
                    "types": types,
                }
            },
        }


class SideEffectGuard:
    def __init__(self, loaded=()):
        self.install_calls = 0
        self.save_calls = 0
        self._loaded = tuple(loaded)

    def installFile(self, *_args, **_kwargs):
        self.install_calls += 1
        raise AssertionError("packaging must not install a library")

    def save(self, *_args, **_kwargs):
        self.save_calls += 1
        raise AssertionError("packaging must not save the HIP")

    def loadedFiles(self):
        return self._loaded


def _service(node, planner, events=None, install_root=None, loaded=()):
    guard = SideEffectGuard(loaded)
    namespace = {
        "_hcm_hou": SimpleNamespace(
            expandString=lambda value: value,
            getenv=lambda name: install_root if name == "HFS" else None,
            applicationPath=lambda: "",
            hda=guard,
            hipFile=guard,
        ),
        "_hcm_resolve_node": lambda value, _label="node": node,
    }
    exec(HDA_PACKAGE_SOURCE, namespace)
    service = namespace["_HCMHdaPackageService"](events, planner)
    service._test_guard = guard
    return service


def test_copy_failure_creates_no_target_and_cleans_staging(tmp_path) -> None:
    source = tmp_path / "source.hda"
    source.write_bytes(b"source")
    target = tmp_path / "published.hda"
    definition = FakeDefinition(str(source), fail=True)
    events = []
    service = _service(FakeNode(definition), FakePlanner(), events)

    with pytest.raises(RuntimeError, match="simulated HOM"):
        service.copy("/obj/geo1/tool1", str(target))

    assert not target.exists()
    assert list(tmp_path.glob(".published.hcm-*")) == []
    assert events[-1]["before"]["exists"] is False
    assert events[-1]["after"]["exists"] is False


def test_copy_failure_preserves_existing_target(tmp_path) -> None:
    source = tmp_path / "source.hda"
    source.write_bytes(b"source")
    target = tmp_path / "published.hda"
    target.write_bytes(b"old-target")
    definition = FakeDefinition(str(source), fail=True)
    service = _service(
        FakeNode(definition), FakePlanner(destination_types=("acme::tool::1.0",))
    )

    with pytest.raises(RuntimeError, match="simulated HOM"):
        service.copy("/obj/geo1/tool1", str(target), overwrite=True)

    assert target.read_bytes() == b"old-target"


def test_copy_successfully_stages_and_publishes_new_library_without_scene_effects(tmp_path) -> None:
    source = tmp_path / "source.hda"
    source.write_bytes(b"source")
    target = tmp_path / "published.hda"
    definition = FakeDefinition(str(source), payload=b"published")
    events = []
    planner = FakePlanner()
    service = _service(FakeNode(definition), planner, events)

    result = service.copy("/obj/geo1/tool1", str(target), label="Published Tool")

    assert target.read_bytes() == b"published"
    assert result["before"]["exists"] is False
    assert result["after"]["sha256"]
    assert result["library_installed"] is False
    assert result["instance_changed"] is False
    assert result["hip_saved"] is False
    assert definition.copy_calls[0][1:] == ("acme::tool::1.0", "Published Tool")
    assert planner.calls[0][1]["mode"] == "copy"
    assert events[-1]["installed_library"] is False
    assert service._test_guard.install_calls == 0
    assert service._test_guard.save_calls == 0


def test_overwrite_requires_explicit_consent_and_can_create_verified_backup(tmp_path) -> None:
    source = tmp_path / "source.hda"
    source.write_bytes(b"source")
    target = tmp_path / "published.hda"
    target.write_bytes(b"old-target")
    definition = FakeDefinition(str(source), payload=b"replacement")
    planner = FakePlanner(destination_types=("acme::tool::1.0",))
    service = _service(FakeNode(definition), planner)

    with pytest.raises(FileExistsError, match="already exists"):
        service.copy("/obj/geo1/tool1", str(target))
    assert target.read_bytes() == b"old-target"

    result = service.copy("/obj/geo1/tool1", str(target), overwrite=True, backup=True)

    assert target.read_bytes() == b"replacement"
    assert result["backup"] is not None
    assert open(result["backup"]["path"], "rb").read() == b"old-target"
    assert result["backup"]["manifest"]["sha256"] == result["before"]["sha256"]


def test_rejects_embedded_or_houdini_install_libraries(tmp_path) -> None:
    install = tmp_path / "houdini-install"
    install.mkdir()
    target = tmp_path / "published.hda"
    embedded = FakeNode(FakeDefinition("Embedded"))

    with pytest.raises(ValueError, match="Embedded"):
        _service(embedded, FakePlanner(), install_root=str(install)).copy(embedded, str(target))

    source = tmp_path / "source.hda"
    source.write_bytes(b"source")
    node = FakeNode(FakeDefinition(str(source)))
    with pytest.raises(ValueError, match="Houdini installation"):
        _service(node, FakePlanner(), install_root=str(install)).copy(node, str(install / "published.hda"))


def test_rejects_a_currently_loaded_destination_library(tmp_path) -> None:
    source = tmp_path / "source.hda"
    source.write_bytes(b"source")
    destination = tmp_path / "published.hda"
    destination.write_bytes(b"loaded target")
    definition = FakeDefinition(str(source))
    service = _service(
        FakeNode(definition),
        FakePlanner(destination_types=("acme::tool::1.0",)),
        loaded=(str(destination),),
    )

    with pytest.raises(ValueError, match="currently loaded"):
        service.copy("/obj/geo1/tool1", str(destination), overwrite=True)

    assert destination.read_bytes() == b"loaded target"
    assert definition.copy_calls == []
