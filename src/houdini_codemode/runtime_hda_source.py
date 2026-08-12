"""Houdini-side bounded HDA definition and library inspection source."""

from __future__ import annotations


HDA_SOURCE = r'''
def _hcm_hda_components(type_name):
    try:
        scope, namespace, name, version = _hcm_hou.hda.componentsFromFullNodeTypeName(
            type_name
        )
    except BaseException:
        scope, namespace, name, version = "", "", type_name, ""
    return {
        "scope": str(scope),
        "namespace": str(namespace),
        "name": str(name),
        "version": str(version),
    }


def _hcm_hda_sections(definition, maximum):
    rows = []
    try:
        items = list(definition.sections().items())
    except BaseException:
        items = []
    for name, section in items[:maximum]:
        try:
            size = int(section.size())
        except BaseException:
            size = None
        rows.append({"name": str(name), "size": size})
    return {
        "count": len(items),
        "items": rows,
        "truncated": len(items) > len(rows),
        "limit": maximum,
    }


def _hcm_hda_definition(definition, include_sections, section_limit):
    node_type = definition.nodeType()
    type_name = str(node_type.name())
    result = {
        "type_name": type_name,
        "components": _hcm_hda_components(type_name),
        "label": str(definition.description()),
        "category": str(node_type.category().name()),
        "library": str(definition.libraryFilePath()),
        "version": str(definition.version()),
        "icon": str(definition.icon()),
        "min_inputs": int(definition.minNumInputs()),
        "max_inputs": int(definition.maxNumInputs()),
        "preferred": bool(definition.isPreferred()),
        "current": bool(definition.isCurrent()),
    }
    if include_sections:
        result["sections"] = _hcm_hda_sections(definition, section_limit)
    return result


def _hcm_hda_matches(row, category, namespace, name, type_name):
    if category and row["category"].lower() != category.lower():
        return False
    if namespace and row["components"]["namespace"] != namespace:
        return False
    if name and name.lower() not in row["components"]["name"].lower():
        return False
    if type_name and type_name.lower() not in row["type_name"].lower():
        return False
    return True


def _hcm_hda_text_filter(value, label):
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise TypeError(label + " must be a non-empty string or null")
    return value


def _hcm_hda_parm_tree(definition, maximum, max_depth):
    state = {"visited": 0, "truncated": False}

    def walk(entries, depth):
        rows = []
        if depth > max_depth:
            state["truncated"] = True
            return rows
        for template in entries:
            if state["visited"] >= maximum:
                state["truncated"] = True
                break
            state["visited"] += 1
            row = {
                "name": str(template.name()),
                "label": str(template.label()),
                "type": str(template.type().name()),
            }
            method = getattr(template, "parmTemplates", None)
            if callable(method):
                children = walk(method(), depth + 1)
                if children:
                    row["children"] = children
            rows.append(row)
        return rows

    rows = walk(definition.parmTemplateGroup().entries(), 0)
    return {
        "count": state["visited"],
        "items": rows,
        "truncated": state["truncated"],
        "limit": maximum,
        "max_depth": max_depth,
    }


def _hcm_hda_messages(node):
    result = {}
    for name in ("errors", "warnings", "messages"):
        method = getattr(node, name, None)
        try:
            result[name] = [str(value) for value in method()] if callable(method) else []
        except BaseException:
            result[name] = []
    return result


def _hcm_hda_connector_count(node, output):
    names = (
        ("outputNames", "outputConnectors", "outputs")
        if output
        else ("inputNames", "inputConnectors", "inputs")
    )
    for name in names:
        method = getattr(node, name, None)
        if not callable(method):
            continue
        try:
            return len(method())
        except BaseException:
            continue
    return 0


def _hcm_hda_temporary_name(parent):
    base = "__houdini_codemode_hda_validate"
    name = base
    suffix = 1
    while parent.node(name) is not None:
        name = base + str(suffix)
        suffix += 1
    return name


def _hcm_hda_cop_outputs(node, maximum):
    if str(node.type().category().name()) != "Cop":
        return None
    output_nodes = [
        child for child in node.children() if str(child.type().name()) == "output"
    ]
    canonical = next(
        (child for child in output_nodes if str(child.name()) == "outputs"), None
    )
    extras = [child for child in output_nodes if child is not canonical]
    warnings = []
    if canonical is None:
        warnings.append(
            "Copernicus HDA is missing the canonical Output COP named 'outputs'"
        )
    if extras:
        warnings.append(
            "Copernicus HDA contains additional Output COPs that are not exported"
        )
    items = [str(child.path()) for child in output_nodes]
    extra_paths = [str(child.path()) for child in extras]
    return {
        "canonical": str(canonical.path()) if canonical is not None else None,
        "count": len(items),
        "items": items[:maximum],
        "items_truncated": len(items) > maximum,
        "extra_count": len(extra_paths),
        "extras": extra_paths[:maximum],
        "extras_truncated": len(extra_paths) > maximum,
        "warnings": warnings,
        "ok": not warnings,
    }


def _hcm_hda_conditionals(group, name):
    template = group.find(name)
    if template is None or not callable(getattr(template, "conditionals", None)):
        return {}
    result = {}
    for key, value in template.conditionals().items():
        try:
            key_name = str(key.name())
        except BaseException:
            key_name = str(key)
        result[key_name] = str(value)
    return result


def _hcm_hda_conditional_audit(node, definition, maximum):
    definition_group = definition.parmTemplateGroup()
    instance_group = node.parmTemplateGroup()
    rows = []
    seen = set()
    total = 0
    for parm in node.parms():
        try:
            name = str(parm.tuple().name())
        except BaseException:
            name = str(parm.name())
        if name in seen:
            continue
        seen.add(name)
        definition_rules = _hcm_hda_conditionals(definition_group, name)
        instance_rules = _hcm_hda_conditionals(instance_group, name)
        if not definition_rules and not instance_rules:
            continue
        total += 1
        if len(rows) < maximum:
            rows.append(
                {
                    "parm": name,
                    "definition": definition_rules,
                    "instance": instance_rules,
                    "matches": definition_rules == instance_rules,
                }
            )
    mismatch_count = sum(1 for row in rows if not row["matches"])
    return {
        "count": total,
        "items": rows,
        "returned": len(rows),
        "truncated": total > len(rows),
        "limit": maximum,
        "mismatch_count": mismatch_count,
        "mismatch_count_complete": total == len(rows),
        "ok": mismatch_count == 0 and total == len(rows),
    }


def _hcm_hda_frames(frames, cook):
    if frames is None:
        return [float(_hcm_hou.frame())] if cook else []
    if not isinstance(frames, (list, tuple)):
        raise TypeError("frames must be a list, tuple, or null")
    if len(frames) > 100:
        raise ValueError("frames exceeds the 100-frame validation limit")
    result = []
    for index, value in enumerate(frames):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("frames[{}] must be a number".format(index))
        value = float(value)
        if not _hcm_math.isfinite(value):
            raise ValueError("frames must contain only finite values")
        result.append(value)
    return result


def _hcm_hda_validation_plan(node, fresh, cook, frames, external_references):
    return {
        "operation": "hda.validate",
        "node_path": node.path(),
        "type_name": str(node.type().name()),
        "dry_run": True,
        "steps": [
            {"kind": "inspect_definition_state", "enabled": True, "mutates": False},
            {
                "kind": "create_fresh_instance",
                "enabled": fresh,
                "temporary": True,
                "mutates_scene": fresh,
            },
            {
                "kind": "cook_frames",
                "enabled": bool(frames),
                "frames": frames,
                "may_have_non_undoable_effects": bool(frames),
            },
            {"kind": "audit_interface", "enabled": True, "mutates": False},
            {
                "kind": "audit_external_references",
                "enabled": external_references,
                "mutates": False,
            },
            {
                "kind": "restore_frame_and_remove_temporary",
                "enabled": bool(frames) or fresh,
                "best_effort_cleanup": True,
            },
        ],
        "effects": {
            "temporary_node": fresh,
            "temporary_frame_changes": bool(frames),
            "cooks": len(frames),
            "library_writes": False,
            "hip_save": False,
        },
    }


class _HCMHdaService:
    def __init__(self, mutation_events=None):
        self._mutation_events = mutation_events if mutation_events is not None else []

    def inspect(
        self,
        node,
        parms=False,
        sections=False,
        tools=False,
        max_items=100,
        max_depth=12,
    ):
        for value, label in ((parms, "parms"), (sections, "sections"), (tools, "tools")):
            if not isinstance(value, bool):
                raise TypeError(label + " must be a boolean")
        maximum = _hcm_geometry_positive(max_items, "max_items", 10000)
        depth = _hcm_geometry_positive(max_depth, "max_depth", 64)
        resolved = _hcm_resolve_node(node)
        definition = resolved.type().definition()
        if definition is None:
            raise ValueError("Node is not an HDA instance: " + resolved.path())
        result = {
            "node": _hcm_node_summary(resolved),
            "definition": _hcm_hda_definition(definition, sections, maximum),
            "locked": bool(resolved.isLockedHDA()),
            "matches": bool(resolved.matchesCurrentDefinition()),
        }
        if parms:
            result["parms"] = _hcm_hda_parm_tree(definition, maximum, depth)
        if tools:
            try:
                names = sorted(str(name) for name in definition.tools().keys())
            except BaseException:
                names = []
            result["tools"] = {
                "count": len(names),
                "items": names[:maximum],
                "truncated": len(names) > maximum,
                "limit": maximum,
            }
        compress_method = getattr(resolved, "isGenericFlagSet", None)
        node_flag = getattr(_hcm_hou, "nodeFlag", None)
        if callable(compress_method) and node_flag is not None:
            try:
                result["compress"] = bool(compress_method(node_flag.Compress))
            except BaseException:
                pass
        return result

    def definitions(
        self,
        library=None,
        category=None,
        namespace=None,
        name=None,
        type_name=None,
        include_sections=False,
        max_items=50,
        max_scan=10000,
        section_limit=100,
    ):
        library = _hcm_hda_text_filter(library, "library")
        category = _hcm_hda_text_filter(category, "category")
        namespace = _hcm_hda_text_filter(namespace, "namespace")
        name = _hcm_hda_text_filter(name, "name")
        type_name = _hcm_hda_text_filter(type_name, "type_name")
        if not isinstance(include_sections, bool):
            raise TypeError("include_sections must be a boolean")
        maximum = _hcm_geometry_positive(max_items, "max_items", 10000)
        scan_limit = _hcm_geometry_positive(max_scan, "max_scan", 1000000)
        sections_maximum = _hcm_geometry_positive(
            section_limit, "section_limit", 10000
        )
        paths = [library] if library else [str(path) for path in _hcm_hou.hda.loadedFiles()]
        rows = []
        errors = []
        scanned = 0
        matches = 0
        scan_truncated = False
        for path in paths:
            try:
                definitions = _hcm_hou.hda.definitionsInFile(path)
            except BaseException as exc:
                if len(errors) < 20:
                    errors.append({"library": str(path), "error": _hcm_error_text(exc, 512)})
                continue
            for definition in definitions:
                if scanned >= scan_limit:
                    scan_truncated = True
                    break
                scanned += 1
                row = _hcm_hda_definition(
                    definition, include_sections, sections_maximum
                )
                if not _hcm_hda_matches(
                    row, category, namespace, name, type_name
                ):
                    continue
                matches += 1
                if len(rows) < maximum:
                    rows.append(row)
            if scan_truncated:
                break
        return {
            "count": len(rows),
            "definitions": rows,
            "errors": errors,
            "meta": {
                "total_matches": matches,
                "returned": len(rows),
                "limit": maximum,
                "truncated": matches > len(rows) or scan_truncated,
                "scanned_definitions": scanned,
                "max_scan": scan_limit,
                "scan_truncated": scan_truncated,
                "library_count": len(paths),
            },
        }

    def libraries(
        self,
        library=None,
        definition=None,
        max_items=50,
        max_types=100,
        max_scan=10000,
    ):
        library = _hcm_hda_text_filter(library, "library")
        definition = _hcm_hda_text_filter(definition, "definition")
        maximum = _hcm_geometry_positive(max_items, "max_items", 10000)
        type_limit = _hcm_geometry_positive(max_types, "max_types", 10000)
        scan_limit = _hcm_geometry_positive(max_scan, "max_scan", 1000000)
        paths = [str(path) for path in _hcm_hou.hda.loadedFiles()]
        rows = []
        matches = 0
        scanned = 0
        scan_truncated = False
        for path in paths:
            if library and library.lower() not in path.lower():
                continue
            try:
                definitions = list(_hcm_hou.hda.definitionsInFile(path))
            except BaseException:
                definitions = []
            type_names = []
            total_definitions = len(definitions)
            for item in definitions:
                if scanned >= scan_limit:
                    scan_truncated = True
                    break
                scanned += 1
                type_names.append(str(item.nodeType().name()))
            if definition and not any(
                definition.lower() in type_name.lower() for type_name in type_names
            ):
                if scan_truncated:
                    break
                continue
            matches += 1
            if len(rows) < maximum:
                rows.append(
                    {
                        "path": path,
                        "definition_count": total_definitions,
                        "types": type_names[:type_limit],
                        "types_truncated": total_definitions > type_limit
                        or len(type_names) < total_definitions,
                        "type_limit": type_limit,
                    }
                )
            if scan_truncated:
                break
        return {
            "count": len(rows),
            "libraries": rows,
            "meta": {
                "total_matches": matches,
                "returned": len(rows),
                "limit": maximum,
                "truncated": matches > len(rows) or scan_truncated,
                "scanned_definitions": scanned,
                "max_scan": scan_limit,
                "scan_truncated": scan_truncated,
            },
        }

    def references(
        self,
        node,
        descendants=True,
        max_nodes=1000,
        max_parms=10000,
        max_results=1000,
        max_errors=100,
    ):
        return _HCMHdaReferenceService().audit(
            node,
            descendants=descendants,
            max_nodes=max_nodes,
            max_parms=max_parms,
            max_results=max_results,
            max_errors=max_errors,
        )

    def plan_promotion(
        self,
        node,
        internal_parms,
        destination_names=None,
        folder=None,
        max_items=25,
    ):
        return _HCMHdaPromotionService().plan(
            node,
            internal_parms,
            destination_names=destination_names,
            folder=folder,
            max_items=max_items,
        )

    def plan_update(
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
        return _HCMHdaUpdateService().plan(
            node,
            mode=mode,
            library=library,
            type_name=type_name,
            label=label,
            contents=contents,
            interface=interface,
            preserve_sections=preserve_sections,
            preserve_tools=preserve_tools,
            reference_audit=reference_audit,
            overwrite=overwrite,
            match_current=match_current,
            create_backup=create_backup,
            max_items=max_items,
        )

    def validate(
        self,
        node,
        fresh=False,
        cook=False,
        frames=None,
        strict=False,
        external_references=False,
        dry_run=False,
        max_items=1000,
    ):
        for value, label in (
            (fresh, "fresh"),
            (cook, "cook"),
            (strict, "strict"),
            (external_references, "external_references"),
            (dry_run, "dry_run"),
        ):
            if not isinstance(value, bool):
                raise TypeError(label + " must be a boolean")
        maximum = _hcm_geometry_positive(max_items, "max_items", 10000)
        resolved = _hcm_resolve_node(node)
        definition = resolved.type().definition()
        if definition is None:
            raise ValueError("Node is not an HDA instance: " + resolved.path())
        frame_values = _hcm_hda_frames(frames, cook)
        if dry_run:
            return _hcm_hda_validation_plan(
                resolved,
                fresh,
                cook or bool(frame_values),
                frame_values,
                external_references or strict,
            )

        event = {
            "kind": "hda.validation",
            "helper": "ctx.hda.validate",
            "node_path": resolved.path(),
            "fresh": fresh,
            "cook": bool(frame_values),
            "frames": list(frame_values),
            "status": "started",
        }
        self._mutation_events.append(event)
        target = resolved
        temporary = None
        original_frame = float(_hcm_hou.frame())
        result = {
            "node_path": resolved.path(),
            "definition_current": bool(definition.isCurrent()),
            "locked": bool(resolved.isLockedHDA()),
            "matches": bool(resolved.matchesCurrentDefinition()),
            "library": str(definition.libraryFilePath()),
            "dry_run": False,
        }
        try:
            if fresh:
                parent = resolved.parent()
                temporary = parent.createNode(
                    str(resolved.type().name()), _hcm_hda_temporary_name(parent)
                )
                for index, source in enumerate(resolved.inputs()):
                    if source is not None:
                        temporary.setInput(index, source)
                target = temporary
                result["fresh_instance"] = target.path()
                self._mutation_events.append(
                    {
                        "kind": "node.create_temporary",
                        "helper": "ctx.hda.validate",
                        "node_path": target.path(),
                    }
                )
            frame_results = []
            for frame in frame_values:
                _hcm_hou.setFrame(frame)
                target.cook(force=True)
                frame_results.append({"frame": frame, **_hcm_hda_messages(target)})
            result["frames"] = frame_results
            result["parms"] = len(target.parms())
            result["input_count"] = _hcm_hda_connector_count(target, False)
            result["output_count"] = _hcm_hda_connector_count(target, True)
            validation_warnings = []
            cop_outputs = _hcm_hda_cop_outputs(target, maximum)
            if cop_outputs is not None:
                result["cop_outputs"] = cop_outputs
                validation_warnings.extend(cop_outputs["warnings"])
            conditional_ui = _hcm_hda_conditional_audit(
                target, definition, maximum
            )
            result["conditional_ui"] = conditional_ui
            if not conditional_ui["ok"]:
                validation_warnings.append(
                    "Published HDA parameter conditionals differ or were truncated"
                )
            result["warnings"] = validation_warnings
            result["ok"] = not validation_warnings
            if external_references or strict:
                reference_audit = _HCMHdaReferenceService().audit(
                    target,
                    descendants=True,
                    max_nodes=maximum,
                    max_parms=min(maximum * 100, 100000),
                    max_results=maximum,
                    max_errors=min(maximum, 1000),
                )
                result["external_references"] = reference_audit
                result["ok"] = result["ok"] and reference_audit["count"] == 0
            compress_method = getattr(target, "isGenericFlagSet", None)
            if callable(compress_method):
                try:
                    result["compress"] = bool(
                        compress_method(_hcm_hou.nodeFlag.Compress)
                    )
                except BaseException:
                    result["compress"] = None
            frame_warnings = [
                warning
                for row in frame_results
                for warning in row.get("warnings", [])
            ]
            frame_errors = [
                error for row in frame_results for error in row.get("errors", [])
            ]
            external_count = result.get("external_references", {}).get("count", 0)
            if strict and (
                validation_warnings or frame_warnings or frame_errors or external_count
            ):
                messages = validation_warnings + frame_warnings + frame_errors
                if external_count:
                    messages.append(
                        "External HDA parameter references: {}".format(external_count)
                    )
                raise ValueError(
                    "Strict HDA validation failed: "
                    + "; ".join(messages)
                )
            event["status"] = "complete"
            event["ok"] = result["ok"] and not frame_errors
            return result
        except BaseException:
            event["status"] = "error"
            raise
        finally:
            if frame_values:
                _hcm_hou.setFrame(original_frame)
            event["frame_restored"] = bool(frame_values)
            if temporary is not None:
                temporary_path = temporary.path()
                temporary.destroy()
                self._mutation_events.append(
                    {
                        "kind": "node.destroy_temporary",
                        "helper": "ctx.hda.validate",
                        "node_path": temporary_path,
                    }
                )
'''
