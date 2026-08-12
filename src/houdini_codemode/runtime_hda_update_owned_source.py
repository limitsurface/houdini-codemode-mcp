"""Guarded lifecycle update for one isolated, explicitly owned HDA library.

This deliberately is not a general HDA create/update wrapper.  It accepts one
existing external library, verifies a sole unlocked instance, makes a durable
same-directory backup before mutation, and never installs a library or saves
the HIP file.
"""

from __future__ import annotations


HDA_UPDATE_OWNED_SOURCE = r'''
import hashlib as _hcm_hda_owned_hashlib
import os as _hcm_hda_owned_os
import shutil as _hcm_hda_owned_shutil
import uuid as _hcm_hda_owned_uuid


_HCM_HDA_OWNED_SUFFIXES = (".hda", ".hdalc", ".hdanc", ".otl")
_HCM_HDA_OWNED_MANAGED_SECTIONS = {"Contents.gz", "DialogScript"}


def _hcm_hda_owned_bool(value, name):
    if not isinstance(value, bool):
        raise TypeError(name + " must be a boolean")
    return value


def _hcm_hda_owned_limit(value, name, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(name + " must be an integer")
    if value < 1:
        raise ValueError(name + " must be positive")
    return min(value, maximum)


def _hcm_hda_owned_text(value, name, maximum=4096):
    if not isinstance(value, str) or not value.strip():
        raise TypeError(name + " must be a non-empty string")
    value = value.strip()
    if len(value) > maximum:
        raise ValueError(name + " exceeds " + str(maximum) + " characters")
    return value


def _hcm_hda_owned_path(value):
    value = _hcm_hda_owned_text(value, "owned_library")
    expand = getattr(_hcm_hou, "expandString", None)
    if callable(expand):
        try:
            value = expand(value)
        except BaseException:
            pass
    path = _hcm_hda_owned_os.path.realpath(
        _hcm_hda_owned_os.path.abspath(_hcm_hda_owned_os.path.normpath(value))
    )
    if _hcm_hda_owned_os.path.splitext(path)[1].lower() not in _HCM_HDA_OWNED_SUFFIXES:
        raise ValueError("owned_library must use one of: " + ", ".join(_HCM_HDA_OWNED_SUFFIXES))
    return path


def _hcm_hda_owned_same_path(left, right):
    return _hcm_hda_owned_os.path.normcase(_hcm_hda_owned_os.path.realpath(left)) == _hcm_hda_owned_os.path.normcase(_hcm_hda_owned_os.path.realpath(right))


def _hcm_hda_owned_under(path, root):
    try:
        return _hcm_hda_owned_os.path.commonpath((path, root)) == root
    except ValueError:
        return False


def _hcm_hda_owned_reject_hfs(path):
    candidates = []
    expand = getattr(_hcm_hou, "expandString", None)
    if callable(expand):
        try:
            expanded = str(expand("$HFS"))
        except BaseException:
            expanded = ""
        if expanded and expanded != "$HFS":
            candidates.append(expanded)
    environment = _hcm_hda_owned_os.environ.get("HFS", "")
    if environment:
        candidates.append(environment)
    for root in candidates:
        root = _hcm_hda_owned_os.path.realpath(_hcm_hda_owned_os.path.abspath(root))
        if _hcm_hda_owned_under(path, root):
            raise ValueError("update_owned refuses HFS/SideFX-installed HDA libraries")


def _hcm_hda_owned_digest(path, maximum):
    stat = _hcm_hda_owned_os.stat(path)
    size = int(stat.st_size)
    if size > maximum:
        raise ValueError("HDA library exceeds max_library_bytes: " + str(size))
    digest = _hcm_hda_owned_hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return {
        "path": path,
        "size": size,
        "mtime_ns": int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1000000000))),
        "sha256": digest.hexdigest(),
    }


def _hcm_hda_owned_instances(instance):
    method = getattr(instance.type(), "instances", None)
    if not callable(method):
        raise ValueError("Cannot verify a sole HDA instance: node type does not expose instances()")
    try:
        instances = list(method())
    except BaseException as exc:
        raise ValueError("Cannot verify a sole HDA instance: " + str(exc))
    paths = []
    for candidate in instances:
        try:
            paths.append(str(candidate.path()))
        except BaseException:
            raise ValueError("Cannot verify a sole HDA instance: an instance has no path")
    if paths != [str(instance.path())]:
        raise ValueError("update_owned requires a sole HDA instance; found " + str(len(paths)))
    return paths


def _hcm_hda_owned_section_text(section):
    # ``HDADefinition.addSection`` documents its ``contents`` argument as the
    # text returned by HDASection.contents().  Keep this primitive deliberately
    # text-only instead of assuming binaryContents() can be round-tripped
    # through every H22 addSection/compression combination.
    value = section.contents()
    if not isinstance(value, str):
        raise ValueError("Preserved HDA section is not text; binary sections are outside update_owned scope")
    return value


def _hcm_hda_owned_section_snapshot(definition, preserve_sections, preserve_tools, max_sections, max_section_bytes, max_total_section_bytes):
    snapshots = []
    total = 0
    sections = definition.sections()
    for name in sorted(str(value) for value in sections.keys()):
        if name in _HCM_HDA_OWNED_MANAGED_SECTIONS:
            continue
        is_tool = name.startswith("Tools.")
        if (is_tool and not preserve_tools) or (not is_tool and not preserve_sections):
            continue
        if len(snapshots) >= max_sections:
            raise ValueError("Preserved sections exceed max_sections")
        section = sections[name]
        try:
            declared_size = int(section.size())
        except BaseException:
            declared_size = None
        if declared_size is not None and declared_size > max_section_bytes:
            raise ValueError("Preserved section exceeds max_section_bytes: " + name)
        contents = _hcm_hda_owned_section_text(section)
        size = len(contents.encode("utf-8"))
        if size > max_section_bytes:
            raise ValueError("Preserved section exceeds max_section_bytes: " + name)
        total += size
        if total > max_total_section_bytes:
            raise ValueError("Preserved sections exceed max_total_section_bytes")
        snapshots.append({
            "name": name,
            "contents": contents,
            "manifest": {"name": name, "bytes": size, "sha256": _hcm_hda_owned_hashlib.sha256(contents.encode("utf-8")).hexdigest(), "tool_section": is_tool},
        })
    return snapshots


def _hcm_hda_owned_backup(library, before, enabled):
    if not enabled:
        return None
    directory = _hcm_hda_owned_os.path.dirname(library)
    name = _hcm_hda_owned_os.path.basename(library)
    backup = _hcm_hda_owned_os.path.join(directory, "." + name + ".hcm-backup-" + _hcm_hda_owned_uuid.uuid4().hex)
    _hcm_hda_owned_shutil.copy2(library, backup)
    manifest = _hcm_hda_owned_digest(backup, max(before["size"], 1))
    if manifest["sha256"] != before["sha256"] or manifest["size"] != before["size"]:
        try:
            _hcm_hda_owned_os.remove(backup)
        except OSError:
            pass
        raise RuntimeError("HDA backup verification failed")
    return {"path": backup, "manifest": manifest}


def _hcm_hda_owned_validate(instance, enabled, cook, maximum):
    if not enabled:
        return None
    service_type = globals().get("_HCMHdaService")
    if service_type is None:
        raise RuntimeError("ctx.hda.validate runtime service is unavailable for update_owned validation")
    service = service_type([])
    return service.validate(
        instance, fresh=True, cook=cook, strict=False,
        external_references=False, dry_run=False, max_items=maximum,
    )


class _HCMHdaUpdateOwnedService:
    """Mutate one existing isolated HDA definition after explicit ownership checks."""

    def __init__(self, mutation_events=None):
        self._mutation_events = mutation_events if mutation_events is not None else []

    def update_owned(
        self,
        node,
        owned_library,
        allow_library_write=False,
        contents=True,
        interface=False,
        preserve_sections=True,
        preserve_tools=True,
        create_backup=True,
        match_current=False,
        validate=True,
        validation_cook=False,
        max_sections=100,
        max_section_bytes=1048576,
        max_total_section_bytes=8388608,
        max_library_bytes=536870912,
    ):
        for value, name in (
            (allow_library_write, "allow_library_write"), (contents, "contents"),
            (interface, "interface"), (preserve_sections, "preserve_sections"),
            (preserve_tools, "preserve_tools"), (create_backup, "create_backup"),
            (match_current, "match_current"), (validate, "validate"),
            (validation_cook, "validation_cook"),
        ):
            _hcm_hda_owned_bool(value, name)
        if not contents and not interface:
            raise ValueError("update_owned requires contents=True or interface=True")
        if not allow_library_write:
            raise ValueError("update_owned writes the HDA library; set allow_library_write=True after reviewing the effects")
        section_limit = _hcm_hda_owned_limit(max_sections, "max_sections", 1000)
        section_byte_limit = _hcm_hda_owned_limit(max_section_bytes, "max_section_bytes", 67108864)
        section_total_limit = _hcm_hda_owned_limit(max_total_section_bytes, "max_total_section_bytes", 268435456)
        library_byte_limit = _hcm_hda_owned_limit(max_library_bytes, "max_library_bytes", 2147483648)
        library = _hcm_hda_owned_path(owned_library)
        instance = _hcm_resolve_node(node, "node")
        definition = instance.type().definition()
        if definition is None:
            raise ValueError("Node is not an HDA instance: " + str(instance.path()))
        definition_library = str(definition.libraryFilePath())
        if definition_library == "Embedded":
            raise ValueError("update_owned does not support embedded HDA definitions")
        if not _hcm_hda_owned_same_path(definition_library, library):
            raise ValueError("owned_library must exactly match the HDA definition library")
        _hcm_hda_owned_reject_hfs(library)
        if not _hcm_hda_owned_os.path.isfile(library):
            raise ValueError("owned_library must be an existing regular HDA library file")
        if bool(instance.isLockedHDA()):
            raise ValueError("update_owned requires an unlocked HDA instance")
        isolated_paths = _hcm_hda_owned_instances(instance)
        before = _hcm_hda_owned_digest(library, library_byte_limit)
        snapshots = _hcm_hda_owned_section_snapshot(
            definition, preserve_sections, preserve_tools, section_limit,
            section_byte_limit, section_total_limit,
        )
        events = [{
            "kind": "hda.update_owned.preflight", "node_path": str(instance.path()),
            "library": library, "sole_instance_paths": isolated_paths,
            "contents": contents, "interface": interface,
            "contents_checkpoint_required": True,
            "preserved_sections": len(snapshots),
        }]
        backup = None
        try:
            backup = _hcm_hda_owned_backup(library, before, create_backup)
            if backup is not None:
                events.append({"kind": "hda.update_owned.backup", "path": backup["path"], "sha256": backup["manifest"]["sha256"]})

            # This is both the requested contents update and the mandatory
            # checkpoint before any optional interface sync can discard edits.
            checkpoint = {"kind": "hda.update_owned.updateFromNode", "status": "started", "library_write": "implicit_by_HOM", "checkpoint": True}
            events.append(checkpoint)
            definition.updateFromNode(instance)
            checkpoint["status"] = "complete"

            if interface:
                definition.setParmTemplateGroup(
                    instance.parmTemplateGroup(), rename_conflicting_parms=False,
                    create_backup=False,
                )
                events.append({"kind": "hda.update_owned.setParmTemplateGroup", "library_write": "implicit_by_HOM", "source": "instance.parmTemplateGroup", "create_backup": False})

            for snapshot in snapshots:
                definition.addSection(snapshot["name"], snapshot["contents"])
                events.append({"kind": "hda.update_owned.restore_section", "name": snapshot["name"], "bytes": snapshot["manifest"]["bytes"], "tool_section": snapshot["manifest"]["tool_section"]})

            if match_current:
                instance.matchCurrentDefinition()
                events.append({"kind": "hda.update_owned.matchCurrentDefinition", "node_path": str(instance.path()), "after_checkpoint": True})
            validation = _hcm_hda_owned_validate(instance, validate, validation_cook, section_limit)
            if validation is not None:
                events.append({"kind": "hda.update_owned.validate", "fresh": True, "cook": validation_cook, "ok": bool(validation.get("ok", False))})
        except BaseException as exc:
            if events and events[-1].get("kind") == "hda.update_owned.updateFromNode" and events[-1].get("status") == "started":
                events[-1]["status"] = "error"
            events.append({"kind": "hda.update_owned.failure", "error": str(exc), "rollback": "not attempted; restore the verified backup manually after unloading/reloading as appropriate"})
            self._mutation_events.extend(events)
            raise RuntimeError("update_owned failed after possible HDA library mutation; no automatic rollback was attempted. Backup: " + (backup["path"] if backup is not None else "not created") + ". Cause: " + str(exc))

        after = _hcm_hda_owned_digest(library, library_byte_limit)
        self._mutation_events.extend(events)
        return {
            "operation": "hda.update_owned", "ok": True,
            "node_path": str(instance.path()), "sole_instance_paths": isolated_paths,
            "surfaces": {
                "contents": contents,
                "interface": interface,
                "interface_source": "instance.parmTemplateGroup" if interface else None,
                "contents_checkpointed": True,
                "checkpoint_reason": (
                    "requested contents update" if contents
                    else "mandatory preservation checkpoint before an interface-only definition mutation"
                ),
            },
            "library": {"before": before, "after": after, "backup": backup, "install_called": False, "hda_definition_save_called": False, "hip_save_called": False},
            "preserved_sections": [snapshot["manifest"] for snapshot in snapshots],
            "preservation_scope": {"non_tool_sections": preserve_sections, "tool_sections_prefix": "Tools.", "tool_sections": preserve_tools, "managed_sections_excluded": sorted(_HCM_HDA_OWNED_MANAGED_SECTIONS)},
            "match_current_called": match_current,
            "validation": validation,
            "events": events,
            "rollback_limits": "Non-transactional. A verified pre-mutation backup remains on disk when create_backup=True; this operation never reloads or overwrites a loaded HDA library to roll back. Restore it manually after reviewing affected instances.",
        }
'''
