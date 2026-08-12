"""Read-only planning for updating or copying an existing HDA definition.

The embedded source deliberately reports the HOM calls an eventual apply
operation would need.  It never calls ``updateFromNode``, ``save``,
``copyToHDAFile``, ``matchCurrentDefinition``, ``installFile``, or
``hipFile.save``.
"""

from __future__ import annotations


HDA_UPDATE_SOURCE = r'''
import os as _hcm_hda_update_os


_HCM_HDA_UPDATE_LIBRARY_SUFFIXES = (".hda", ".hdalc", ".hdanc", ".otl")


def _hcm_hda_update_bool(value, name):
    if not isinstance(value, bool):
        raise TypeError(name + " must be a boolean")
    return value


def _hcm_hda_update_limit(value, name, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(name + " must be an integer")
    if value < 1 or value > maximum:
        raise ValueError(name + " must be between 1 and " + str(maximum))
    return value


def _hcm_hda_update_text(value, name, maximum, allow_none=True):
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value.strip():
        raise TypeError(name + " must be a non-empty string" + (" or null" if allow_none else ""))
    value = value.strip()
    if len(value) > maximum:
        raise ValueError(name + " exceeds " + str(maximum) + " characters")
    return value


def _hcm_hda_update_type_components(type_name):
    try:
        values = _hcm_hou.hda.componentsFromFullNodeTypeName(type_name)
        scope, namespace, name, version = values
    except BaseException:
        scope, namespace, name, version = "", "", type_name, ""
    return {
        "scope": str(scope),
        "namespace": str(namespace),
        "name": str(name),
        "version": str(version),
    }


def _hcm_hda_update_expand_path(value):
    expand = getattr(_hcm_hou, "expandString", None)
    if callable(expand):
        try:
            value = expand(value)
        except BaseException:
            pass
    value = _hcm_hda_update_os.path.expandvars(value)
    return _hcm_hda_update_os.path.abspath(_hcm_hda_update_os.path.normpath(value))


def _hcm_hda_update_library_path(value, current_library):
    requested = _hcm_hda_update_text(value, "library", 4096)
    candidate = current_library if requested is None else requested
    if not candidate or candidate == "Embedded":
        raise ValueError("library is required because this HDA definition is embedded")
    path = _hcm_hda_update_expand_path(candidate)
    suffix = _hcm_hda_update_os.path.splitext(path)[1].lower()
    if suffix not in _HCM_HDA_UPDATE_LIBRARY_SUFFIXES:
        raise ValueError(
            "library must use one of: " + ", ".join(_HCM_HDA_UPDATE_LIBRARY_SUFFIXES)
        )
    return requested, path


def _hcm_hda_update_path_state(path):
    exists = _hcm_hda_update_os.path.exists(path)
    parent = _hcm_hda_update_os.path.dirname(path)
    parent_exists = _hcm_hda_update_os.path.isdir(parent)
    file_writable = bool(_hcm_hda_update_os.access(path, _hcm_hda_update_os.W_OK)) if exists else None
    parent_writable = (
        bool(_hcm_hda_update_os.access(parent, _hcm_hda_update_os.W_OK))
        if parent_exists
        else None
    )
    return {
        "path": path,
        "exists": bool(exists),
        "parent": parent,
        "parent_exists": bool(parent_exists),
        "file_writable": file_writable,
        "parent_writable": parent_writable,
        "write_probe": "advisory_only_no_file_opened",
        "ready": bool(file_writable) if exists else bool(parent_exists and parent_writable),
    }


def _hcm_hda_update_destination_definitions(path, maximum):
    if not _hcm_hda_update_os.path.exists(path):
        return {
            "available": True,
            "count": 0,
            "count_complete": True,
            "types": [],
            "truncated": False,
            "error": None,
        }
    try:
        definitions = _hcm_hou.hda.definitionsInFile(path)
    except BaseException as exc:
        return {
            "available": False,
            "count": None,
            "count_complete": False,
            "types": [],
            "truncated": False,
            "error": _hcm_error_text(exc, 512),
        }
    types = []
    truncated = False
    for definition in definitions:
        if len(types) >= maximum:
            truncated = True
            break
        try:
            types.append(str(definition.nodeType().name()))
        except BaseException:
            types.append("<unavailable>")
    return {
        "available": True,
        "count": len(types) if not truncated else None,
        "count_complete": not truncated,
        "types": types,
        "truncated": truncated,
        "error": None,
    }


def _hcm_hda_update_sections(definition, maximum):
    try:
        names = sorted(str(name) for name in definition.sections().keys())
    except BaseException:
        names = []
    preserved = [name for name in names if name not in ("Contents.gz", "DialogScript")]
    return {
        "count": len(preserved),
        "names": preserved[:maximum],
        "truncated": len(preserved) > maximum,
        "limit": maximum,
        "excluded_from_restore": ["Contents.gz", "DialogScript"],
    }


def _hcm_hda_update_reference_audit(node, enabled, maximum):
    if not enabled:
        return {"enabled": False, "performed": False, "expectation": "not requested"}
    service_type = globals().get("_HCMHdaReferenceService")
    if service_type is None:
        return {
            "enabled": True,
            "performed": False,
            "expectation": "must complete before apply; reference auditor is unavailable",
        }
    try:
        audit = service_type().audit(
            node,
            descendants=True,
            max_nodes=maximum,
            max_parms=min(maximum * 10, 10000),
            max_results=maximum,
            max_errors=min(maximum, 1000),
        )
    except BaseException as exc:
        return {
            "enabled": True,
            "performed": False,
            "expectation": "must complete before apply",
            "error": _hcm_error_text(exc, 512),
        }
    return {
        "enabled": True,
        "performed": True,
        "expectation": "review external references before writing the definition",
        "external_reference_count": int(audit.get("count", 0)),
        "items": list(audit.get("items", []))[:maximum],
        "truncated": bool(audit.get("meta", {}).get("truncated", False)),
        "errors": list(audit.get("errors", []))[:maximum],
    }


class _HCMHdaUpdateService:
    """Bounded, no-effect planner for existing HDA update and copy operations."""

    def plan(
        self,
        node,
        mode="update",
        library=None,
        type_name=None,
        label=None,
        contents=True,
        interface=False,
        preserve_sections=True,
        preserve_tools=True,
        reference_audit=True,
        overwrite=False,
        match_current=False,
        create_backup=True,
        max_items=100,
    ):
        if mode not in ("update", "copy"):
            raise ValueError("mode must be 'update' or 'copy'")
        maximum = _hcm_hda_update_limit(max_items, "max_items", 1000)
        target_type = _hcm_hda_update_text(type_name, "type_name", 256)
        target_label = _hcm_hda_update_text(label, "label", 512)
        for value, name in (
            (contents, "contents"),
            (interface, "interface"),
            (preserve_sections, "preserve_sections"),
            (preserve_tools, "preserve_tools"),
            (reference_audit, "reference_audit"),
            (overwrite, "overwrite"),
            (match_current, "match_current"),
            (create_backup, "create_backup"),
        ):
            _hcm_hda_update_bool(value, name)
        if not contents and not interface and mode == "update":
            raise ValueError("update mode requires contents or interface")

        instance = _hcm_resolve_node(node, "node")
        definition = instance.type().definition()
        if definition is None:
            raise ValueError("Node is not an HDA instance: " + str(instance.path()))
        source_type = str(instance.type().name())
        current_library = str(definition.libraryFilePath())
        requested_library, destination_library = _hcm_hda_update_library_path(
            library, current_library
        )
        target_type = target_type or source_type
        if mode == "update" and target_type != source_type:
            type_issue = "update cannot rename an existing HDA definition; use copy mode"
        else:
            type_issue = None

        path_state = _hcm_hda_update_path_state(destination_library)
        destinations = _hcm_hda_update_destination_definitions(destination_library, maximum)
        destination_has_type = target_type in destinations["types"]
        source_is_editable = not bool(instance.isLockedHDA())
        needs_editable_instance = bool(contents)
        overwrite_required = bool(mode == "copy" and destination_has_type)
        sections = _hcm_hda_update_sections(definition, maximum)
        references = _hcm_hda_update_reference_audit(instance, reference_audit, maximum)

        blockers = []
        if not path_state["ready"]:
            blockers.append("destination library or its parent is not currently writable")
        if not destinations["available"]:
            blockers.append("destination library definitions could not be read")
        if type_issue:
            blockers.append(type_issue)
        if needs_editable_instance and not source_is_editable:
            blockers.append("contents update requires an unlocked HDA instance")
        if overwrite_required and not overwrite:
            blockers.append("copy target already contains the target type; set overwrite=True")
        if mode == "copy" and destinations["truncated"] and not destination_has_type:
            blockers.append("destination type scan reached max_items; target type conflict is unknown")

        future_effects = []
        order = 1
        if reference_audit:
            future_effects.append({
                "order": order,
                "kind": "audit_external_references",
                "method": "ctx.hda.references",
                "required_review": True,
                "mutates": False,
            })
            order += 1
        if contents and (preserve_sections or preserve_tools):
            future_effects.append({
                "order": order,
                "kind": "snapshot_preserved_sections",
                "method": "hou.HDADefinition.sections",
                "sections": sections["count"],
                "mutates": False,
            })
            order += 1
        if contents:
            future_effects.append({
                "order": order,
                "kind": "update_definition_contents",
                "method": "hou.HDADefinition.updateFromNode",
                "requires_unlocked_instance": True,
                "mutates_definition": True,
                "writes_current_library": True,
            })
            order += 1
        if interface:
            future_effects.append({
                "order": order,
                "kind": "update_parameter_interface",
                "method": "hou.HDADefinition.setParmTemplateGroup",
                "source": "instance.parmTemplateGroup()",
                "mutates_definition": True,
            })
            order += 1
        if contents and (preserve_sections or preserve_tools):
            future_effects.append({
                "order": order,
                "kind": "restore_preserved_sections",
                "method": "hou.HDADefinition.addSection",
                "preserve_sections": preserve_sections,
                "preserve_tools": preserve_tools,
                "mutates_definition": True,
            })
            order += 1
        future_effects.append({
            "order": order,
            "kind": "write_destination_library",
            "method": "hou.HDADefinition.copyToHDAFile" if mode == "copy" else "hou.HDADefinition.save",
            "destination": destination_library,
            "target_type": target_type,
            "overwrites_existing_type": overwrite_required,
            "create_backup": create_backup if mode == "update" else None,
            "mutates_disk": True,
        })
        order += 1
        if match_current and mode == "update":
            future_effects.append({
                "order": order,
                "kind": "match_current_definition",
                "method": "hou.OpNode.matchCurrentDefinition",
                "discard_unlocked_instance_changes": True,
                "mutates_instance": True,
            })

        return {
            "operation": "hda.update.plan",
            "dry_run": True,
            "mode": mode,
            "ok": not blockers,
            "blockers": blockers,
            "node": {
                "path": str(instance.path()),
                "type_name": source_type,
                "locked": bool(instance.isLockedHDA()),
                "matches_current_definition": bool(instance.matchesCurrentDefinition()),
            },
            "definition": {
                "current_library": current_library,
                "source_type": source_type,
                "source_components": _hcm_hda_update_type_components(source_type),
                "target_type": target_type,
                "target_components": _hcm_hda_update_type_components(target_type),
                "label_intent": target_label,
                "type_intent": "copy_as_new_type" if mode == "copy" and target_type != source_type else "retain_existing_type",
                "version_intent": _hcm_hda_update_type_components(target_type)["version"],
            },
            "destination": {
                "requested_library": requested_library,
                "path_state": path_state,
                "definitions": destinations,
                "target_type_exists": destination_has_type,
                "overwrite_required": overwrite_required,
                "overwrite_confirmed": overwrite,
            },
            "surfaces": {
                "contents": contents,
                "interface": interface,
                "preserve_sections": preserve_sections,
                "preserve_tools": preserve_tools,
                "retained_sections": sections,
            },
            "reference_audit": references,
            "apply_preconditions": [
                "re-check filesystem permissions and destination definitions immediately before apply",
                "review any external references and truncated audit results",
                "keep the instance unlocked while updating contents",
                "obtain an explicit overwrite decision when the destination type exists",
            ],
            "future_effects": future_effects,
            "rollback_limits": [
                "This plan does not create a backup or modify the HDA library.",
                "An applied definition update can affect all locked instances of the type.",
                "A library backup is only available when the eventual write requests it and Houdini can create it.",
                "Matching the current definition discards unlocked instance edits and cannot be undone by this planner.",
                "No HIP file save is planned; any later HIP save is a separate explicit effect.",
            ],
            "expected_effects": {
                "current_call": {
                    "mutates_instance": False,
                    "mutates_definition": False,
                    "writes_library": False,
                    "installs_library": False,
                    "saves_hip": False,
                },
                "apply": {
                    "definition_update": bool(contents or interface),
                    "library_write": True,
                    "hip_save": False,
                    "may_affect_locked_instances": bool(contents or interface),
                },
            },
            "limits": {"max_items": maximum},
        }
'''
