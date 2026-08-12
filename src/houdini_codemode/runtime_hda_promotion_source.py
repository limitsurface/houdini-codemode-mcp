"""Read-only Houdini-side HDA parameter-promotion planning source.

This is deliberately separate from ``runtime_hda_source``.  It describes the
definition and channel changes an eventual promotion command would make, but
does not clone templates, set expressions, update a definition, or save an HDA
library.
"""

from __future__ import annotations


HDA_PROMOTION_SOURCE = r'''
_HCM_HDA_PROMOTION_SUPPORTED_TYPES = (
    "Float", "Int", "Toggle", "Menu", "String",
)


def _hcm_hda_promotion_limit(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("max_items must be an integer")
    if value < 1 or value > 100:
        raise ValueError("max_items must be between 1 and 100")
    return value


def _hcm_hda_promotion_paths(value, maximum):
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = list(value)
    else:
        raise TypeError("internal_parms must be a non-empty string, list, or tuple")
    if not values:
        raise ValueError("internal_parms must not be empty")
    if len(values) > maximum:
        raise ValueError("internal_parms exceeds max_items")
    for index, path in enumerate(values):
        if not isinstance(path, str) or not path.strip():
            raise TypeError(
                "internal_parms[{}] must be a non-empty string".format(index)
            )
    return [path.strip() for path in values]


def _hcm_hda_promotion_valid_name(value):
    if not isinstance(value, str) or not value or len(value) > 128:
        return False
    first = value[0]
    if not (first == "_" or "A" <= first <= "Z" or "a" <= first <= "z"):
        return False
    for char in value[1:]:
        if not (
            char == "_"
            or "A" <= char <= "Z"
            or "a" <= char <= "z"
            or "0" <= char <= "9"
        ):
            return False
    return True


def _hcm_hda_promotion_names(value, paths):
    count = len(paths)
    if value is None:
        return None
    if isinstance(value, str):
        if count != 1:
            raise TypeError("destination_names must be a list or tuple for multiple parms")
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = list(value)
    else:
        raise TypeError("destination_names must be a string, list, tuple, or None")
    if len(values) != count:
        raise ValueError("destination_names must have one item per internal parameter")
    for index, name in enumerate(values):
        if not _hcm_hda_promotion_valid_name(name):
            raise ValueError(
                "destination_names[{}] must be an ASCII Houdini parameter name".format(
                    index
                )
            )
    return values


def _hcm_hda_promotion_type(template):
    try:
        value = template.type()
        return str(value.name() if callable(getattr(value, "name", None)) else value)
    except BaseException:
        return "Unknown"


def _hcm_hda_promotion_tuple(parm):
    tuple_method = getattr(parm, "tuple", None)
    parm_tuple = tuple_method() if callable(tuple_method) else None
    if parm_tuple is None:
        raise ValueError("Parameter cannot be promoted because it has no parameter tuple")
    try:
        components = list(parm_tuple)
    except TypeError:
        components = []
    if not components:
        components = [parm]
    try:
        tuple_name = str(parm_tuple.name())
    except BaseException:
        tuple_name = str(parm.name())
    return parm_tuple, tuple_name, components


def _hcm_hda_promotion_is_internal(instance, parm):
    owner_method = getattr(parm, "node", None)
    owner = owner_method() if callable(owner_method) else None
    if owner is None:
        return False
    instance_path = str(instance.path()).rstrip("/")
    try:
        owner_path = str(owner.path()).rstrip("/")
    except BaseException:
        return False
    return owner_path.startswith(instance_path + "/")


def _hcm_hda_promotion_find_folder(group, folder):
    if folder is None:
        return None
    if not isinstance(folder, str) or not folder:
        raise TypeError("folder must be a non-empty string or None")
    finder = getattr(group, "findFolder", None)
    target = finder(folder) if callable(finder) else group.find(folder)
    if target is None:
        raise ValueError("Destination folder not found in HDA definition: " + folder)
    template_type = _hcm_hda_promotion_type(target)
    if template_type != "Folder":
        raise ValueError("Destination is not a folder: " + folder)
    return {
        "name": str(target.name()),
        "label": str(target.label()),
        "type": template_type,
        "action": "append_to_existing_folder",
    }


def _hcm_hda_promotion_existing(group, instance, name):
    definition_template = group.find(name)
    instance_parm = instance.parm(name)
    conflicts = []
    if definition_template is not None:
        conflicts.append("definition_template")
    if instance_parm is not None:
        conflicts.append("instance_parameter")
    return conflicts


def _hcm_hda_promotion_expression_state(parm):
    has_expression = False
    method = getattr(parm, "expression", None)
    if callable(method):
        try:
            method()
            has_expression = True
        except BaseException:
            pass
    keyframe_count = None
    keyframes = getattr(parm, "keyframes", None)
    if callable(keyframes):
        try:
            keyframe_count = len(keyframes())
        except BaseException:
            pass
    return {
        "has_expression": has_expression,
        "keyframe_count": keyframe_count,
        "will_be_replaced": True,
    }


def _hcm_hda_promotion_source_item(instance, requested_path, destination_name):
    parm = instance.parm(requested_path)
    if parm is None:
        raise ValueError("Internal parameter not found: " + requested_path)
    if not _hcm_hda_promotion_is_internal(instance, parm):
        raise ValueError(
            "Promotion target must belong to a node inside the HDA: " + requested_path
        )
    template = parm.parmTemplate()
    template_type = _hcm_hda_promotion_type(template)
    if template_type not in _HCM_HDA_PROMOTION_SUPPORTED_TYPES:
        raise ValueError(
            "Unsupported promotion template type {} for {}".format(
                template_type, requested_path
            )
        )
    _parm_tuple, tuple_name, components = _hcm_hda_promotion_tuple(parm)
    if destination_name is None:
        destination_name = str(template.name())
    if not _hcm_hda_promotion_valid_name(destination_name):
        raise ValueError(
            "Destination name is not an ASCII Houdini parameter name: "
            + destination_name
        )
    component_paths = []
    for component in components:
        try:
            component_paths.append(str(component.path()))
        except BaseException:
            component_paths.append(str(component.name()))
    return {
        "requested_path": requested_path,
        "source": {
            "parm_path": str(parm.path()),
            "node_path": str(parm.node().path()),
            "tuple_name": tuple_name,
            "component_paths": component_paths,
        },
        "template_copy": {
            "source_name": str(template.name()),
            "source_label": str(template.label()),
            "type": template_type,
            "components": len(components),
            "operation": "clone_then_set_name",
            "destination_name": destination_name,
        },
        "destination": {
            "parm_tuple_name": destination_name,
            "parm_path": str(instance.path()).rstrip("/") + "/" + destination_name,
        },
        "source_channel_state": _hcm_hda_promotion_expression_state(parm),
        "channel_link": {
            "direction": "internal_references_promoted_parameter",
            "language": "Hscript",
            "components": len(components),
            "operation": (
                "after matching the updated definition, zip source.parm.tuple() "
                "with instance.parmTuple(destination_name), build each source "
                "reference with source.referenceExpression(destination, "
                "language=hou.exprLanguage.Hscript), then call source.setExpression"
            ),
        },
    }


class _HCMHdaPromotionService:
    """Read-only planner for promoting existing internal HDA parameters."""

    def plan(
        self,
        node,
        internal_parms,
        destination_names=None,
        folder=None,
        max_items=25,
    ):
        maximum = _hcm_hda_promotion_limit(max_items)
        paths = _hcm_hda_promotion_paths(internal_parms, maximum)
        names = _hcm_hda_promotion_names(destination_names, paths)
        instance = _hcm_resolve_node(node, "node")
        definition = instance.type().definition()
        if definition is None:
            raise ValueError("Node is not an HDA instance: " + instance.path())
        group = definition.parmTemplateGroup()
        destination_folder = _hcm_hda_promotion_find_folder(group, folder)

        items = []
        source_tuples = set()
        destination_counts = {}
        for index, requested_path in enumerate(paths):
            requested_name = names[index] if names is not None else None
            item = _hcm_hda_promotion_source_item(
                instance, requested_path, requested_name
            )
            source_tuple = item["source"]["node_path"] + ":" + item["source"]["tuple_name"]
            if source_tuple in source_tuples:
                raise ValueError(
                    "The same internal parameter tuple was requested more than once: "
                    + requested_path
                )
            source_tuples.add(source_tuple)
            destination = item["destination"]["parm_tuple_name"]
            destination_counts[destination] = destination_counts.get(destination, 0) + 1
            items.append(item)
        duplicate_destinations = {
            name for name, count in destination_counts.items() if count > 1
        }
        if duplicate_destinations:
            raise ValueError(
                "Multiple promotion targets use destination name(s): "
                + ", ".join(sorted(duplicate_destinations))
            )
        conflicts = []
        for item in items:
            destination = item["destination"]["parm_tuple_name"]
            existing = _hcm_hda_promotion_existing(group, instance, destination)
            item["destination"]["conflicts"] = existing
            item["destination"]["available"] = not existing
            if existing:
                conflicts.append(
                    {"destination_name": destination, "conflicts": existing}
                )
        return {
            "operation": "hda.parms.promote.plan",
            "dry_run": True,
            "node": {
                "path": str(instance.path()),
                "type_name": str(instance.type().name()),
                "locked": bool(instance.isLockedHDA()),
            },
            "definition": {
                "library": str(definition.libraryFilePath()),
                "interface_edit": "append template copy"
                if destination_folder is None
                else "append template copy to existing folder",
                "content_edit": "replace internal component channels with references",
                "affects_all_instances_after_definition_update": True,
            },
            "destination_folder": destination_folder,
            "items": items,
            "conflicts": conflicts,
            "ok": not conflicts,
            "apply_preconditions": [
                "all destination names must remain available",
                "the HDA definition and library must be writable",
                "the definition must be updated from the linked instance after channel changes",
            ],
            "expected_effects": {
                "instance": {
                    "interface_refresh": True,
                    "internal_channel_expressions_replaced": len(items),
                },
                "definition": {
                    "parameter_interface_changed": True,
                    "network_contents_changed": True,
                    "all_instances_affected_after_update": True,
                },
                "library": {
                    "writes_required_on_apply": True,
                    "backup_may_be_created_by_setParmTemplateGroup": True,
                },
                "current_call": {
                    "mutates_instance": False,
                    "mutates_definition": False,
                    "writes_library": False,
                    "saves_hip": False,
                },
            },
            "limits": {"max_items": maximum, "requested": len(paths)},
        }
'''
