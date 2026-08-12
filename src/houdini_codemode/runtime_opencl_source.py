"""Houdini-side OpenCL validation extension source."""

from __future__ import annotations


OPENCL_SOURCE = r'''
import re as _hcm_opencl_re


_HCM_OPENCL_MAX_BINDINGS = 1000
_HCM_OPENCL_SPARE_TYPES = {"int", "float", "float2", "float3", "float4", "ramp"}
_HCM_OPENCL_VDB_SIGNATURE_TYPES = {
    "any": "fnvdb",
    "float": "fvdb",
    "vector": "vvdb",
    "int": "ivdb",
    "floatn": "fnvdb",
}
_HCM_OPENCL_BIND_RE = _hcm_opencl_re.compile(r"(?m)^[ \t]*#bind\b([^\r\n]*)")
_HCM_OPENCL_BVH_RE = _hcm_opencl_re.compile(
    r"(?<![A-Za-z0-9_])(?:pointbvhmask\s*=\s*[^\s/]+|nopointbvh|pointbvh|nobvh|bvh)"
)


def _hcm_opencl_binding_value(binding, key, default=None):
    try:
        return binding[key]
    except (KeyError, TypeError):
        return default


def _hcm_opencl_enrich_bvh(kernel_code, bindings):
    directives = _HCM_OPENCL_BIND_RE.findall(kernel_code)
    result = []
    for index, binding in enumerate(bindings):
        row = dict(binding)
        row.setdefault("bvh", False)
        row.setdefault("pointbvh", False)
        row.setdefault("pointbvhmask", "")
        if index < len(directives) and str(row.get("type", "")) == "attribute":
            source = directives[index].split("//", 1)[0]
            bvh = False
            pointbvh = False
            pointbvhmask = ""
            for match in _HCM_OPENCL_BVH_RE.finditer(source):
                token = _hcm_opencl_re.sub(r"\s+", "", match.group(0))
                if token == "bvh":
                    bvh = True
                elif token == "nobvh":
                    bvh = False
                elif token == "pointbvh":
                    pointbvh = True
                elif token == "nopointbvh":
                    pointbvh = False
                elif token.startswith("pointbvhmask="):
                    pointbvhmask = token.split("=", 1)[1]
            row["bvh"] = bvh
            row["pointbvh"] = pointbvh
            row["pointbvhmask"] = pointbvhmask
        result.append(row)
    return result


def _hcm_opencl_bvh_summary(binding):
    return {
        "bvh": bool(_hcm_opencl_binding_value(binding, "bvh", False)),
        "pointbvh": bool(_hcm_opencl_binding_value(binding, "pointbvh", False)),
        "pointbvhmask": str(
            _hcm_opencl_binding_value(binding, "pointbvhmask", "")
        ),
    }


def _hcm_opencl_accelerated(bindings):
    rows = []
    for binding in bindings:
        acceleration = _hcm_opencl_bvh_summary(binding)
        if not any(acceleration.values()):
            continue
        mode = (
            "surface_bvh"
            if acceleration["bvh"]
            else "point_bvh"
            if acceleration["pointbvh"]
            else "none"
        )
        row = {"name": str(binding["name"]), "mode": mode}
        if acceleration["pointbvhmask"]:
            row["point_mask"] = acceleration["pointbvhmask"]
        rows.append(row)
    return rows


def _hcm_opencl_preflight_bvh(bindings):
    accelerated = [
        binding for binding in bindings if any(_hcm_opencl_bvh_summary(binding).values())
    ]
    if not accelerated:
        return
    try:
        major = int(_hcm_hou.applicationVersion()[0])
    except BaseException:
        major = 22
    if major < 22:
        raise ValueError("OpenCL BVH attribute bindings require Houdini 22 or newer")
    for binding in accelerated:
        name = str(binding["name"])
        acceleration = _hcm_opencl_bvh_summary(binding)
        if acceleration["bvh"] and acceleration["pointbvh"]:
            raise ValueError(
                "OpenCL binding {!r} cannot combine bvh and pointbvh".format(name)
            )
        if str(binding["type"]) != "attribute":
            raise ValueError(
                "OpenCL BVH binding {!r} must be an attribute binding".format(name)
            )
        if not bool(binding["readable"]):
            raise ValueError(
                "OpenCL BVH binding {!r} must be readable".format(name)
            )
        attribclass = str(binding["attribclass"])
        attribtype = str(binding["attribtype"])
        attribsize = int(binding["attribsize"])
        if attribtype != "float" or attribsize != 3:
            raise ValueError(
                "OpenCL BVH binding {!r} must be a float3 attribute".format(name)
            )
        if acceleration["bvh"] and attribclass not in ("point", "vertex"):
            raise ValueError(
                "Surface BVH binding {!r} must use a point or vertex attribute".format(
                    name
                )
            )
        if acceleration["pointbvh"] and attribclass != "point":
            raise ValueError(
                "Point BVH binding {!r} must use a point attribute".format(name)
            )
        if acceleration["pointbvhmask"] and not acceleration["pointbvh"]:
            raise ValueError(
                "OpenCL binding {!r} uses pointbvhmask without pointbvh".format(name)
            )


def _hcm_opencl_context(node):
    try:
        category = str(node.type().category().name()).lower()
    except BaseException:
        category = ""
    if category == "sop":
        return "sop"
    if category == "dop":
        return "dop"
    return "cop"


def _hcm_opencl_messages(node):
    result = {}
    for key in ("errors", "warnings", "messages"):
        method = getattr(node, key, None)
        try:
            result[key] = [str(value) for value in method()] if callable(method) else []
        except BaseException:
            result[key] = []
    return result


def _hcm_opencl_safe_cook(node):
    method = getattr(node, "cook", None)
    if not callable(method):
        return
    try:
        method(force=True)
    except TypeError:
        method()
    except BaseException:
        return


def _hcm_opencl_current_binding_rows(node, context):
    count_name = "paramcount" if context == "dop" else "bindings"
    count_parm = node.parm(count_name)
    if count_parm is None:
        return []
    try:
        count = int(count_parm.eval())
    except BaseException:
        return []
    if count < 0 or count > _HCM_OPENCL_MAX_BINDINGS:
        raise ValueError("OpenCL binding row count is outside the supported limit")
    rows = []
    for index in range(1, count + 1):
        if context == "dop":
            prefix = "parameter{}".format(index)
            name_parm = node.parm(prefix + "Name")
            type_parm = node.parm(prefix + "Type")
            bvh_parm = node.parm(prefix + "BuildBVH")
            pointbvh_parm = node.parm(prefix + "BuildPointBVH")
            mask_parm = node.parm(prefix + "PointBVHMask")
        else:
            prefix = "bindings{}_".format(index)
            name_parm = node.parm(prefix + "name")
            type_parm = node.parm(prefix + "type")
            bvh_parm = node.parm(prefix + "attribbvh")
            pointbvh_parm = node.parm(prefix + "attribpointbvh")
            mask_parm = node.parm(prefix + "attribpointbvhmask")
        if name_parm is None or type_parm is None:
            continue
        try:
            rows.append(
                {
                    "name": str(name_parm.evalAsString()),
                    "type": str(type_parm.evalAsString()),
                    "bvh": bool(bvh_parm.eval()) if bvh_parm is not None else False,
                    "pointbvh": bool(pointbvh_parm.eval())
                    if pointbvh_parm is not None
                    else False,
                    "pointbvhmask": str(mask_parm.evalAsString())
                    if mask_parm is not None
                    else "",
                }
            )
        except BaseException:
            continue
    return rows


def _hcm_opencl_desired_binding_rows(bindings):
    return [
        {
            "name": str(binding["name"]),
            "type": str(binding["type"]),
            **_hcm_opencl_bvh_summary(binding),
        }
        for binding in bindings
    ]


def _hcm_opencl_row_validation(node, bindings, runover, context):
    current_rows = _hcm_opencl_current_binding_rows(node, context)
    desired_rows = _hcm_opencl_desired_binding_rows(bindings) if bindings else current_rows
    matches = current_rows == desired_rows
    messages = _hcm_opencl_messages(node)
    hints = []
    if not matches:
        hints.append(
            "OpenCL {} binding rows differ from the kernel directives; synchronize the node interface".format(
                context.upper()
            )
        )
    return {
        "node_path": node.path(),
        "context": context,
        "runover": runover,
        "binding_count": len(desired_rows),
        "bindings_match_kernel": matches,
        "signature_matches_kernel": None,
        "sync_required": not matches,
        "invalid_connection_count": 0,
        "missing_required_count": 0,
        "ok": matches and not messages["errors"],
        "desired_bindings": desired_rows,
        "current_bindings": current_rows,
        "desired_inputs": [],
        "desired_outputs": [],
        "current_inputs": [],
        "current_outputs": [],
        "inputs": [],
        "hints": hints,
        **messages,
    }


def _hcm_opencl_signature_type(binding_type, binding, output):
    if binding_type == "layer":
        return str(binding["layertype"])
    if binding_type in ("attribute", "volume"):
        return "geo"
    if binding_type == "vdb":
        return _HCM_OPENCL_VDB_SIGNATURE_TYPES[str(binding["vdbtype"])]
    if not output and binding_type == "metadata":
        return "metadata"
    raise ValueError(
        "Unsupported binding type for OpenCL signature validation: " + binding_type
    )


def _hcm_opencl_desired_signature(bindings, output):
    entries = []
    grouped_indices = {}
    for binding in bindings:
        binding_type = str(binding["type"])
        readable = bool(binding["readable"])
        writeable = bool(binding["writeable"])
        optional = bool(binding["optional"])
        if output:
            if not writeable:
                continue
        else:
            if binding_type == "layer" and not readable and not writeable:
                entries.append(
                    {
                        "name": str(binding["name"]),
                        "type": "metadata",
                        "optional": optional,
                        "precision": str(binding["precision"]),
                    }
                )
                continue
            if not readable:
                continue
        if binding_type == "layer":
            entries.append(
                {
                    "name": str(binding["name"]),
                    "type": _hcm_opencl_signature_type(binding_type, binding, output),
                    "optional": optional,
                    "precision": str(binding["precision"]),
                }
            )
            continue
        if binding_type not in ("attribute", "volume", "vdb"):
            continue
        portname = str(binding["portname"])
        resolved_type = _hcm_opencl_signature_type(binding_type, binding, output)
        key = (resolved_type, portname)
        existing_index = grouped_indices.get(key)
        if existing_index is None:
            grouped_indices[key] = len(entries)
            entries.append(
                {
                    "name": portname,
                    "type": resolved_type,
                    "optional": optional,
                    "precision": str(binding["precision"]),
                }
            )
        else:
            entries[existing_index]["optional"] = (
                bool(entries[existing_index]["optional"]) and optional
            )
    return entries


def _hcm_opencl_existing_signature(node, output):
    count_parm = node.parm("outputs" if output else "inputs")
    if count_parm is None:
        return []
    try:
        count = int(count_parm.eval())
    except BaseException:
        return []
    if count < 0 or count > _HCM_OPENCL_MAX_BINDINGS:
        raise ValueError("OpenCL signature row count is outside the supported limit")
    prefix = "output" if output else "input"
    result = []
    for index in range(1, count + 1):
        name_parm = node.parm("{}{}_name".format(prefix, index))
        type_parm = node.parm("{}{}_type".format(prefix, index))
        if name_parm is None or type_parm is None:
            continue
        try:
            name = str(name_parm.evalAsString())
            signature_type = str(type_parm.evalAsString() or "floatn")
        except BaseException:
            continue
        if not name:
            continue
        entry = {"name": name, "type": signature_type, "optional": False}
        if not output:
            optional_parm = node.parm("input{}_optional".format(index))
            try:
                entry["optional"] = (
                    bool(optional_parm.eval()) if optional_parm is not None else False
                )
            except BaseException:
                entry["optional"] = False
        result.append(entry)
    return result


def _hcm_opencl_input_types(node):
    try:
        return [str(value) for value in node.inputDataTypes()]
    except BaseException:
        return []


def _hcm_opencl_output_types(node):
    try:
        return [str(value) for value in node.outputDataTypes()]
    except BaseException:
        return []


def _hcm_opencl_input_connections(node):
    result = {}
    try:
        connections = list(node.inputConnections())
    except BaseException:
        return result
    for connection in connections:
        source = connection.inputNode()
        output_index = int(connection.outputIndex())
        source_types = _hcm_opencl_output_types(source) if source is not None else []
        source_type = (
            source_types[output_index]
            if 0 <= output_index < len(source_types)
            else None
        )
        try:
            output_name = str(connection.inputName())
        except BaseException:
            output_name = None
        try:
            output_label = str(connection.inputLabel())
        except BaseException:
            output_label = None
        result[int(connection.inputIndex())] = {
            "from_path": source.path() if source is not None else None,
            "from_output_index": output_index,
            "from_output_name": output_name,
            "from_output_label": output_label,
            "source_output_type": source_type,
        }
    return result


def _hcm_opencl_binding_row_hints(node):
    count_parm = node.parm("bindings")
    if count_parm is None:
        return []
    try:
        count = int(count_parm.eval())
    except BaseException:
        return []
    if count < 0 or count > _HCM_OPENCL_MAX_BINDINGS:
        return ["OpenCL binding row count is outside the supported inspection limit"]
    layer_rows = []
    static_rows = []
    for index in range(1, count + 1):
        prefix = "bindings{}_".format(index)
        name_parm = node.parm(prefix + "name")
        type_parm = node.parm(prefix + "type")
        if name_parm is None or type_parm is None:
            continue
        try:
            name = str(name_parm.evalAsString())
            binding_type = str(type_parm.evalAsString())
        except BaseException:
            continue
        if binding_type == "layer":
            layer_rows.append(name)
            continue
        if binding_type not in _HCM_OPENCL_SPARE_TYPES:
            continue
        component_counts = {"int": 1, "float": 1, "float2": 2, "float3": 3, "float4": 4}
        component_count = component_counts.get(binding_type, 0)
        if component_count == 0:
            continue
        suffix_root = {
            "int": "intval",
            "float": "fval",
            "float2": "v2val",
            "float3": "v3val",
            "float4": "v4val",
        }[binding_type]
        for component in range(component_count):
            parm_name = prefix + suffix_root
            suffixes = ("",)
            if component_count > 1:
                parm_name += str(component + 1)
                suffixes = (str(component + 1), "xyzw"[component])
            parm = node.parm(parm_name)
            try:
                expression = str(parm.expression()) if parm is not None else None
            except BaseException:
                expression = None
            expected = {
                'ch("./{}{}")'.format(name, suffix) if suffix else 'ch("./{}")'.format(name)
                for suffix in suffixes
            }
            if expression not in expected:
                static_rows.append(name)
                break
    hints = []
    if layer_rows:
        hints.append(
            "OpenCL binding rows include layer bindings ({}); layers belong in the visible signature".format(
                ", ".join(layer_rows)
            )
        )
    if static_rows:
        hints.append(
            "OpenCL parm binding rows are not linked to generated spare parms ({})".format(
                ", ".join(dict.fromkeys(static_rows))
            )
        )
    return hints


def _hcm_opencl_types_compatible(expected, source):
    if expected is None or source is None:
        return None
    if source == expected:
        return True
    return expected == "RGBA" and source == "RGB"


def _hcm_opencl_cop_validation(node, bindings, runover):
    desired_inputs = _hcm_opencl_desired_signature(bindings, False)
    desired_outputs = _hcm_opencl_desired_signature(bindings, True)
    current_inputs = _hcm_opencl_existing_signature(node, False)
    current_outputs = _hcm_opencl_existing_signature(node, True)
    input_types = _hcm_opencl_input_types(node)
    connections = _hcm_opencl_input_connections(node)
    messages = _hcm_opencl_messages(node)
    hints = _hcm_opencl_binding_row_hints(node)
    input_rows = []
    invalid_connections = 0
    missing_required = 0
    for index, entry in enumerate(current_inputs):
        expected_type = input_types[index] if index < len(input_types) else None
        connected = connections.get(index)
        compatible = None
        if connected is None:
            compatible = bool(entry["optional"])
            if not entry["optional"]:
                missing_required += 1
        elif expected_type is not None and connected["source_output_type"] is not None:
            compatible = bool(
                _hcm_opencl_types_compatible(
                    expected_type, connected["source_output_type"]
                )
            )
            if not compatible:
                invalid_connections += 1
        else:
            compatible = False
            invalid_connections += 1
        row = {
            "index": index,
            "name": str(entry["name"]),
            "type": str(entry["type"]),
            "expected_data_type": expected_type,
            "optional": bool(entry["optional"]),
            "connected": connected is not None,
            "compatible": compatible,
        }
        if connected is not None:
            row.update(connected)
        input_rows.append(row)
    desired_input_rows = [
        {
            "name": entry["name"],
            "type": entry["type"],
            "optional": bool(entry["optional"]),
        }
        for entry in desired_inputs
    ]
    desired_output_rows = [
        {
            "name": entry["name"],
            "type": entry["type"],
            "optional": bool(entry.get("optional", False)),
        }
        for entry in desired_outputs
    ]
    current_output_rows = [
        {
            "name": entry["name"],
            "type": entry["type"],
            "optional": bool(entry.get("optional", False)),
        }
        for entry in current_outputs
    ]
    signature_matches = (
        current_inputs == desired_input_rows
        and current_output_rows == desired_output_rows
    )
    if not signature_matches:
        hints.append(
            "OpenCL signature differs from the kernel directives; synchronize the node interface"
        )
    return {
        "node_path": node.path(),
        "context": "cop",
        "runover": runover,
        "binding_count": len(bindings),
        "signature_matches_kernel": signature_matches,
        "sync_required": not signature_matches,
        "invalid_connection_count": invalid_connections,
        "missing_required_count": missing_required,
        "ok": signature_matches
        and invalid_connections == 0
        and missing_required == 0
        and not messages["errors"],
        "desired_inputs": desired_input_rows,
        "desired_outputs": desired_output_rows,
        "current_inputs": current_inputs,
        "current_outputs": current_output_rows,
        "inputs": input_rows,
        "hints": hints,
        **messages,
    }


def _hcm_opencl_compact(validation, bindings):
    binding_rows = []
    if bindings:
        for binding in bindings:
            binding_type = str(binding["type"])
            if binding_type in _HCM_OPENCL_SPARE_TYPES:
                direction = "parm"
            elif bool(binding["readable"]) and bool(binding["writeable"]):
                direction = "inout"
            elif bool(binding["writeable"]):
                direction = "output"
            else:
                direction = "input"
            binding_rows.append([str(binding["name"]), binding_type, direction])
    else:
        for row in validation.get("current_bindings", []):
            binding_type = str(row["type"])
            direction = "parm" if binding_type in _HCM_OPENCL_SPARE_TYPES else "input"
            binding_rows.append([str(row["name"]), binding_type, direction])
    result = {
        "node_path": validation["node_path"],
        "context": validation.get("context", "cop"),
        "runover": validation.get("runover", ""),
        "binding_count": validation["binding_count"],
        "binding_cols": ["name", "type", "direction"],
        "bindings": binding_rows,
        "clean": bool(validation["ok"]),
        "sync_required": bool(validation.get("sync_required", False)),
        "invalid_connection_count": validation.get("invalid_connection_count", 0),
        "missing_required_count": validation.get("missing_required_count", 0),
    }
    for key in ("errors", "warnings", "messages", "hints"):
        if validation.get(key):
            result[key] = validation[key]
    if validation.get("accelerated_bindings"):
        result["accelerated_bindings"] = validation["accelerated_bindings"]
    return result


def _hcm_opencl_vector(binding, key, size):
    value = binding[key]
    return [float(value[index]) for index in range(size)]


def _hcm_opencl_binding_parm_values(index, binding):
    prefix = "bindings{}_".format(index)
    binding_type = str(binding["type"])
    values = {
        prefix + "name": str(binding["name"]),
        prefix + "type": binding_type,
        prefix + "portname": str(_hcm_opencl_binding_value(binding, "portname", "")),
        prefix + "precision": str(_hcm_opencl_binding_value(binding, "precision", "float")),
        prefix + "optional": bool(_hcm_opencl_binding_value(binding, "optional", False)),
        prefix + "defval": bool(_hcm_opencl_binding_value(binding, "defval", False)),
        prefix + "readable": bool(_hcm_opencl_binding_value(binding, "readable", False)),
        prefix + "writeable": bool(_hcm_opencl_binding_value(binding, "writeable", False)),
        prefix + "timescale": str(_hcm_opencl_binding_value(binding, "timescale", "none")),
    }
    if binding_type == "layer":
        values[prefix + "layertype"] = str(binding["layertype"])
        values[prefix + "layerborder"] = str(
            _hcm_opencl_binding_value(binding, "layerborder", "none")
        )
    elif binding_type == "attribute":
        values[prefix + "input"] = int(_hcm_opencl_binding_value(binding, "input", 0))
        values[prefix + "attribute"] = str(binding["attribute"])
        values[prefix + "attribclass"] = str(binding["attribclass"])
        values[prefix + "attribtype"] = str(binding["attribtype"])
        values[prefix + "attribsize"] = int(binding["attribsize"])
        acceleration = _hcm_opencl_bvh_summary(binding)
        values[prefix + "attribbvh"] = acceleration["bvh"]
        values[prefix + "attribpointbvh"] = acceleration["pointbvh"]
        values[prefix + "attribpointbvhmask"] = acceleration["pointbvhmask"]
    elif binding_type == "volume":
        values[prefix + "input"] = int(_hcm_opencl_binding_value(binding, "input", 0))
        values[prefix + "volume"] = str(binding["volume"])
        values[prefix + "resolution"] = bool(binding["resolution"])
        values[prefix + "voxelsize"] = bool(binding["voxelsize"])
        values[prefix + "xformtoworld"] = bool(binding["xformtoworld"])
        values[prefix + "xformtovoxel"] = bool(binding["xformtovoxel"])
    elif binding_type == "vdb":
        values[prefix + "input"] = int(_hcm_opencl_binding_value(binding, "input", 0))
        values[prefix + "volume"] = str(binding["volume"])
        values[prefix + "vdbtype"] = str(binding["vdbtype"])
    elif binding_type == "int":
        values[prefix + "intval"] = int(binding["intval"])
    elif binding_type == "float":
        values[prefix + "fval"] = float(binding["fval"])
    elif binding_type == "float2":
        values[prefix + "v2val"] = _hcm_opencl_vector(binding, "v2val", 2)
    elif binding_type == "float3":
        values[prefix + "v3val"] = _hcm_opencl_vector(binding, "v3val", 3)
    elif binding_type == "float4":
        values[prefix + "v4val"] = _hcm_opencl_vector(binding, "v4val", 4)
    elif binding_type == "ramp":
        values[prefix + "rampsize"] = int(binding["rampsize"])
        values[prefix + "ramptype"] = str(binding["ramptype"])
    return values


def _hcm_opencl_component_names(node, binding):
    name = str(binding["name"])
    parm_tuple = node.parmTuple(name)
    if parm_tuple is None:
        parm_tuple = node.parmTuple(name + "_val")
    if parm_tuple is not None:
        try:
            return [str(parm.name()) for parm in parm_tuple]
        except BaseException:
            pass
    count = {"float2": 2, "float3": 3, "float4": 4}.get(
        str(binding["type"]), 1
    )
    return [name] if count == 1 else [name + str(index) for index in range(1, count + 1)]


def _hcm_opencl_capture_control_state(node, bindings):
    states = {}
    for binding in bindings:
        for name in _hcm_opencl_component_names(node, binding):
            parm = node.parm(name)
            if parm is None:
                continue
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


def _hcm_opencl_restore_control_state(node, states):
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
        else:
            parm.set(state["value"])
        restored.append(name)
    return restored


def _hcm_opencl_remove_generated_controls(node):
    group = node.parmTemplateGroup()
    changed = False
    for name in ("opencl_sync_controls", "folder_generatedparms_kernelcode"):
        try:
            group.remove(name)
            changed = True
        except BaseException:
            pass
    if changed:
        node.setParmTemplateGroup(group)


def _hcm_opencl_control_template(binding):
    name = str(binding["name"])
    label = name.replace("_", " ").title()
    binding_type = str(binding["type"])
    if binding_type == "int":
        return _hcm_hou.IntParmTemplate(
            name, label, 1, default_value=(int(binding["intval"]),)
        )
    if binding_type == "float":
        return _hcm_hou.FloatParmTemplate(
            name, label, 1, default_value=(float(binding["fval"]),)
        )
    if binding_type in ("float2", "float3", "float4"):
        size = int(binding_type[-1])
        return _hcm_hou.FloatParmTemplate(
            name,
            label,
            size,
            default_value=tuple(_hcm_opencl_vector(binding, "v{}val".format(size), size)),
        )
    if binding_type == "ramp":
        ramp_type = (
            _hcm_hou.rampParmType.Color
            if str(binding["ramptype"]) == "vector"
            else _hcm_hou.rampParmType.Float
        )
        return _hcm_hou.RampParmTemplate(
            name,
            label,
            ramp_type,
            default_value=2,
            default_basis=_hcm_hou.rampBasis.Linear,
        )
    raise ValueError("Unsupported OpenCL control type: " + binding_type)


def _hcm_opencl_sync_controls(node, bindings, preserve):
    controls = [
        binding
        for binding in bindings
        if str(binding["type"]) in _HCM_OPENCL_SPARE_TYPES
    ]
    states = _hcm_opencl_capture_control_state(node, controls) if preserve else {}
    _hcm_opencl_remove_generated_controls(node)
    if controls:
        group = node.parmTemplateGroup()
        folder = _hcm_hou.FolderParmTemplate(
            "folder_generatedparms_kernelcode", "Generated Channel Parameters"
        )
        for binding in controls:
            folder.addParmTemplate(_hcm_opencl_control_template(binding))
        try:
            group.insertBefore("kernelcode", folder)
        except BaseException:
            group.append(folder)
        node.setParmTemplateGroup(group)
    restored = _hcm_opencl_restore_control_state(node, states) if states else []
    return [str(binding["name"]) for binding in controls], restored


def _hcm_opencl_link_control_rows(node, bindings, context):
    for index, binding in enumerate(bindings, 1):
        binding_type = str(binding["type"])
        if binding_type not in _HCM_OPENCL_SPARE_TYPES:
            continue
        sources = _hcm_opencl_component_names(node, binding)
        if context == "dop":
            suffixes = {
                "int": ("Int",),
                "float": ("Flt",),
                "float3": ("Flt31", "Flt32", "Flt33"),
                "float4": ("Flt41", "Flt42", "Flt43", "Flt44"),
            }.get(binding_type, ())
            targets = ["parameter{}{}".format(index, suffix) for suffix in suffixes]
        else:
            prefix = "bindings{}_".format(index)
            targets = {
                "int": (prefix + "intval",),
                "float": (prefix + "fval",),
                "float2": tuple(prefix + "v2val" + str(i) for i in range(1, 3)),
                "float3": tuple(prefix + "v3val" + str(i) for i in range(1, 4)),
                "float4": tuple(prefix + "v4val" + str(i) for i in range(1, 5)),
                "ramp": (
                    prefix
                    + ("ramp_rgb" if str(binding["ramptype"]) == "vector" else "ramp"),
                ),
            }.get(binding_type, ())
        for target, source in zip(targets, sources):
            parm = node.parm(target)
            if parm is not None:
                parm.setExpression('ch("./{}")'.format(source))


def _hcm_opencl_sync_standard_rows(node, bindings, context):
    row_bindings = (
        [binding for binding in bindings if str(binding["type"]) in _HCM_OPENCL_SPARE_TYPES]
        if context == "cop"
        else bindings
    )
    node.setParms({"bindings": 0})
    if not row_bindings:
        return
    node.setParms({"bindings": len(row_bindings)})
    values = {}
    for index, binding in enumerate(row_bindings, 1):
        values.update(_hcm_opencl_binding_parm_values(index, binding))
    if context == "sop":
        values = {name: value for name, value in values.items() if node.parm(name) is not None}
    node.setParms(values)
    _hcm_opencl_link_control_rows(node, row_bindings, context)


def _hcm_opencl_dop_values(index, binding):
    prefix = "parameter{}".format(index)
    binding_type = str(binding["type"])
    values = {
        prefix + "Name": str(binding["name"]),
        prefix + "Type": binding_type,
        prefix + "Precision": str(_hcm_opencl_binding_value(binding, "precision", "float")),
        prefix + "Input": bool(_hcm_opencl_binding_value(binding, "readable", False)),
        prefix + "Output": bool(_hcm_opencl_binding_value(binding, "writeable", False)),
        prefix + "Optional": bool(_hcm_opencl_binding_value(binding, "optional", False)),
        prefix + "DefVal": bool(_hcm_opencl_binding_value(binding, "defval", False)),
        prefix + "TimeScale": str(_hcm_opencl_binding_value(binding, "timescale", "none")),
    }
    if binding_type in ("scalarfield", "vectorfield", "matrixfield"):
        values[prefix + "Field"] = str(binding["fieldname"])
        values[prefix + "Offsets"] = bool(binding["fieldoffsets"])
    elif binding_type == "attribute":
        values[prefix + "Geometry"] = str(binding["geometry"])
        values[prefix + "Attribute"] = str(binding["attribute"])
        values[prefix + "Class"] = str(binding["attribclass"])
        values[prefix + "AttributeType"] = str(binding["attribtype"])
        values[prefix + "AttributeSize"] = int(binding["attribsize"])
        acceleration = _hcm_opencl_bvh_summary(binding)
        values[prefix + "BuildBVH"] = acceleration["bvh"]
        values[prefix + "BuildPointBVH"] = acceleration["pointbvh"]
        values[prefix + "PointBVHMask"] = acceleration["pointbvhmask"]
    elif binding_type == "volume":
        values[prefix + "Geometry"] = str(binding["geometry"])
        values[prefix + "Volume"] = str(binding["volume"])
        values[prefix + "Resolution"] = bool(binding["resolution"])
        values[prefix + "VoxelSize"] = bool(binding["voxelsize"])
        values[prefix + "XformToWorld"] = bool(binding["xformtoworld"])
        values[prefix + "XformToVoxel"] = bool(binding["xformtovoxel"])
    elif binding_type == "vdb":
        values[prefix + "Geometry"] = str(binding["geometry"])
        values[prefix + "Volume"] = str(binding["volume"])
        values[prefix + "VDBType"] = str(binding["vdbtype"])
    elif binding_type == "option":
        values[prefix + "DataName"] = str(binding["dataname"])
        values[prefix + "OptionName"] = str(binding["optionname"])
        values[prefix + "OptionType"] = str(binding["optiontype"])
        values[prefix + "OptionSize"] = int(binding["optionsize"])
    elif binding_type == "ramp":
        values[prefix + "RampSize"] = int(binding["rampsize"])
    elif binding_type == "int":
        values[prefix + "Int"] = int(binding["intval"])
    elif binding_type == "float":
        values[prefix + "Flt"] = float(binding["fval"])
    elif binding_type == "float3":
        values[prefix + "Flt3"] = _hcm_opencl_vector(binding, "v3val", 3)
    elif binding_type == "float4":
        values[prefix + "Flt4"] = _hcm_opencl_vector(binding, "v4val", 4)
    else:
        raise ValueError("Unsupported Gas OpenCL binding type: " + binding_type)
    return values


def _hcm_opencl_sync_dop_rows(node, bindings):
    node.setParms({"paramcount": 0})
    if not bindings:
        return
    node.setParms({"paramcount": len(bindings)})
    values = {}
    for index, binding in enumerate(bindings, 1):
        values.update(_hcm_opencl_dop_values(index, binding))
    values = {name: value for name, value in values.items() if node.parm(name) is not None}
    node.setParms(values)
    _hcm_opencl_link_control_rows(node, bindings, "dop")


def _hcm_opencl_capture_connections(node):
    entries = _hcm_opencl_existing_signature(node, False)
    captured = []
    try:
        connections = list(node.inputConnections())
    except BaseException:
        return captured
    for connection in connections:
        index = int(connection.inputIndex())
        source = connection.inputNode()
        if source is None or not (0 <= index < len(entries)):
            continue
        captured.append(
            {
                "name": str(entries[index]["name"]),
                "from_path": source.path(),
                "from_output_index": int(connection.outputIndex()),
                "source_node": source,
            }
        )
    return captured


def _hcm_opencl_disconnect(node, index):
    try:
        node.setInput(index, None)
    except TypeError:
        node.setInput(index, None, 0)


def _hcm_opencl_restore_connections(node, entries, connections):
    indices = {}
    for index, entry in enumerate(entries):
        indices.setdefault(str(entry["name"]), []).append(index)
    for index in list(_hcm_opencl_input_connections(node)):
        _hcm_opencl_disconnect(node, index)
    restored = []
    dropped = []
    used = {}
    for connection in connections:
        name = str(connection["name"])
        occurrence = used.get(name, 0)
        used[name] = occurrence + 1
        candidates = indices.get(name, [])
        plain = {key: value for key, value in connection.items() if key != "source_node"}
        if occurrence >= len(candidates) or connection["source_node"] is None:
            dropped.append(plain)
            continue
        input_index = candidates[occurrence]
        node.setInput(
            input_index,
            connection["source_node"],
            int(connection["from_output_index"]),
        )
        plain["to_input_index"] = input_index
        restored.append(plain)
    return restored, dropped


def _hcm_opencl_sync_cop_signature(node, inputs, outputs):
    node.setParms({"inputs": 0, "outputs": 0})
    node.setParms({"inputs": len(inputs), "outputs": len(outputs)})
    values = {}
    for index, entry in enumerate(inputs, 1):
        values["input{}_name".format(index)] = str(entry["name"])
        values["input{}_type".format(index)] = str(entry["type"])
        values["input{}_optional".format(index)] = bool(entry["optional"])
    for index, entry in enumerate(outputs, 1):
        values["output{}_name".format(index)] = str(entry["name"])
        values["output{}_type".format(index)] = str(entry["type"])
        values["output{}_metadata".format(index)] = "first"
        values["output{}_precision".format(index)] = str(entry["precision"])
        values["output{}_typeinfo".format(index)] = "node"
        values["output{}_metaname".format(index)] = ""
    if values:
        node.setParms(values)


def _hcm_opencl_sync(
    node_value,
    clear,
    bindings_only,
    preserve_values,
    disconnect_invalid,
    details,
):
    for name, value in (
        ("clear", clear),
        ("bindings_only", bindings_only),
        ("preserve_values", preserve_values),
        ("disconnect_invalid", disconnect_invalid),
        ("details", details),
    ):
        if not isinstance(value, bool):
            raise TypeError(name + " must be a boolean")
    node = _hcm_resolve_node(node_value)
    kernel_parm = node.parm("kernelcode")
    if kernel_parm is None:
        raise ValueError("Node is not an OpenCL node: " + node.path())
    kernel_code = str(kernel_parm.evalAsString())
    if not kernel_code.strip():
        raise ValueError(
            "Kernel Code is empty; OpenCL sync does not rebuild external-kernel interfaces"
        )
    bindings = list(_hcm_hou.text.oclExtractBindings(kernel_code))
    if len(bindings) > _HCM_OPENCL_MAX_BINDINGS:
        raise ValueError(
            "Kernel contains more than {} OpenCL bindings".format(
                _HCM_OPENCL_MAX_BINDINGS
            )
        )
    bindings = _hcm_opencl_enrich_bvh(kernel_code, bindings)
    _hcm_opencl_preflight_bvh(bindings)
    runover = str(_hcm_hou.text.oclExtractRunOver(kernel_code))
    context = _hcm_opencl_context(node)
    use_code = node.parm("usecode")
    if use_code is not None and not bool(use_code.eval()):
        use_code.set(True)
    at_binding = node.parm("atbinding")
    if (
        at_binding is not None
        and ("#bind" in kernel_code or "@KERNEL" in kernel_code)
        and not bool(at_binding.eval())
    ):
        at_binding.set(True)

    spare_parms, restored_values = _hcm_opencl_sync_controls(
        node, bindings, preserve_values
    )
    restored_connections = []
    dropped_connections = []
    if context == "dop":
        _hcm_opencl_sync_dop_rows(node, bindings)
        input_summary = []
        output_summary = []
    else:
        _hcm_opencl_sync_standard_rows(node, bindings, context)
        if context == "cop":
            desired_inputs = _hcm_opencl_desired_signature(bindings, False)
            desired_outputs = _hcm_opencl_desired_signature(bindings, True)
            connections = _hcm_opencl_capture_connections(node) if not bindings_only else []
            if not bindings_only:
                _hcm_opencl_sync_cop_signature(node, desired_inputs, desired_outputs)
                restored_connections, dropped_connections = _hcm_opencl_restore_connections(
                    node, desired_inputs, connections
                )
                input_summary = [
                    {"name": item["name"], "type": item["type"], "optional": bool(item["optional"])}
                    for item in desired_inputs
                ]
                output_summary = [
                    {"name": item["name"], "type": item["type"]}
                    for item in desired_outputs
                ]
            else:
                input_summary = _hcm_opencl_existing_signature(node, False)
                output_summary = _hcm_opencl_existing_signature(node, True)
        else:
            input_summary = []
            output_summary = []
    if runover:
        runover_parm = node.parm("runover") or node.parm("options_runover")
        if runover_parm is not None:
            runover_parm.set(runover)
    _hcm_opencl_safe_cook(node)
    validation = _hcm_opencl_validate(node, True, False)
    disconnected = []
    if disconnect_invalid and context == "cop":
        for row in validation.get("inputs", []):
            if row.get("connected") and row.get("compatible") is False:
                index = int(row["index"])
                _hcm_opencl_disconnect(node, index)
                disconnected.append(index)
        if disconnected:
            _hcm_opencl_safe_cook(node)
            validation = _hcm_opencl_validate(node, True, False)
    compact = _hcm_opencl_compact(validation, bindings)
    compact.update(
        {
            "bindings_only": bindings_only,
            "disconnect_invalid": disconnect_invalid,
            "preserve_values": preserve_values,
            "disconnected_inputs": disconnected,
            "spare_parms": spare_parms,
            "restored_values": restored_values,
            "inputs": input_summary,
            "outputs": output_summary,
        }
    )
    if context == "cop":
        compact["restored_connections"] = restored_connections
        compact["dropped_connections"] = dropped_connections
    if details:
        compact["validation"] = validation
    return node, compact


def _hcm_opencl_validate(node_value, details, cook):
    node = _hcm_resolve_node(node_value)
    if not isinstance(details, bool):
        raise TypeError("details must be a boolean")
    if not isinstance(cook, bool):
        raise TypeError("cook must be a boolean")
    kernel_parm = node.parm("kernelcode")
    if kernel_parm is None:
        raise ValueError("Node is not an OpenCL node: " + node.path())
    kernel_code = str(kernel_parm.evalAsString())
    bindings = list(_hcm_hou.text.oclExtractBindings(kernel_code))
    if len(bindings) > _HCM_OPENCL_MAX_BINDINGS:
        raise ValueError(
            "Kernel contains more than {} OpenCL bindings".format(
                _HCM_OPENCL_MAX_BINDINGS
            )
        )
    bindings = _hcm_opencl_enrich_bvh(kernel_code, bindings)
    runover = str(_hcm_hou.text.oclExtractRunOver(kernel_code))
    _hcm_opencl_preflight_bvh(bindings)
    if cook:
        _hcm_opencl_safe_cook(node)
    context = _hcm_opencl_context(node)
    if context in ("sop", "dop"):
        validation = _hcm_opencl_row_validation(
            node, bindings, runover, context
        )
    else:
        validation = _hcm_opencl_cop_validation(node, bindings, runover)
    validation["accelerated_bindings"] = _hcm_opencl_accelerated(bindings)
    bad_references = [
        message
        for message in validation.get("warnings", [])
        if "Bad parameter reference" in message
    ]
    if bad_references:
        validation["ok"] = False
        validation["sync_required"] = True
        validation.setdefault("hints", []).append(
            "One or more OpenCL binding rows reference missing control parameters"
        )
    use_code = node.parm("usecode")
    if use_code is not None and not bool(use_code.eval()) and kernel_code:
        validation["ok"] = False
        validation["sync_required"] = True
        validation.setdefault("hints", []).append(
            "Kernel Code is populated but Use Code Snippet is disabled"
        )
    at_binding = node.parm("atbinding")
    if (
        at_binding is not None
        and ("#bind" in kernel_code or "@KERNEL" in kernel_code)
        and not bool(at_binding.eval())
    ):
        validation["ok"] = False
        validation["sync_required"] = True
        validation.setdefault("hints", []).append(
            "Kernel Code uses binding directives but Enable @-Binding is disabled"
        )
    return validation if details else _hcm_opencl_compact(validation, bindings)


class _HCMOpenCLService:
    def __init__(self, mutation_events):
        self._mutation_events = mutation_events

    def validate(self, node, details=False, cook=True):
        value = _hcm_opencl_validate(node, details, cook)
        if cook:
            self._mutation_events.append(
                {
                    "kind": "houdini.cook",
                    "helper": "ctx.opencl.validate",
                    "node_path": _hcm_resolve_node(node).path(),
                }
            )
        return value

    def sync(
        self,
        node,
        clear=False,
        bindings_only=False,
        preserve_values=True,
        disconnect_invalid=False,
        details=False,
    ):
        resolved = _hcm_resolve_node(node)
        event = {
            "kind": "opencl.interface_sync",
            "helper": "ctx.opencl.sync",
            "node_path": resolved.path(),
            "status": "started",
            "clear": clear,
            "bindings_only": bindings_only,
            "preserve_values": preserve_values,
            "disconnect_invalid": disconnect_invalid,
        }
        self._mutation_events.append(event)
        _, value = _hcm_opencl_sync(
            resolved,
            clear,
            bindings_only,
            preserve_values,
            disconnect_invalid,
            details,
        )
        event["status"] = "complete"
        event["context"] = value["context"]
        event["binding_count"] = value["binding_count"]
        return value
'''
