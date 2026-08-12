"""Narrow, owned-library HDA *plain text* section service.

This is intentionally an integration-ready runtime source rather than an
addition to the broad HDA helper.  Section writes are definition/library
mutations, so callers must make the ownership and write opt-in explicit.
``Tools.shelf`` is excluded: its XML is a UI/tool registration surface and
needs a dedicated contract rather than being treated as an opaque section.
"""

from __future__ import annotations


HDA_SECTION_SOURCE = r'''
import hashlib as _hcm_hda_section_hashlib
import os as _hcm_hda_section_os
import shutil as _hcm_hda_section_shutil
import tempfile as _hcm_hda_section_tempfile


_HCM_HDA_SECTION_SUFFIXES = (".hda", ".hdalc", ".hdanc", ".otl")
_HCM_HDA_SECTION_MAX_NAME_BYTES = 512
_HCM_HDA_SECTION_MAX_CONTENT_BYTES = 262144
_HCM_HDA_SECTION_RESERVED = {
    "Contents.gz", "DialogScript", "ExtraFileOptions", "Tools.shelf",
}


def _hcm_hda_section_bool(value, name):
    if not isinstance(value, bool):
        raise TypeError(name + " must be a boolean")
    return value


def _hcm_hda_section_limit(value, name, ceiling):
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(name + " must be an integer")
    if value < 1 or value > ceiling:
        raise ValueError(name + " must be between 1 and " + str(ceiling))
    return value


def _hcm_hda_section_text(value, name, maximum):
    if not isinstance(value, str) or not value:
        raise TypeError(name + " must be a non-empty string")
    encoded = value.encode("utf-8")
    if len(encoded) > maximum:
        raise ValueError(name + " exceeds " + str(maximum) + " UTF-8 bytes")
    return value, len(encoded)


def _hcm_hda_section_name(value):
    name, size = _hcm_hda_section_text(value, "name", _HCM_HDA_SECTION_MAX_NAME_BYTES)
    if name in _HCM_HDA_SECTION_RESERVED:
        if name == "Tools.shelf":
            raise ValueError("Tools.shelf requires a dedicated tool-registration operation and is not a plain section")
        raise ValueError("Refusing Houdini-managed HDA section: " + name)
    return name, size


def _hcm_hda_section_absolute_path(value, name):
    value, _unused = _hcm_hda_section_text(value, name, 4096)
    expand = getattr(_hcm_hou, "expandString", None)
    if callable(expand):
        try:
            value = expand(value)
        except BaseException:
            pass
    return _hcm_hda_section_os.path.realpath(
        _hcm_hda_section_os.path.abspath(_hcm_hda_section_os.path.normpath(_hcm_hda_section_os.path.expandvars(value)))
    )


def _hcm_hda_section_path(value, name):
    path = _hcm_hda_section_absolute_path(value, name)
    if _hcm_hda_section_os.path.splitext(path)[1].lower() not in _HCM_HDA_SECTION_SUFFIXES:
        raise ValueError(name + " must use one of: " + ", ".join(_HCM_HDA_SECTION_SUFFIXES))
    return path


def _hcm_hda_section_under(path, root):
    try:
        return _hcm_hda_section_os.path.commonpath((path, root)) == root
    except ValueError:
        return False


def _hcm_hda_section_reject_hfs(path):
    expand = getattr(_hcm_hou, "expandString", None)
    hfs = ""
    if callable(expand):
        try:
            hfs = str(expand("$HFS"))
        except BaseException:
            hfs = ""
    if not hfs or hfs == "$HFS":
        hfs = _hcm_hda_section_os.environ.get("HFS", "")
    if hfs and _hcm_hda_section_under(path, _hcm_hda_section_absolute_path(hfs, "HFS")):
        raise ValueError("owned_library must not be inside HFS / the Houdini installation")


def _hcm_hda_section_manifest(path):
    stat = _hcm_hda_section_os.stat(path)
    digest = _hcm_hda_section_hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": path, "size": int(stat.st_size),
        "mtime_ns": int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1000000000))),
        "sha256": digest.hexdigest(),
    }


def _hcm_hda_section_backup_path(library):
    directory, filename = _hcm_hda_section_os.path.split(library)
    stem, extension = _hcm_hda_section_os.path.splitext(filename)
    descriptor, path = _hcm_hda_section_tempfile.mkstemp(
        prefix="." + stem + ".hcm-section-backup-", suffix=extension, dir=directory
    )
    _hcm_hda_section_os.close(descriptor)
    return path


def _hcm_hda_section_instances(instance):
    method = getattr(instance.type(), "instances", None)
    if not callable(method):
        raise ValueError("Cannot verify a sole HDA instance: node type does not expose instances()")
    try:
        instances = list(method())
    except BaseException as exc:
        raise ValueError("Cannot verify a sole HDA instance: " + str(exc))
    paths = [str(candidate.path()) for candidate in instances]
    if paths != [str(instance.path())]:
        raise ValueError("Plain section mutation requires the definition's sole instance; found {} instance(s)".format(len(paths)))
    return paths


def _hcm_hda_section_preflight(node, owned_library):
    instance = _hcm_resolve_node(node, "node")
    definition = instance.type().definition()
    if definition is None:
        raise ValueError("Node is not an HDA instance: " + str(instance.path()))
    library_value = str(definition.libraryFilePath())
    if not library_value or library_value == "Embedded":
        raise ValueError("Embedded HDA definitions are not supported")
    library = _hcm_hda_section_path(library_value, "definition library")
    owned = _hcm_hda_section_path(owned_library, "owned_library")
    if _hcm_hda_section_os.path.normcase(library) != _hcm_hda_section_os.path.normcase(owned):
        raise ValueError("owned_library must exactly match the HDA definition library")
    _hcm_hda_section_reject_hfs(library)
    if not _hcm_hda_section_os.path.isfile(library):
        raise ValueError("owned_library must be an existing regular HDA library file")
    instances = _hcm_hda_section_instances(instance)
    definitions_method = getattr(getattr(_hcm_hou, "hda", None), "definitionsInFile", None)
    if not callable(definitions_method):
        raise ValueError("Cannot verify the owned library contains a sole definition")
    try:
        definitions = list(definitions_method(library))
    except BaseException as exc:
        raise ValueError("Cannot inspect owned_library definitions: " + str(exc))
    type_names = [str(item.nodeType().name()) for item in definitions]
    type_name = str(instance.type().name())
    if len(type_names) != 1 or type_names != [type_name]:
        raise ValueError("Plain section mutation requires owned_library to contain exactly this one HDA definition")
    return instance, definition, library, instances, type_name


def _hcm_hda_section_existing(definition, name):
    try:
        return definition.sections().get(name)
    except BaseException as exc:
        raise ValueError("Cannot inspect HDA sections: " + str(exc))


class _HCMHdaSectionService:
    """Plan, read, then mutate one owned text/plain HDA section."""

    def __init__(self, mutation_events=None):
        self._mutation_events = mutation_events if mutation_events is not None else []

    def plan(self, node, name, action="set", contents=None, owned_library=None, max_content_bytes=262144):
        if action not in ("set", "delete"):
            raise ValueError("action must be 'set' or 'delete'")
        maximum = _hcm_hda_section_limit(max_content_bytes, "max_content_bytes", _HCM_HDA_SECTION_MAX_CONTENT_BYTES)
        name, name_bytes = _hcm_hda_section_name(name)
        if owned_library is None:
            raise TypeError("owned_library must be an explicit non-empty string")
        content_bytes = None
        if action == "set":
            contents, content_bytes = _hcm_hda_section_text(contents, "contents", maximum)
        elif contents is not None:
            raise ValueError("contents must be null when action='delete'")
        instance, definition, library, instances, type_name = _hcm_hda_section_preflight(node, owned_library)
        existing = _hcm_hda_section_existing(definition, name)
        existing_size = None
        if existing is not None:
            try:
                existing_size = int(existing.size())
            except BaseException:
                pass
        blockers = []
        if action == "delete" and existing is None:
            blockers.append("HDA section not found: " + name)
        return {
            "operation": "hda.sections.plan", "dry_run": True, "ok": not blockers,
            "blockers": blockers, "action": action,
            "node_path": str(instance.path()), "type_name": type_name,
            "library": {"path": library, "manifest": _hcm_hda_section_manifest(library), "sole_instance_paths": instances, "sole_definition": True},
            "section": {"name": name, "name_utf8_bytes": name_bytes, "existing": existing is not None, "existing_size": existing_size, "content_utf8_bytes": content_bytes, "max_content_bytes": maximum},
            "future_events": [
                {"kind": "hda.sections.preflight", "mutates": False},
                {"kind": "hda.definition.addSection" if action == "set" else "hda.definition.removeSection", "mutates_definition": True, "writes_library": "implicit_by_HOM"},
            ],
            "expected_effects": {"current_call": {"writes_library": False, "installs_library": False, "saves_hip": False}, "apply": {"writes_library": True, "installs_library": False, "saves_hip": False, "may_affect_other_instances": False}},
            "rollback_limits": ["No mutation occurs in plan.", "HOM section writes are not transactional; an optional file backup is an external recovery artifact, not an in-session rollback."],
        }

    def read(self, node, name, owned_library=None, max_content_bytes=262144):
        maximum = _hcm_hda_section_limit(max_content_bytes, "max_content_bytes", _HCM_HDA_SECTION_MAX_CONTENT_BYTES)
        name, name_bytes = _hcm_hda_section_name(name)
        if owned_library is None:
            raise TypeError("owned_library must be an explicit non-empty string")
        instance, definition, library, instances, type_name = _hcm_hda_section_preflight(node, owned_library)
        section = _hcm_hda_section_existing(definition, name)
        if section is None:
            raise ValueError("HDA section not found: " + name)
        reported_size = int(section.size())
        if reported_size > maximum:
            raise ValueError("HDA section exceeds max_content_bytes before read")
        contents = section.contents()
        if not isinstance(contents, str):
            raise ValueError("Only UTF-8 text/plain HDA sections are supported")
        actual_bytes = len(contents.encode("utf-8"))
        if actual_bytes > maximum:
            raise ValueError("HDA section exceeds max_content_bytes after read")
        return {"operation": "hda.sections.read", "node_path": str(instance.path()), "type_name": type_name, "library": {"path": library, "sole_instance_paths": instances, "sole_definition": True}, "section": {"name": name, "name_utf8_bytes": name_bytes, "reported_size": reported_size, "content_utf8_bytes": actual_bytes, "max_content_bytes": maximum, "contents": contents}, "effects": {"writes_library": False, "installs_library": False, "saves_hip": False}}

    def apply(self, node, name, action="set", contents=None, owned_library=None, allow_library_write=False, create_backup=True, max_content_bytes=262144):
        _hcm_hda_section_bool(allow_library_write, "allow_library_write")
        _hcm_hda_section_bool(create_backup, "create_backup")
        if not allow_library_write:
            raise ValueError("Section apply writes the HDA library; set allow_library_write=True after reviewing the plan")
        plan = self.plan(node, name, action, contents, owned_library, max_content_bytes)
        if not plan["ok"]:
            raise ValueError("Section preflight failed: " + "; ".join(plan["blockers"]))
        # Re-resolve all ownership facts immediately before the implicit HOM write.
        instance, definition, library, instances, type_name = _hcm_hda_section_preflight(node, owned_library)
        name = plan["section"]["name"]
        before = _hcm_hda_section_manifest(library)
        events = [{"kind": "hda.sections.preflight", "node_path": str(instance.path()), "library": library, "sole_instance_paths": instances, "sole_definition": True}]
        backup = None
        if create_backup:
            backup_path = _hcm_hda_section_backup_path(library)
            _hcm_hda_section_shutil.copy2(library, backup_path)
            backup = {"path": backup_path, "manifest": _hcm_hda_section_manifest(backup_path)}
            if backup["manifest"]["sha256"] != before["sha256"]:
                raise RuntimeError("HDA section backup verification failed")
            events.append({"kind": "hda.sections.backup", "path": backup_path, "manifest": backup["manifest"]})
        event = {"kind": "hda.definition.addSection" if action == "set" else "hda.definition.removeSection", "name": name, "library_write": "implicit_by_HOM", "status": "started"}
        events.append(event)
        try:
            if action == "set":
                definition.addSection(name, contents)
            else:
                definition.removeSection(name)
            event["status"] = "complete"
        except BaseException:
            event["status"] = "error"
            self._mutation_events.extend(events)
            raise
        after = _hcm_hda_section_manifest(library)
        self._mutation_events.extend(events)
        return {"operation": "hda.sections.apply", "ok": True, "action": action, "node_path": str(instance.path()), "type_name": type_name, "section": {"name": name, "content_utf8_bytes": plan["section"]["content_utf8_bytes"]}, "library": {"before": before, "after": after, "backup": backup, "hda_definition_save_called": False, "install_called": False, "hip_save_called": False}, "events": events, "rollback_limits": "Non-transactional: addSection/removeSection writes the loaded definition/library immediately. The optional backup is verified but is not automatically restored because that cannot reliably synchronize the live loaded definition."}
'''
