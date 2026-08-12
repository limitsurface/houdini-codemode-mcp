"""Houdini-side Python COP/SOP binding extension source."""

from __future__ import annotations


PYTHON_SOURCE = r'''
_HCM_PYTHON_CONTROL_TYPES = {
    "string",
    "int",
    "float",
    "float2",
    "float3",
    "float4",
    "ramp",
}
_HCM_PYTHON_GENERATED_FOLDER = "folder_generatedparms_pythoncode"
_HCM_PYTHON_MAX_BINDINGS = 1000
_HCM_PYTHON_VDB_TYPES = {
    "any": "fnvdb",
    "float": "fvdb",
    "vector": "vvdb",
    "int": "ivdb",
    "floatn": "fnvdb",
}


def _hcm_python_context(node):
    category = str(node.type().category().name()).lower()
    code = node.parm("pythoncode")
    bindings = node.parm("bindings")
    if code is None or bindings is None:
        raise ValueError("Node is not a supported Python binding node: " + node.path())
    if category == "sop" and str(node.type().name()) == "pythonsnippet":
        return "sop"
    if category.startswith("cop"):
        return "cop"
    raise ValueError("Unsupported Python node context: " + node.path())


def _hcm_python_extract(node):
    _hcm_python_context(node)
    code = str(node.parm("pythoncode").evalAsString())
    bindings = list(_hcm_hou.text.oclExtractBindings(code))
    if len(bindings) > _HCM_PYTHON_MAX_BINDINGS:
        raise ValueError(
            "Python code contains more than {} bindings".format(
                _HCM_PYTHON_MAX_BINDINGS
            )
        )
    return [dict(binding) for binding in bindings]


def _hcm_python_desired_rows(bindings):
    return [
        {"name": str(binding["name"]), "type": str(binding["type"])}
        for binding in bindings
        if str(binding["type"]) in _HCM_PYTHON_CONTROL_TYPES
    ]


def _hcm_python_current_rows(node):
    count = int(node.parm("bindings").eval())
    if count < 0 or count > _HCM_PYTHON_MAX_BINDINGS:
        raise ValueError("Python binding row count is outside the supported limit")
    rows = []
    for index in range(1, count + 1):
        name_parm = node.parm("bindings{}_name".format(index))
        type_parm = node.parm("bindings{}_type".format(index))
        if name_parm is None or type_parm is None:
            raise ValueError("Python binding row {} is incomplete".format(index))
        rows.append(
            {
                "name": str(name_parm.evalAsString()),
                "type": str(type_parm.evalAsString()),
            }
        )
    return rows


def _hcm_python_signature_type(binding, output):
    kind = str(binding["type"])
    if kind == "layer":
        value = str(binding["layertype"])
        return "floatn" if value == "float?" else value
    if kind in ("attribute", "volume", "geo"):
        return "geo"
    if kind == "vdb":
        return _HCM_PYTHON_VDB_TYPES[str(binding["vdbtype"])]
    if not output and kind == "metadata":
        return "metadata"
    raise ValueError("Unsupported Python COP port binding type: " + kind)


def _hcm_python_desired_ports(bindings, output):
    entries = []
    grouped = {}
    for binding in bindings:
        kind = str(binding["type"])
        readable = bool(binding["readable"])
        writeable = bool(binding["writeable"])
        optional = bool(binding["optional"])
        if output:
            if not writeable:
                continue
        elif kind == "layer" and not readable and not writeable:
            entries.append(
                {"name": str(binding["name"]), "type": "metadata", "optional": optional}
            )
            continue
        elif not readable:
            continue
        if kind == "layer":
            entry = {
                "name": str(binding.get("portname") or binding["name"]),
                "type": _hcm_python_signature_type(binding, output),
            }
            if not output:
                entry["optional"] = optional
            entries.append(entry)
            continue
        if kind not in ("attribute", "volume", "vdb", "geo"):
            continue
        name = str(binding.get("portname") or binding["name"])
        port_type = _hcm_python_signature_type(binding, output)
        key = (name, port_type)
        if key not in grouped:
            grouped[key] = len(entries)
            entry = {"name": name, "type": port_type}
            if not output:
                entry["optional"] = optional
            entries.append(entry)
        else:
            entries[grouped[key]]["optional"] = (
                bool(entries[grouped[key]]["optional"]) and optional
            )
    return entries


def _hcm_python_current_ports(node, output):
    count_parm = node.parm("outputs" if output else "inputs")
    if count_parm is None:
        raise ValueError("Python COP signature count parameter is missing")
    count = int(count_parm.eval())
    if count < 0 or count > _HCM_PYTHON_MAX_BINDINGS:
        raise ValueError("Python COP signature count is outside the supported limit")
    prefix = "output" if output else "input"
    rows = []
    for index in range(1, count + 1):
        name_parm = node.parm("{}{}_name".format(prefix, index))
        type_parm = node.parm("{}{}_type".format(prefix, index))
        if name_parm is None or type_parm is None:
            raise ValueError("Python COP signature row {} is incomplete".format(index))
        row = {
            "name": str(name_parm.evalAsString()),
            "type": str(type_parm.evalAsString() or "floatn"),
        }
        if not output:
            optional_parm = node.parm("input{}_optional".format(index))
            row["optional"] = bool(optional_parm.eval()) if optional_parm else False
        rows.append(row)
    return rows


def _hcm_python_generated_controls(node):
    folder = node.parmTemplateGroup().find(_HCM_PYTHON_GENERATED_FOLDER)
    if folder is None:
        return []
    return [str(template.name()) for template in folder.parmTemplates()]


def _hcm_python_control(node, name):
    return (
        node.parm(name)
        or node.parmTuple(name)
        or node.parm(name + "_val")
        or node.parmTuple(name + "_val")
    )


def _hcm_python_control_rows(node, bindings):
    generated = set(_hcm_python_generated_controls(node))
    rows = []
    row_index = 0
    for binding in bindings:
        kind = str(binding["type"])
        if kind not in _HCM_PYTHON_CONTROL_TYPES:
            continue
        row_index += 1
        base = str(binding["name"])
        control = _hcm_python_control(node, base)
        name = str(control.name()) if control is not None else None
        suffix = {
            "string": "sval",
            "int": "intval",
            "float": "fval",
            "float2": "v2val1",
            "float3": "v3val1",
            "float4": "v4val1",
        }.get(kind)
        if kind == "ramp":
            suffix = "ramp_rgb" if str(binding["ramptype"]) == "vector" else "ramp"
        link = node.parm("bindings{}_{}".format(row_index, suffix)) if suffix else None
        linked = False
        if control is not None and link is not None:
            try:
                raw = str(link.rawValue())
                linked = any(
                    token in raw
                    for token in (
                        '"./{}'.format(name),
                        "'./{}".format(name),
                        '"{}"'.format(name),
                        "'{}'".format(name),
                    )
                )
            except BaseException:
                linked = False
        rows.append(
            {
                "binding": base,
                "type": kind,
                "control": name,
                "generated": name in generated if name else False,
                "missing": control is None,
                "linked": linked,
            }
        )
    return rows


def _hcm_python_validation(node, bindings):
    context = _hcm_python_context(node)
    desired_rows = _hcm_python_desired_rows(bindings)
    current_rows = _hcm_python_current_rows(node)
    controls = _hcm_python_control_rows(node, bindings)
    missing = [row["binding"] for row in controls if row["missing"]]
    unlinked = [
        row["binding"] for row in controls if not row["missing"] and not row["linked"]
    ]
    generated = _hcm_python_generated_controls(node)
    desired_names = {row["name"] for row in desired_rows}
    stale = [
        name
        for name in generated
        if name not in desired_names
        and not (name.endswith("_val") and name[:-4] in desired_names)
    ]
    rows_match = current_rows == desired_rows
    hints = []
    result = {
        "node_path": node.path(),
        "context": context,
        "binding_count": len(bindings),
        "bindings_match_code": rows_match,
        "desired_bindings": desired_rows,
        "current_bindings": current_rows,
        "controls": controls,
        "generated_controls": generated,
        "missing_controls": missing,
        "unlinked_controls": unlinked,
        "stale_generated_controls": stale,
    }
    signature_matches = True
    if context == "cop":
        desired_inputs = _hcm_python_desired_ports(bindings, False)
        desired_outputs = _hcm_python_desired_ports(bindings, True)
        current_inputs = _hcm_python_current_ports(node, False)
        current_outputs = _hcm_python_current_ports(node, True)
        signature_matches = (
            current_inputs == desired_inputs and current_outputs == desired_outputs
        )
        result.update(
            {
                "signature_matches_code": signature_matches,
                "desired_inputs": desired_inputs,
                "desired_outputs": desired_outputs,
                "current_inputs": current_inputs,
                "current_outputs": current_outputs,
            }
        )
        if not signature_matches:
            hints.append("Python COP signature differs from #bind directives")
    if not rows_match:
        hints.append("Python {} binding rows differ from #bind directives".format(context.upper()))
    if missing:
        hints.append("Missing controls: " + ", ".join(missing))
    if unlinked:
        hints.append("Binding rows are not linked to controls: " + ", ".join(unlinked))
    if stale:
        hints.append("Stale generated controls: " + ", ".join(stale))
    clean = signature_matches and rows_match and not missing and not unlinked and not stale
    result["sync_required"] = not clean
    result["ok"] = clean
    result["hints"] = hints
    return result


def _hcm_python_compact(data):
    result = {
        "node_path": data["node_path"],
        "context": data["context"],
        "binding_count": data["binding_count"],
        "clean": data["ok"],
        "sync_required": data["sync_required"],
        "input_count": len(data.get("current_inputs", [])),
        "output_count": len(data.get("current_outputs", [])),
        "control_count": len(data["controls"]),
        "missing_control_count": len(data["missing_controls"]),
        "unlinked_control_count": len(data["unlinked_controls"]),
        "stale_generated_count": len(data["stale_generated_controls"]),
    }
    if data["hints"]:
        result["hints"] = data["hints"]
    return result


def _hcm_python_capture_spare_state(node):
    states = {}
    for parm in node.spareParms():
        template_type = str(parm.parmTemplate().type().name())
        if template_type in ("Folder", "FolderSet", "Button", "Label", "Separator"):
            continue
        name = str(parm.name())
        state = {}
        try:
            state["expression"] = parm.expression()
            state["language"] = parm.expressionLanguage()
        except BaseException:
            try:
                state["value"] = parm.eval()
            except BaseException:
                continue
        states[name] = state
    return states


def _hcm_python_restore_spare_state(node, states):
    restored = []
    for name, state in states.items():
        parm = node.parm(name)
        if parm is None:
            continue
        if "expression" in state:
            try:
                parm.setExpression(state["expression"], state.get("language"))
            except TypeError:
                parm.setExpression(state["expression"])
        elif "value" in state:
            parm.set(state["value"])
        restored.append(name)
    return restored


def _hcm_python_prune_generated(node, desired_names):
    group = node.parmTemplateGroup()
    folder = group.find(_HCM_PYTHON_GENERATED_FOLDER)
    if folder is None:
        return []
    updated = folder.clone()
    removed = []
    kept = []
    for template in updated.parmTemplates():
        name = str(template.name())
        if name not in desired_names and not (
            name.endswith("_val") and name[:-4] in desired_names
        ):
            removed.append(name)
        else:
            kept.append(template)
    if removed:
        updated.setParmTemplates(tuple(kept))
        group.replace(_HCM_PYTHON_GENERATED_FOLDER, updated)
        node.setParmTemplateGroup(group)
    return removed


def _hcm_python_remove_incompatible(node, bindings):
    generated = set(_hcm_python_generated_controls(node))
    incompatible_generated = []
    incompatible_external = []
    for binding in bindings:
        kind = str(binding["type"])
        if kind not in _HCM_PYTHON_CONTROL_TYPES:
            continue
        name = str(binding["name"])
        control = _hcm_python_control(node, name)
        if control is None:
            continue
        template = control.parmTemplate()
        actual_type = str(template.type().name())
        expected_type = (
            "String"
            if kind == "string"
            else "Int"
            if kind == "int"
            else "Ramp"
            if kind == "ramp"
            else "Float"
        )
        compatible = actual_type == expected_type
        if compatible and kind.startswith("float"):
            expected_size = {"float": 1, "float2": 2, "float3": 3, "float4": 4}[kind]
            compatible = int(template.numComponents()) == expected_size
        if compatible and kind == "ramp":
            expected_ramp = "Color" if str(binding["ramptype"]) == "vector" else "Float"
            compatible = str(template.parmType().name()) == expected_ramp
        if not compatible:
            target = incompatible_generated if name in generated else incompatible_external
            target.append(name)
    if incompatible_external:
        raise ValueError(
            "Externally organized Python controls have incompatible types: "
            + ", ".join(incompatible_external)
        )
    if not incompatible_generated:
        return []
    group = node.parmTemplateGroup()
    folder = group.find(_HCM_PYTHON_GENERATED_FOLDER)
    updated = folder.clone()
    updated.setParmTemplates(
        tuple(
            template
            for template in updated.parmTemplates()
            if str(template.name()) not in incompatible_generated
        )
    )
    group.replace(_HCM_PYTHON_GENERATED_FOLDER, updated)
    node.setParmTemplateGroup(group)
    return incompatible_generated


def _hcm_python_capture_connections(node):
    ports = _hcm_python_current_ports(node, False)
    rows = []
    for connection in node.inputConnections():
        index = int(connection.inputIndex())
        source = connection.inputNode()
        if source is None or not 0 <= index < len(ports):
            continue
        rows.append(
            {
                "name": ports[index]["name"],
                "from_path": source.path(),
                "from_output_index": int(connection.outputIndex()),
                "source_node": source,
            }
        )
    return rows


def _hcm_python_restore_connections(node, ports, captured):
    indices = {}
    for index, port in enumerate(ports):
        indices.setdefault(str(port["name"]), []).append(index)
    for connection in list(node.inputConnections()):
        node.setInput(int(connection.inputIndex()), None)
    used = {}
    restored = []
    dropped = []
    for row in captured:
        name = str(row["name"])
        occurrence = used.get(name, 0)
        used[name] = occurrence + 1
        choices = indices.get(name, [])
        public = {key: value for key, value in row.items() if key != "source_node"}
        if occurrence >= len(choices):
            dropped.append(public)
            continue
        to_index = choices[occurrence]
        node.setInput(to_index, row["source_node"], int(row["from_output_index"]))
        restored.append(dict(public, to_input_index=to_index))
    return restored, dropped


def _hcm_python_sync_impl(node, bindings, context, bindings_only, prune_generated, preserve_values):
    state = _hcm_python_capture_spare_state(node) if preserve_values else {}
    connections = (
        _hcm_python_capture_connections(node)
        if context == "cop" and not bindings_only
        else []
    )
    existing_inputs = int(node.parm("inputs").eval()) if context == "cop" else 0
    existing_outputs = int(node.parm("outputs").eval()) if context == "cop" else 0
    replaced = []
    if context == "sop":
        replaced = _hcm_python_remove_incompatible(node, bindings)
        for name in replaced:
            state.pop(name, None)
    if context == "cop" and not bindings_only:
        node.parm("inputs").set(0)
        node.parm("outputs").set(0)
    node.parm("bindings").set(0)
    module = __import__("vexpressionmenu")
    module.createSpareParmsFromOCLBindings(node, "pythoncode")
    if context == "cop" and bindings_only:
        node.parm("inputs").set(existing_inputs)
        node.parm("outputs").set(existing_outputs)
    desired_names = {row["name"] for row in _hcm_python_desired_rows(bindings)}
    removed = (
        _hcm_python_prune_generated(node, desired_names) if prune_generated else []
    )
    restored_values = _hcm_python_restore_spare_state(node, state) if state else []
    restored_connections = []
    dropped_connections = []
    if context == "cop" and not bindings_only:
        restored_connections, dropped_connections = _hcm_python_restore_connections(
            node, _hcm_python_current_ports(node, False), connections
        )
    return {
        "removed_generated_controls": removed,
        "replaced_generated_controls": replaced,
        "restored_controls": restored_values,
        "restored_connections": restored_connections,
        "dropped_connections": dropped_connections,
    }


class _HCMPythonService:
    def __init__(self, mutation_events):
        self._mutation_events = mutation_events

    def inspect(self, node, details=False):
        return self.validate(node, details=details)

    def validate(self, node, details=False):
        if not isinstance(details, bool):
            raise TypeError("details must be a boolean")
        resolved = _hcm_resolve_node(node)
        bindings = _hcm_python_extract(resolved)
        data = _hcm_python_validation(resolved, bindings)
        return data if details else _hcm_python_compact(data)

    def sync(
        self,
        node,
        dry_run=False,
        bindings_only=False,
        prune_generated=False,
        preserve_values=True,
        details=False,
    ):
        for value, label in (
            (dry_run, "dry_run"),
            (bindings_only, "bindings_only"),
            (prune_generated, "prune_generated"),
            (preserve_values, "preserve_values"),
            (details, "details"),
        ):
            if not isinstance(value, bool):
                raise TypeError("{} must be a boolean".format(label))
        resolved = _hcm_resolve_node(node)
        context = _hcm_python_context(resolved)
        if context == "sop" and bindings_only:
            raise ValueError("bindings_only is only meaningful for Python COPs")
        bindings = _hcm_python_extract(resolved)
        before = _hcm_python_validation(resolved, bindings)
        if dry_run:
            result = _hcm_python_compact(before)
            result["dry_run"] = True
            if details:
                result["validation"] = before
            return result
        event = {
            "kind": "python.interface_sync",
            "helper": "ctx.python.sync",
            "node_path": resolved.path(),
            "context": context,
            "status": "started",
        }
        self._mutation_events.append(event)
        changes = _hcm_python_sync_impl(
            resolved,
            bindings,
            context,
            bindings_only,
            prune_generated,
            preserve_values,
        )
        after = _hcm_python_validation(resolved, bindings)
        event["status"] = "complete"
        event["clean"] = bool(after["ok"])
        result = _hcm_python_compact(after)
        result.update(
            {
                "dry_run": False,
                "bindings_only": bindings_only,
                "prune_generated": prune_generated,
                "preserve_values": preserve_values,
                **changes,
            }
        )
        if details:
            result["validation"] = after
        return result
'''
