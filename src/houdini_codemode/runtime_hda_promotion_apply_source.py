"""Opt-in Houdini-side HDA parameter-promotion mutation source.

This source intentionally is not wired into the general HDA service yet.  It
is a narrow, explicitly-owned-library primitive.  Both interface mutation and
``updateFromNode`` write the HDA library in HOM.
"""

from __future__ import annotations


HDA_PROMOTION_APPLY_SOURCE = r'''
import hashlib as _hcm_hda_promotion_apply_hashlib
import os as _hcm_hda_promotion_apply_os


_HCM_HDA_PROMOTION_APPLY_MAX_COMPONENTS = 16


def _hcm_hda_promotion_apply_bool(value, name):
    if not isinstance(value, bool):
        raise TypeError(name + " must be a boolean")
    return value


def _hcm_hda_promotion_apply_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise TypeError(name + " must be a non-empty string")
    return value.strip()


def _hcm_hda_promotion_apply_path(value):
    return _hcm_hda_promotion_apply_os.path.normcase(
        _hcm_hda_promotion_apply_os.path.abspath(value)
    )


def _hcm_hda_promotion_apply_library_state(path):
    stat = _hcm_hda_promotion_apply_os.stat(path)
    digest = _hcm_hda_promotion_apply_hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return {
        "path": path,
        "size": int(stat.st_size),
        "mtime_ns": int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1000000000))),
        "sha256": digest.hexdigest(),
    }


def _hcm_hda_promotion_apply_is_hfs_library(path):
    expand = getattr(_hcm_hou, "expandString", None)
    hfs = ""
    if callable(expand):
        try:
            hfs = str(expand("$HFS"))
        except BaseException:
            hfs = ""
    if not hfs or hfs == "$HFS":
        hfs = _hcm_hda_promotion_apply_os.environ.get("HFS", "")
    if not hfs:
        return False
    try:
        return _hcm_hda_promotion_apply_os.path.commonpath(
            [_hcm_hda_promotion_apply_path(path), _hcm_hda_promotion_apply_path(hfs)]
        ) == _hcm_hda_promotion_apply_path(hfs)
    except ValueError:
        return False


def _hcm_hda_promotion_apply_require_isolated(instance):
    instances_method = getattr(instance.type(), "instances", None)
    if not callable(instances_method):
        raise ValueError("Cannot verify an isolated HDA definition: node type does not expose instances()")
    try:
        instances = list(instances_method())
    except BaseException as exc:
        raise ValueError("Cannot verify an isolated HDA definition: " + str(exc))
    instance_path = str(instance.path())
    paths = []
    for candidate in instances:
        try:
            paths.append(str(candidate.path()))
        except BaseException:
            raise ValueError("Cannot verify an isolated HDA definition: an instance has no path")
    if paths != [instance_path]:
        raise ValueError(
            "Promotion apply requires an isolated HDA definition; found {} instance(s)".format(len(paths))
        )
    return paths


def _hcm_hda_promotion_apply_component_tuple(parm, label):
    tuple_method = getattr(parm, "tuple", None)
    parm_tuple = tuple_method() if callable(tuple_method) else None
    if parm_tuple is None:
        raise ValueError(label + " has no parameter tuple")
    try:
        components = list(parm_tuple)
    except TypeError:
        components = []
    if not components:
        raise ValueError(label + " has no tuple components")
    if len(components) > _HCM_HDA_PROMOTION_APPLY_MAX_COMPONENTS:
        raise ValueError(label + " exceeds the {}-component promotion limit".format(_HCM_HDA_PROMOTION_APPLY_MAX_COMPONENTS))
    return components


def _hcm_hda_promotion_apply_clone(template, destination_name):
    clone_method = getattr(template, "clone", None)
    if not callable(clone_method):
        raise ValueError("Unsupported promotion template: clone() is unavailable")
    copied = clone_method()
    set_name = getattr(copied, "setName", None)
    if not callable(set_name):
        raise ValueError("Unsupported promotion template: setName() is unavailable")
    set_name(destination_name)
    return copied


def _hcm_hda_promotion_apply_snapshot(parm):
    snapshot = {"parm": parm, "keyframes": None, "expression": None, "language": None, "value": None}
    keyframes = getattr(parm, "keyframes", None)
    if callable(keyframes):
        try:
            snapshot["keyframes"] = list(keyframes())
        except BaseException:
            pass
    expression = getattr(parm, "expression", None)
    if callable(expression):
        try:
            snapshot["expression"] = expression()
            language = getattr(parm, "expressionLanguage", None)
            if callable(language):
                snapshot["language"] = language()
        except BaseException:
            pass
    evaluate = getattr(parm, "eval", None)
    if callable(evaluate):
        try:
            snapshot["value"] = evaluate()
        except BaseException:
            pass
    return snapshot


def _hcm_hda_promotion_apply_restore(snapshot):
    parm = snapshot["parm"]
    errors = []
    try:
        keyframes = snapshot["keyframes"]
        delete = getattr(parm, "deleteAllKeyframes", None)
        set_keyframes = getattr(parm, "setKeyframes", None)
        if keyframes is not None and callable(delete) and callable(set_keyframes):
            delete()
            if keyframes:
                set_keyframes(tuple(keyframes))
            elif snapshot["value"] is not None:
                setter = getattr(parm, "set", None)
                if not callable(setter):
                    raise ValueError("set() is unavailable")
                setter(snapshot["value"])
        elif snapshot["expression"] is not None:
            parm.setExpression(snapshot["expression"], snapshot["language"])
        elif snapshot["value"] is not None:
            setter = getattr(parm, "set", None)
            if not callable(setter):
                raise ValueError("set() is unavailable")
            setter(snapshot["value"])
    except BaseException as exc:
        errors.append(str(exc))
    return errors


class _HCMHdaPromotionApplyService:
    """Apply a conflict-free promotion only to one, explicitly owned HDA library."""

    def __init__(self, mutation_events=None):
        self._mutation_events = mutation_events if mutation_events is not None else []

    def apply(
        self,
        node,
        internal_parms,
        destination_names,
        folder=None,
        max_items=25,
        allow_library_write=False,
        owned_library=None,
        create_backup=True,
    ):
        _hcm_hda_promotion_apply_bool(allow_library_write, "allow_library_write")
        _hcm_hda_promotion_apply_bool(create_backup, "create_backup")
        if destination_names is None:
            raise ValueError("destination_names must be explicit for promotion apply")
        if not allow_library_write:
            raise ValueError("Promotion apply writes the HDA library; set allow_library_write=True after reviewing the plan")
        owned_library = _hcm_hda_promotion_apply_text(owned_library, "owned_library")

        instance = _hcm_resolve_node(node, "node")
        definition = instance.type().definition()
        if definition is None:
            raise ValueError("Node is not an HDA instance: " + str(instance.path()))
        if bool(instance.isLockedHDA()):
            raise ValueError("Promotion apply requires an unlocked HDA instance")
        library = str(definition.libraryFilePath())
        if library == "Embedded":
            raise ValueError("Promotion apply does not support embedded HDA definitions")
        if _hcm_hda_promotion_apply_path(library) != _hcm_hda_promotion_apply_path(owned_library):
            raise ValueError("owned_library must exactly match the HDA definition library")
        if _hcm_hda_promotion_apply_is_hfs_library(library):
            raise ValueError("Promotion apply refuses HFS/SideFX-installed HDA libraries")
        if not _hcm_hda_promotion_apply_os.path.isfile(library):
            raise ValueError("owned_library must be an existing regular HDA library file")
        isolated_paths = _hcm_hda_promotion_apply_require_isolated(instance)

        plan = _HCMHdaPromotionService().plan(
            instance, internal_parms, destination_names=destination_names,
            folder=folder, max_items=max_items,
        )
        if not plan.get("ok"):
            raise ValueError("Promotion preflight has destination conflicts: " + str(plan.get("conflicts", [])))
        before_library = _hcm_hda_promotion_apply_library_state(library)
        events = [{"kind": "preflight", "plan_ok": True, "items": len(plan["items"]), "isolated_instance_paths": isolated_paths}]
        # matchCurrentDefinition discards unlocked contents.  First commit the
        # caller's current isolated edits, then it is safe to synchronize the
        # newly-added interface onto this instance later in the operation.
        checkpoint_event = {
            "kind": "definition.updateFromNode_checkpoint",
            "library_write": "implicit_by_HOM",
            "source_instance": str(instance.path()),
            "status": "started",
        }
        events.append(checkpoint_event)
        try:
            definition.updateFromNode(instance)
            checkpoint_event["status"] = "complete"
        except BaseException as exc:
            checkpoint_event["status"] = "error"
            self._mutation_events.extend(events)
            raise RuntimeError(
                "Promotion checkpoint failed; no interface promotion was attempted: " + str(exc)
            )
        plan = _HCMHdaPromotionService().plan(
            instance, internal_parms, destination_names=destination_names,
            folder=folder, max_items=max_items,
        )
        if not plan.get("ok"):
            events.append({"kind": "preflight_recheck", "plan_ok": False, "conflicts": plan.get("conflicts", [])})
            self._mutation_events.extend(events)
            raise ValueError("Promotion preflight changed after the content checkpoint: " + str(plan.get("conflicts", [])))
        events.append({"kind": "preflight_recheck", "plan_ok": True, "items": len(plan["items"])})
        original_group = definition.parmTemplateGroup()
        group = definition.parmTemplateGroup()
        prepared = []
        for item in plan["items"]:
            source = instance.parm(item["requested_path"])
            if source is None:
                raise ValueError("Internal parameter disappeared after preflight: " + item["requested_path"])
            source_components = _hcm_hda_promotion_apply_component_tuple(source, "Internal parameter " + item["requested_path"])
            template = source.parmTemplate()
            copied = _hcm_hda_promotion_apply_clone(template, item["destination"]["parm_tuple_name"])
            component_count = getattr(copied, "numComponents", None)
            if not callable(component_count) or int(component_count()) != len(source_components):
                raise ValueError("Template component count does not match internal tuple for " + item["requested_path"])
            prepared.append((item, copied))

        for item, copied in prepared:
            if folder is None:
                group.append(copied)
            else:
                target_folder = group.findFolder(folder)
                if target_folder is None:
                    raise ValueError("Destination folder disappeared before interface update: " + str(folder))
                group.appendToFolder(target_folder, copied)

        snapshots = []
        interface_changed = False
        try:
            definition.setParmTemplateGroup(
                group, rename_conflicting_parms=False, create_backup=create_backup
            )
            interface_changed = True
            events.append({
                "kind": "definition.setParmTemplateGroup",
                "library_write": "implicit_by_HOM",
                "create_backup": create_backup,
                "items": len(prepared),
            })
            # An unlocked instance does not automatically adopt a definition's
            # new interface.  Synchronize it, then immediately unlock it again
            # before touching its internal channels.  This is limited to the
            # sole verified instance of the definition.
            instance.matchCurrentDefinition()
            events.append({"kind": "node.matchCurrentDefinition", "node_path": str(instance.path())})
            if not bool(instance.isLockedHDA()):
                raise ValueError("HDA instance did not lock while synchronizing its new interface")
            instance.allowEditingOfContents()
            events.append({"kind": "node.allowEditingOfContents", "node_path": str(instance.path())})
            if bool(instance.isLockedHDA()):
                raise ValueError("HDA instance could not be unlocked after interface synchronization")
            links = []
            for item, _copied in prepared:
                source = instance.parm(item["requested_path"])
                if source is None:
                    raise ValueError("Internal parameter disappeared after interface synchronization: " + item["requested_path"])
                source_components = _hcm_hda_promotion_apply_component_tuple(
                    source, "Internal parameter " + item["requested_path"]
                )
                destination_tuple = instance.parmTuple(item["destination"]["parm_tuple_name"])
                if destination_tuple is None:
                    raise ValueError("Promoted parameter tuple was not created: " + item["destination"]["parm_tuple_name"])
                destination_components = list(destination_tuple)
                if len(destination_components) != len(source_components):
                    raise ValueError("Promoted tuple component count does not match internal tuple for " + item["requested_path"])
                links.append((item, source_components, destination_components))
            for item, source_components, destination_components in links:
                for source, destination in zip(source_components, destination_components):
                    snapshots.append(_hcm_hda_promotion_apply_snapshot(source))
                    expression = source.referenceExpression(destination, language=_hcm_hou.exprLanguage.Hscript)
                    source.setExpression(expression, language=_hcm_hou.exprLanguage.Hscript)
                events.append({
                    "kind": "internal.setExpression_reference",
                    "source": item["source"]["parm_path"],
                    "destination": item["destination"]["parm_path"],
                    "components": len(source_components),
                    "language": "Hscript",
                })
            # The interface must exist before references can target it.  Saving the
            # unlocked instance afterwards is the HOM operation that durably puts
            # those internal channel changes into this isolated definition.
            contents_event = {
                "kind": "definition.updateFromNode",
                "library_write": "implicit_by_HOM",
                "source_instance": str(instance.path()),
                "status": "started",
            }
            events.append(contents_event)
            definition.updateFromNode(instance)
            contents_event["status"] = "complete"
        except BaseException as exc:
            if events and events[-1].get("kind") == "definition.updateFromNode" and events[-1].get("status") == "started":
                events[-1]["status"] = "error"
            rollback = {"attempted": True, "channel_errors": [], "definition_error": None}
            for snapshot in reversed(snapshots):
                rollback["channel_errors"].extend(_hcm_hda_promotion_apply_restore(snapshot))
            if interface_changed:
                try:
                    definition.setParmTemplateGroup(
                        original_group, rename_conflicting_parms=False, create_backup=create_backup
                    )
                except BaseException as rollback_exc:
                    rollback["definition_error"] = str(rollback_exc)
            events.append({
                "kind": "rollback",
                "library_write": "implicit_by_HOM" if interface_changed else False,
                "ok": not rollback["channel_errors"] and rollback["definition_error"] is None,
                "definition_contents_rollback": "unsupported if updateFromNode was entered",
            })
            self._mutation_events.extend(events)
            raise RuntimeError(
                "Promotion apply failed; rollback attempted. Definition contents cannot be restored if updateFromNode was entered: "
                + str(exc)
            )

        after_library = _hcm_hda_promotion_apply_library_state(library)
        self._mutation_events.extend(events)
        return {
            "operation": "hda.parms.promote.apply",
            "ok": True,
            "node_path": str(instance.path()),
            "library": {
                "before": before_library,
                "after": after_library,
                "set_parm_template_group_called": True,
                "match_current_definition_called": True,
                "allow_editing_of_contents_called": True,
                "update_from_node_called": True,
                "update_from_node_calls": 2,
                "hda_definition_save_called": False,
                "install_called": False,
                "hip_save_called": False,
            },
            "persistence": {
                "definition_interface": "written implicitly by setParmTemplateGroup and synchronized onto the sole instance before updateFromNode",
                "content_checkpoint": "current unlocked contents saved before matchCurrentDefinition",
                "internal_channel_references": "saved into the isolated HDA definition by the final updateFromNode",
                "update_from_node_called": True,
                "update_from_node_calls": 2,
            },
            "events": events,
            "items": [
                {"source": item["source"]["parm_path"], "destination": item["destination"]["parm_path"], "components": item["template_copy"]["components"]}
                for item in plan["items"]
            ],
            "rollback_limits": "Rollback is best-effort. It restores instance channels and the original interface with another implicit HDA library write, but cannot undo the initial content checkpoint or restore definition contents after the final updateFromNode has been entered.",
        }
'''
