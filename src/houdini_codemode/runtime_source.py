"""Versioned Python source installed into Houdini over RPyC."""

from __future__ import annotations

import hashlib

from .runtime_artifact_source import ARTIFACT_SOURCE
from .runtime_cop_file_source import COP_FILE_SOURCE
from .runtime_cop_source import COP_SOURCE
from .runtime_geometry_source import GEOMETRY_SOURCE
from .runtime_hda_source import HDA_SOURCE
from .runtime_hda_package_source import HDA_PACKAGE_SOURCE
from .runtime_hda_promotion_apply_source import HDA_PROMOTION_APPLY_SOURCE
from .runtime_hda_promotion_source import HDA_PROMOTION_SOURCE
from .runtime_hda_reference_source import HDA_REFERENCE_SOURCE
from .runtime_hda_update_source import HDA_UPDATE_SOURCE
from .runtime_help_source import HELP_SOURCE
from .runtime_lop_source import LOP_SOURCE
from .runtime_opencl_source import OPENCL_SOURCE
from .runtime_parm_reference_source import PARM_REFERENCE_SOURCE
from .runtime_python_source import PYTHON_SOURCE
from .runtime_wrangle_source import WRANGLE_SOURCE


RUNTIME_SOURCE = r'''
import builtins as _hcm_builtins
from collections import deque as _hcm_deque
import contextlib as _hcm_contextlib
import json as _hcm_json
import math as _hcm_math
import threading as _hcm_threading
import time as _hcm_time
import traceback as _hcm_traceback_module

import hdefereval as _hcm_hdefereval
import hou as _hcm_hou


_HCM_PROTOCOL_VERSION = "0.1"
_HCM_RUNTIME_VERSION = "0.2"
_HCM_MAX_SOURCE_BYTES = 256 * 1024
_HCM_MAX_LOG_BYTES = 256 * 1024
_HCM_MAX_RESULT_BYTES = 1024 * 1024
_HCM_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_HCM_MAX_STRING_BYTES = 256 * 1024
_HCM_MAX_CONTAINER_ITEMS = 10000
_HCM_MAX_TOTAL_ITEMS = 100000
_HCM_MAX_DEPTH = 64
_HCM_MAX_HELPER_NODES = 10000
_HCM_MAX_HELPER_PARMS = 10000
_HCM_MAX_HELPER_ITEMS = 1000
_HCM_MAX_HELPER_BOUNDARIES = 1000


class _HCMRequestError(ValueError):
    pass


class _HCMResultError(ValueError):
    pass


def _hcm_trim_utf8(value, maximum):
    text = value if isinstance(value, str) else str(value)
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= maximum:
        return text, False
    return encoded[:maximum].decode("utf-8", errors="ignore"), True


def _hcm_error_text(exc, maximum=4096):
    try:
        text = str(exc)
    except BaseException:
        text = "Error message could not be rendered"
    return _hcm_trim_utf8(text, maximum)[0]


def _hcm_error_type(exc):
    try:
        return type(exc).__name__
    except BaseException:
        return "Error"


def _hcm_compact_json(value):
    return _hcm_json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _hcm_int_limit(policy, name, default, minimum, maximum):
    value = policy.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise _HCMRequestError("policy.{} must be an integer".format(name))
    if value < minimum:
        raise _HCMRequestError("policy.{} must be at least {}".format(name, minimum))
    return min(value, maximum)


def _hcm_sanitize_request(request):
    if not isinstance(request, dict):
        raise _HCMRequestError("request must be a JSON object")
    if request.get("protocol_version") != _HCM_PROTOCOL_VERSION:
        raise _HCMRequestError("Unsupported protocol version")
    if request.get("expected_runtime_version") != _HCM_RUNTIME_VERSION:
        raise _HCMRequestError("Houdini runtime version mismatch")
    run_id = request.get("run_id")
    source = request.get("source")
    args = request.get("args")
    raw_policy = request.get("policy")
    if not isinstance(run_id, str) or not run_id or len(run_id) > 128:
        raise _HCMRequestError("run_id must be a non-empty bounded string")
    if not isinstance(source, str) or not source.strip():
        raise _HCMRequestError("source must be a non-empty string")
    if len(source.encode("utf-8")) > _HCM_MAX_SOURCE_BYTES:
        raise _HCMRequestError("source exceeds the runtime hard limit")
    if not isinstance(args, dict):
        raise _HCMRequestError("args must be a JSON object")
    if not isinstance(raw_policy, dict):
        raise _HCMRequestError("policy must be a JSON object")
    try:
        _hcm_compact_json(args)
    except BaseException as exc:
        raise _HCMRequestError("args contains invalid JSON data: " + _hcm_error_text(exc))
    undo_group = raw_policy.get("undo_group", True)
    if not isinstance(undo_group, bool):
        raise _HCMRequestError("policy.undo_group must be a boolean")
    label = raw_policy.get("label", "Houdini Code Mode")
    if not isinstance(label, str) or not label.strip():
        raise _HCMRequestError("policy.label must be a non-empty string")
    label, label_truncated = _hcm_trim_utf8(label.strip(), 128)
    if label_truncated:
        raise _HCMRequestError("policy.label must be at most 128 UTF-8 bytes")
    policy = {
        "max_log_bytes": _hcm_int_limit(
            raw_policy, "max_log_bytes", 32768, 0, _HCM_MAX_LOG_BYTES
        ),
        "max_result_bytes": _hcm_int_limit(
            raw_policy, "max_result_bytes", 262144, 256, _HCM_MAX_RESULT_BYTES
        ),
        "max_response_bytes": _hcm_int_limit(
            raw_policy, "max_response_bytes", 524288, 1024, _HCM_MAX_RESPONSE_BYTES
        ),
        "max_string_bytes": _hcm_int_limit(
            raw_policy, "max_string_bytes", 65536, 16, _HCM_MAX_STRING_BYTES
        ),
        "max_container_items": _hcm_int_limit(
            raw_policy, "max_container_items", 1000, 1, _HCM_MAX_CONTAINER_ITEMS
        ),
        "max_total_items": _hcm_int_limit(
            raw_policy, "max_total_items", 10000, 1, _HCM_MAX_TOTAL_ITEMS
        ),
        "max_depth": _hcm_int_limit(
            raw_policy, "max_depth", 12, 1, _HCM_MAX_DEPTH
        ),
        "undo_group": undo_group,
        "label": label,
    }
    return {
        "protocol_version": _HCM_PROTOCOL_VERSION,
        "run_id": run_id,
        "source": source,
        "args": args,
        "policy": policy,
    }


class _HCMCappedWriter:
    def __init__(self, maximum):
        self._maximum = maximum
        self._used = 0
        self._parts = []
        self.truncated = False
        self.encoding = "utf-8"

    def write(self, value):
        text = value if isinstance(value, str) else str(value)
        encoded = text.encode("utf-8", errors="replace")
        remaining = max(self._maximum - self._used, 0)
        if remaining:
            chunk = encoded[:remaining].decode("utf-8", errors="ignore")
            self._parts.append(chunk)
            self._used += len(chunk.encode("utf-8"))
        if len(encoded) > remaining:
            self.truncated = True
        return len(text)

    def flush(self):
        return None

    def isatty(self):
        return False

    def getvalue(self):
        return "".join(self._parts)


class _HCMResultCollector:
    def __init__(self):
        self.emitted = False
        self.value = None

    def emit(self, value):
        if self.emitted:
            raise _HCMResultError("result.emit() may be called at most once")
        self.emitted = True
        self.value = value


def _hcm_is_hou_type(value, name):
    candidate = getattr(_hcm_hou, name, None)
    if candidate is None:
        return False
    try:
        return isinstance(value, candidate)
    except TypeError:
        return False


def _hcm_node_summary(node):
    node_type = node.type()
    category = None
    try:
        category = node_type.category().name()
    except BaseException:
        pass
    flags = []
    for flag, method_name in (("display", "isDisplayFlagSet"), ("render", "isRenderFlagSet"), ("bypass", "isBypassed")):
        method = getattr(node, method_name, None)
        if method is not None:
            try:
                if method():
                    flags.append(flag)
            except BaseException:
                pass
    try:
        child_count = len(node.children())
    except BaseException:
        child_count = None
    try:
        input_count = len(node.inputs())
    except BaseException:
        input_count = None
    try:
        output_count = len(node.outputs())
    except BaseException:
        output_count = None
    return {
        "kind": "hou.Node",
        "path": node.path(),
        "name": node.name(),
        "type": node_type.name(),
        "category": category,
        "child_count": child_count,
        "input_count": input_count,
        "output_count": output_count,
        "flags": flags,
    }


def _hcm_parm_summary(parm):
    template_type = None
    try:
        template_type = parm.parmTemplate().type().name()
    except BaseException:
        pass
    tuple_name = None
    try:
        tuple_name = parm.tuple().name()
    except BaseException:
        pass
    return {
        "kind": "hou.Parm",
        "path": parm.path(),
        "name": parm.name(),
        "node_path": parm.node().path(),
        "tuple": tuple_name,
        "template_type": template_type,
    }


def _hcm_node_type_summary(node_type):
    category = None
    try:
        category = node_type.category().name()
    except BaseException:
        pass
    return {
        "kind": "hou.NodeType",
        "name": node_type.name(),
        "category": category,
    }


def _hcm_helper_int(value, name, default, minimum, maximum):
    if value is None:
        value = default
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("{} must be an integer".format(name))
    if value < minimum or value > maximum:
        raise ValueError(
            "{} must be between {} and {}".format(name, minimum, maximum)
        )
    return value


def _hcm_helper_choice(value, name, choices):
    if not isinstance(value, str) or value not in choices:
        raise ValueError(
            "{} must be one of: {}".format(name, ", ".join(choices))
        )
    return value


def _hcm_optional_text(value, name):
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("{} must be a string or None".format(name))
    return value or None


def _hcm_resolve_node(value, label="node"):
    if _hcm_is_hou_type(value, "Node"):
        return value
    if not isinstance(value, str) or not value:
        raise TypeError("{} must be a hou.Node or non-empty node path".format(label))
    node = _hcm_hou.node(value)
    if node is None:
        raise ValueError("Node not found: " + value)
    return node


def _hcm_relative_path(root_path, node_path):
    if node_path == root_path:
        return "."
    prefix = root_path.rstrip("/") + "/"
    if node_path.startswith(prefix):
        return node_path[len(prefix):]
    return node_path


def _hcm_safe_flag(node, method_name):
    method = getattr(node, method_name, None)
    if not callable(method):
        return False
    try:
        return bool(method())
    except BaseException:
        return False


def _hcm_flag_string(node):
    return "".join(
        [
            "d" if _hcm_safe_flag(node, "isDisplayFlagSet") else "",
            "r" if _hcm_safe_flag(node, "isRenderFlagSet") else "",
            "b" if _hcm_safe_flag(node, "isBypassed") else "",
        ]
    )


def _hcm_compact_node_row(root_path, node):
    try:
        inputs = len([item for item in node.inputs() if item is not None])
    except BaseException:
        inputs = None
    try:
        outputs = len(node.outputs())
    except BaseException:
        outputs = None
    try:
        children = len(node.children())
    except BaseException:
        children = None
    return [
        _hcm_relative_path(root_path, node.path()),
        node.type().name(),
        children,
        inputs,
        outputs,
        _hcm_flag_string(node),
    ]


def _hcm_table(columns, rows, total=None, truncated=False, limit=None):
    if total is None:
        total = len(rows)
    value = {
        "cols": list(columns),
        "rows": rows,
        "count": len(rows),
        "total": total,
        "truncated": bool(truncated or total > len(rows)),
    }
    if limit is not None:
        value["limit"] = limit
    return value


def _hcm_query_nodes(root, max_depth, max_nodes):
    queue = _hcm_deque([(root, 0)])
    nodes = []
    truncated = False
    while queue:
        if len(nodes) >= max_nodes:
            truncated = True
            break
        node, depth = queue.popleft()
        if depth > max_depth:
            continue
        nodes.append(node)
        if depth < max_depth:
            try:
                children = node.children()
            except BaseException:
                children = ()
            for child in children:
                queue.append((child, depth + 1))
    return nodes, truncated


def _hcm_find_nodes(root_value, type_name, category, name, max_depth, max_nodes, count_only):
    root = _hcm_resolve_node(root_value, "root")
    type_name = _hcm_optional_text(type_name, "type_name")
    category = _hcm_optional_text(category, "category")
    name = _hcm_optional_text(name, "name")
    max_depth = _hcm_helper_int(max_depth, "max_depth", 1, 0, _HCM_MAX_DEPTH)
    max_nodes = _hcm_helper_int(
        max_nodes, "max_nodes", 50, 1, _HCM_MAX_HELPER_NODES
    )
    if not isinstance(count_only, bool):
        raise TypeError("count_only must be a boolean")
    nodes, truncated = _hcm_query_nodes(root, max_depth, max_nodes)
    needle = name.lower() if name else None
    rows = []
    matches = 0
    root_path = root.path()
    for node in nodes[1:]:
        node_type = node.type()
        if type_name and node_type.name() != type_name:
            continue
        if category and node_type.category().name() != category:
            continue
        if needle and needle not in node.name().lower():
            continue
        matches += 1
        if not count_only:
            rows.append(_hcm_compact_node_row(root_path, node))
    result = {
        "root": root_path,
        "query": {
            key: value
            for key, value in (
                ("type", type_name),
                ("category", category),
                ("name", name),
            )
            if value is not None
        },
        "scope": {"max_depth": max_depth, "max_nodes": max_nodes},
        "count": matches,
        "visited_nodes": len(nodes),
        "truncated": truncated,
    }
    if not count_only:
        result["nodes"] = _hcm_table(
            ["p", "t", "cc", "in", "out", "f"],
            rows,
            total=matches,
            truncated=truncated,
            limit=max_nodes,
        )
    return result


def _hcm_connection_rows(node, method_name):
    method = getattr(node, method_name, None)
    if not callable(method):
        return []
    try:
        return list(method())
    except BaseException:
        return []


def _hcm_ordered_graph_neighbors(node, direction):
    candidates = []
    if direction in ("both", "upstream"):
        rows = []
        for connection in _hcm_connection_rows(node, "inputConnections"):
            other = connection.inputNode()
            if other is not None:
                rows.append(
                    (
                        int(connection.inputIndex()),
                        int(connection.outputIndex()),
                        other.path(),
                        other,
                    )
                )
        rows.sort(key=lambda item: (item[0], item[1], item[2]))
        candidates.extend(item[3] for item in rows)
    if direction in ("both", "downstream"):
        rows = []
        for connection in _hcm_connection_rows(node, "outputConnections"):
            other = connection.outputNode()
            if other is not None:
                rows.append(
                    (
                        int(connection.outputIndex()),
                        int(connection.inputIndex()),
                        other.path(),
                        other,
                    )
                )
        rows.sort(key=lambda item: (item[0], item[1], item[2]))
        candidates.extend(item[3] for item in rows)
    result = []
    seen = set()
    for other in candidates:
        path = other.path()
        if path not in seen:
            seen.add(path)
            result.append(other)
    return result


def _hcm_neighbor_graph(node_value, direction, depth, max_nodes):
    root = _hcm_resolve_node(node_value)
    direction = _hcm_helper_choice(
        direction, "direction", ("both", "upstream", "downstream")
    )
    depth = _hcm_helper_int(depth, "depth", 1, 0, _HCM_MAX_DEPTH)
    max_nodes = _hcm_helper_int(
        max_nodes, "max_nodes", 50, 1, _HCM_MAX_HELPER_NODES
    )
    queue = _hcm_deque([(root, 0)])
    enqueued = {root.path()}
    nodes = []
    truncated = False
    while queue:
        node, current_depth = queue.popleft()
        nodes.append(node)
        if current_depth >= depth:
            continue
        for other in _hcm_ordered_graph_neighbors(node, direction):
            path = other.path()
            if path in enqueued:
                continue
            if len(enqueued) >= max_nodes:
                truncated = True
                continue
            enqueued.add(path)
            queue.append((other, current_depth + 1))
    index_by_path = {node.path(): index for index, node in enumerate(nodes)}
    parent_path = root.path().rsplit("/", 1)[0] or "/"
    node_rows = [
        [
            index,
            _hcm_relative_path(parent_path, node.path()),
            node.type().name(),
            _hcm_flag_string(node),
        ]
        for index, node in enumerate(nodes)
    ]
    edge_rows = set()
    for node in nodes:
        for connection in _hcm_connection_rows(node, "inputConnections"):
            source = connection.inputNode()
            destination = connection.outputNode()
            if source is None or destination is None:
                continue
            source_path = source.path()
            destination_path = destination.path()
            if source_path not in index_by_path or destination_path not in index_by_path:
                continue
            edge_rows.add(
                (
                    index_by_path[source_path],
                    int(connection.outputIndex()),
                    index_by_path[destination_path],
                    int(connection.inputIndex()),
                )
            )
    return {
        "root": root.path(),
        "direction": direction,
        "depth": depth,
        "nodes": _hcm_table(
            ["id", "p", "t", "f"],
            node_rows,
            truncated=truncated,
            limit=max_nodes,
        ),
        "edges": _hcm_table(
            ["src", "out", "dst", "in"],
            [list(row) for row in sorted(edge_rows)],
        ),
        "truncated": truncated,
        "max_nodes": max_nodes,
    }


def _hcm_network_nodes(root, max_depth, max_nodes):
    queue = _hcm_deque()
    try:
        children = sorted(root.children(), key=lambda item: item.path())
    except BaseException:
        children = []
    for child in children:
        queue.append((child, 1))
    nodes = []
    truncated = False
    while queue:
        if len(nodes) >= max_nodes:
            truncated = True
            break
        node, depth = queue.popleft()
        if depth > max_depth:
            continue
        nodes.append(node)
        if depth < max_depth:
            try:
                children = sorted(node.children(), key=lambda item: item.path())
            except BaseException:
                children = []
            for child in children:
                queue.append((child, depth + 1))
    return nodes, truncated


def _hcm_node_message_count(node, method_name):
    method = getattr(node, method_name, None)
    if not callable(method):
        return 0
    try:
        return len(method())
    except BaseException:
        return 0


def _hcm_is_native_network(node):
    method = getattr(node, "isNetwork", None)
    if not callable(method):
        return False
    try:
        if not method():
            return False
        definition = getattr(node.type(), "definition", None)
        return not callable(definition) or definition() is None
    except BaseException:
        return False


def _hcm_boundary_table(root_path, rows, limit):
    rows.sort(key=lambda row: row[0].lower())
    returned = rows[:limit]
    return _hcm_table(
        ["p", "t"], returned, total=len(rows), truncated=len(rows) > limit, limit=limit
    )


def _hcm_network_summary(root_value, max_depth, max_nodes, top_types, include_boundaries, boundary_limit):
    root = _hcm_resolve_node(root_value, "root")
    max_depth = _hcm_helper_int(max_depth, "max_depth", 1, 0, _HCM_MAX_DEPTH)
    max_nodes = _hcm_helper_int(
        max_nodes, "max_nodes", 10000, 1, _HCM_MAX_HELPER_NODES
    )
    top_types = _hcm_helper_int(top_types, "top_types", 20, 1, 1000)
    boundary_limit = _hcm_helper_int(
        boundary_limit,
        "boundary_limit",
        50,
        1,
        _HCM_MAX_HELPER_BOUNDARIES,
    )
    if not isinstance(include_boundaries, bool):
        raise TypeError("include_boundaries must be a boolean")
    nodes, truncated = _hcm_network_nodes(root, max_depth, max_nodes)
    type_counts = {}
    category_counts = {}
    counts = {
        "nodes": len(nodes),
        "subnets": 0,
        "bypassed": 0,
        "display": 0,
        "render": 0,
        "with_errors": 0,
        "with_warnings": 0,
    }
    for node in nodes:
        node_type = node.type()
        type_name = node_type.name()
        category_name = node_type.category().name()
        type_counts[type_name] = type_counts.get(type_name, 0) + 1
        category_counts[category_name] = category_counts.get(category_name, 0) + 1
        counts["subnets"] += int(_hcm_is_native_network(node))
        counts["bypassed"] += int(_hcm_safe_flag(node, "isBypassed"))
        counts["display"] += int(_hcm_safe_flag(node, "isDisplayFlagSet"))
        counts["render"] += int(_hcm_safe_flag(node, "isRenderFlagSet"))
        counts["with_errors"] += int(_hcm_node_message_count(node, "errors") > 0)
        counts["with_warnings"] += int(_hcm_node_message_count(node, "warnings") > 0)
    ordered_types = sorted(
        type_counts.items(), key=lambda item: (-item[1], item[0].lower())
    )
    result = {
        "root": root.path(),
        "scope": {"max_depth": max_depth, "max_nodes": max_nodes},
        "counts": counts,
        "type_histogram": [
            {"type": name, "count": count}
            for name, count in ordered_types[:top_types]
        ],
        "type_histogram_other": sum(
            count for _name, count in ordered_types[top_types:]
        ),
        "category_histogram": [
            {"category": name, "count": count}
            for name, count in sorted(
                category_counts.items(), key=lambda item: (-item[1], item[0].lower())
            )
        ],
        "truncated": truncated,
        "visited_nodes": len(nodes),
    }
    if include_boundaries:
        paths = {node.path() for node in nodes}
        boundary_rows = {
            "entry_nodes": [],
            "terminal_nodes": [],
            "branch_nodes": [],
            "fan_in_nodes": [],
        }
        for node in nodes:
            inputs = set()
            outputs = set()
            for connection in _hcm_connection_rows(node, "inputConnections"):
                other = connection.inputNode()
                if other is not None and other.path() in paths:
                    inputs.add(
                        (
                            other.path(),
                            int(connection.outputIndex()),
                            int(connection.inputIndex()),
                        )
                    )
            for connection in _hcm_connection_rows(node, "outputConnections"):
                other = connection.outputNode()
                if other is not None and other.path() in paths:
                    outputs.add(
                        (
                            other.path(),
                            int(connection.outputIndex()),
                            int(connection.inputIndex()),
                        )
                    )
            row = [_hcm_relative_path(root.path(), node.path()), node.type().name()]
            if not inputs:
                boundary_rows["entry_nodes"].append(row)
            if not outputs:
                boundary_rows["terminal_nodes"].append(row)
            if len(outputs) > 1:
                boundary_rows["branch_nodes"].append(row)
            if len(inputs) > 1:
                boundary_rows["fan_in_nodes"].append(row)
        result["boundaries"] = {
            name: _hcm_boundary_table(root.path(), rows, boundary_limit)
            for name, rows in boundary_rows.items()
        }
    return result


_HCM_SKIPPED_PARM_TEMPLATE_TYPES = {
    "Button",
    "Folder",
    "FolderSet",
    "Label",
    "Separator",
}


def _hcm_parm_members(parm):
    try:
        members = list(parm.tuple())
    except BaseException:
        members = [parm]
    return members or [parm]


def _hcm_parm_template_type(parm):
    return parm.parmTemplate().type().name()


def _hcm_parm_display_name(parm):
    members = _hcm_parm_members(parm)
    if len(members) > 1:
        try:
            return parm.tuple().name()
        except BaseException:
            pass
    return parm.name()


def _hcm_parm_type_label(parm):
    members = _hcm_parm_members(parm)
    base = _hcm_parm_template_type(parm)
    return "{}{}".format(base, len(members)) if len(members) > 1 else base


def _hcm_parm_is_default(parm):
    return all(bool(member.isAtDefault()) for member in _hcm_parm_members(parm))


def _hcm_expression_summary(parm, max_items):
    rows = []
    total = 0
    for member in _hcm_parm_members(parm):
        method = getattr(member, "keyframes", None)
        if not callable(method):
            continue
        try:
            keyframes = method()
        except BaseException:
            continue
        if not keyframes:
            continue
        total += 1
        if len(rows) >= max_items:
            continue
        try:
            text = member.expression()
        except BaseException:
            text = None
        try:
            language = str(member.expressionLanguage()).rsplit(".", 1)[-1]
        except BaseException:
            language = None
        rows.append({"parm": member.name(), "language": language, "text": text})
    return {
        "count": total,
        "items": rows,
        "truncated": total > len(rows),
    }


def _hcm_ramp_summary(parm, max_items):
    ramp = parm.eval()
    keys = list(ramp.keys())
    bases = [str(item).rsplit(".", 1)[-1].lower() for item in ramp.basis()]
    unique_bases = list(dict.fromkeys(bases))
    return {
        "kind": "ramp",
        "point_count": len(keys),
        "basis": unique_bases[:max_items],
        "basis_truncated": len(unique_bases) > max_items,
    }


def _hcm_parm_value(parm, mode, max_items):
    mode = _hcm_helper_choice(mode, "value_mode", ("none", "scalar", "summary", "full"))
    if mode == "none":
        return None
    template_type = _hcm_parm_template_type(parm)
    if template_type == "Ramp" and mode != "full":
        return _hcm_ramp_summary(parm, max_items)
    method = getattr(parm, "multiParmInstances", None)
    if callable(method):
        try:
            instances = list(method())
        except BaseException:
            instances = []
        if instances and mode != "full":
            return {"kind": "multiparm", "instance_count": len(instances)}
    value = parm.valueAsData()
    if mode == "full":
        return value
    if isinstance(value, str):
        if mode == "scalar" and len(value) <= 120:
            return value
        preview_limit = min(120, max_items * 20)
        return {
            "kind": "string",
            "length": len(value),
            "preview": value[:preview_limit],
            "truncated": len(value) > preview_limit,
        }
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        if mode == "scalar" and len(value) <= 4:
            return value
        return {
            "kind": "sequence",
            "item_count": len(value),
            "items": list(value[:max_items]),
            "truncated": len(value) > max_items,
        }
    if isinstance(value, dict):
        keys = list(value.keys())
        return {
            "kind": "mapping",
            "item_count": len(keys),
            "keys": keys[:max_items],
            "truncated": len(keys) > max_items,
        }
    return {"kind": template_type.lower(), "type": type(value).__name__}


def _hcm_parm_projection_item(parm, mode, max_items, display_name=None):
    item = {
        "p": display_name or _hcm_parm_display_name(parm),
        "status": "ok",
        "t": _hcm_parm_type_label(parm),
        "v": _hcm_parm_value(parm, mode, max_items),
        "default": _hcm_parm_is_default(parm),
    }
    if mode != "none":
        expressions = _hcm_expression_summary(parm, max_items)
        if expressions["count"]:
            item["expressions"] = expressions
    return item


def _hcm_error_projection(name, exc):
    return {
        "p": name,
        "status": "error",
        "error": {
            "type": _hcm_error_type(exc),
            "message": _hcm_error_text(exc),
        },
    }


def _hcm_discoverable_parms(node):
    parms = []
    errors = []
    seen = set()
    try:
        node_parms = node.parms()
    except BaseException as exc:
        raise RuntimeError(
            "Could not enumerate parms on {}: {}".format(node.path(), _hcm_error_text(exc))
        )
    for parm in node_parms:
        try:
            if _hcm_parm_template_type(parm) in _HCM_SKIPPED_PARM_TEMPLATE_TYPES:
                continue
            members = _hcm_parm_members(parm)
            key = members[0].path() if len(members) > 1 else parm.path()
            if key in seen:
                continue
            seen.add(key)
            parms.append(parm)
        except BaseException as exc:
            try:
                name = parm.name()
            except BaseException:
                name = "<unknown>"
            errors.append(_hcm_error_projection(name, exc))
    return parms, errors


def _hcm_parm_matches(parm, name, parm_type, non_default):
    if non_default and _hcm_parm_is_default(parm):
        return False
    if parm_type and _hcm_parm_type_label(parm) != parm_type:
        return False
    if name:
        needle = name.lower()
        names = [_hcm_parm_display_name(parm)] + [
            member.name() for member in _hcm_parm_members(parm)
        ]
        lowered = [item.lower() for item in names]
        if not (
            any(item == needle for item in lowered)
            or any(item.startswith(needle) for item in lowered)
            or (len(needle) >= 3 and any(needle in item for item in lowered))
        ):
            return False
    return True


def _hcm_parm_rows(node_value, name, parm_type, non_default, value_mode, max_parms, max_items):
    node = _hcm_resolve_node(node_value)
    name = _hcm_optional_text(name, "name")
    parm_type = _hcm_optional_text(parm_type, "parm_type")
    if not isinstance(non_default, bool):
        raise TypeError("non_default must be a boolean")
    value_mode = _hcm_helper_choice(
        value_mode, "value_mode", ("none", "scalar", "summary", "full")
    )
    max_parms = _hcm_helper_int(
        max_parms, "max_parms", 100, 1, _HCM_MAX_HELPER_PARMS
    )
    max_items = _hcm_helper_int(
        max_items, "max_items", 10, 1, _HCM_MAX_HELPER_ITEMS
    )
    parms, errors = _hcm_discoverable_parms(node)
    matches = []
    for parm in parms:
        try:
            if _hcm_parm_matches(parm, name, parm_type, non_default):
                matches.append(parm)
        except BaseException as exc:
            try:
                parm_name = parm.name()
            except BaseException:
                parm_name = "<unknown>"
            errors.append(_hcm_error_projection(parm_name, exc))
    rows = []
    for parm in matches[:max_parms]:
        display_name = _hcm_parm_display_name(parm)
        try:
            item = _hcm_parm_projection_item(
                parm, value_mode, max_items, display_name=display_name
            )
            value = item["v"]
            if item.get("expressions"):
                if isinstance(value, dict):
                    value = dict(value)
                    value["expressions"] = item["expressions"]
                else:
                    value = {
                        "kind": "evaluated_expression",
                        "value": value,
                        "expressions": item["expressions"],
                    }
            rows.append(
                [
                    item["p"],
                    item["t"],
                    value,
                    "" if item["default"] else "n",
                ]
            )
        except BaseException as exc:
            error = _hcm_error_projection(display_name, exc)
            errors.append(error)
            rows.append([display_name, None, {"kind": "unavailable", "error": error["error"]}, "e"])
    return {
        "node": node.path(),
        "query": {
            key: value
            for key, value in (
                ("name", name),
                ("type", parm_type),
                ("non_default", True if non_default else None),
            )
            if value is not None
        },
        "value_mode": value_mode,
        "cols": ["p", "t", "v", "f"],
        "rows": rows,
        "count": len(rows),
        "total": len(matches),
        "truncated": len(matches) > len(rows),
        "max_parms": max_parms,
        "errors": errors,
    }


def _hcm_project_parms(node_value, requested_names, value_mode, max_items):
    node = _hcm_resolve_node(node_value)
    if isinstance(requested_names, str) or not isinstance(requested_names, (list, tuple)):
        raise TypeError("names must be a list or tuple of parameter names")
    if len(requested_names) > _HCM_MAX_HELPER_PARMS:
        raise ValueError(
            "names may contain at most {} items".format(_HCM_MAX_HELPER_PARMS)
        )
    value_mode = _hcm_helper_choice(
        value_mode, "value_mode", ("none", "scalar", "summary", "full")
    )
    max_items = _hcm_helper_int(
        max_items, "max_items", 10, 1, _HCM_MAX_HELPER_ITEMS
    )
    items = []
    missing = []
    errors = []
    for requested_name in requested_names:
        if not isinstance(requested_name, str) or not requested_name:
            raise TypeError("every requested parameter name must be a non-empty string")
        parm = node.parm(requested_name)
        if parm is None:
            parm_tuple = node.parmTuple(requested_name)
            if parm_tuple is not None and len(parm_tuple):
                parm = parm_tuple[0]
        if parm is None:
            missing.append(requested_name)
            items.append({"p": requested_name, "status": "missing"})
            continue
        try:
            items.append(
                _hcm_parm_projection_item(
                    parm, value_mode, max_items, display_name=requested_name
                )
            )
        except BaseException as exc:
            item = _hcm_error_projection(requested_name, exc)
            errors.append(item)
            items.append(item)
    return {
        "node": node.path(),
        "value_mode": value_mode,
        "items": items,
        "missing": missing,
        "errors": errors,
        "counts": {
            "requested": len(requested_names),
            "ok": sum(1 for item in items if item["status"] == "ok"),
            "missing": len(missing),
            "errors": len(errors),
        },
    }


class _HCMNormalizationState:
    def __init__(self, policy):
        self.policy = policy
        self.active = set()
        self.total = 0
        self.truncations = []

    def touch(self):
        self.total += 1

    def truncate(self, path, reason, returned=None, available=None):
        if len(self.truncations) >= 100:
            return
        item = {"path": path, "reason": reason}
        if returned is not None:
            item["returned"] = returned
        if available is not None:
            item["available"] = available
        self.truncations.append(item)


def _hcm_normalize(value, state, path="$", depth=0):
    if depth > state.policy["max_depth"]:
        state.truncate(path, "max_depth")
        return {"$truncated": "max_depth"}
    state.touch()
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not _hcm_math.isfinite(value):
            raise _HCMResultError("Non-finite float at " + path)
        return value
    if isinstance(value, str):
        text, truncated = _hcm_trim_utf8(value, state.policy["max_string_bytes"])
        if truncated:
            state.truncate(path, "max_string_bytes")
        return text
    if _hcm_is_hou_type(value, "Node"):
        return _hcm_normalize(_hcm_node_summary(value), state, path, depth)
    if _hcm_is_hou_type(value, "Parm"):
        return _hcm_normalize(_hcm_parm_summary(value), state, path, depth)
    if _hcm_is_hou_type(value, "NodeType"):
        return _hcm_normalize(_hcm_node_type_summary(value), state, path, depth)
    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in state.active:
            raise _HCMResultError("Cycle detected at " + path)
        state.active.add(identity)
        try:
            available = len(value)
            maximum = min(available, state.policy["max_container_items"])
            result = []
            for index in range(maximum):
                if state.total >= state.policy["max_total_items"]:
                    state.truncate(path, "max_total_items", len(result), available)
                    break
                result.append(
                    _hcm_normalize(value[index], state, "{}[{}]".format(path, index), depth + 1)
                )
            if available > maximum:
                state.truncate(path, "max_container_items", maximum, available)
            return result
        finally:
            state.active.remove(identity)
    if isinstance(value, dict):
        identity = id(value)
        if identity in state.active:
            raise _HCMResultError("Cycle detected at " + path)
        state.active.add(identity)
        try:
            available = len(value)
            result = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= state.policy["max_container_items"]:
                    state.truncate(path, "max_container_items", len(result), available)
                    break
                if state.total >= state.policy["max_total_items"]:
                    state.truncate(path, "max_total_items", len(result), available)
                    break
                if not isinstance(key, str):
                    raise _HCMResultError("Dictionary key at {} must be a string".format(path))
                normalized_key, key_truncated = _hcm_trim_utf8(
                    key, state.policy["max_string_bytes"]
                )
                if key_truncated:
                    raise _HCMResultError("Dictionary key at {} is too large".format(path))
                result[normalized_key] = _hcm_normalize(
                    item,
                    state,
                    "{}.{}".format(path, normalized_key),
                    depth + 1,
                )
            return result
        finally:
            state.active.remove(identity)
    raise _HCMResultError(
        "Unsupported result type at {}: {}".format(path, type(value).__name__)
    )


def _hcm_hip_dirty():
    try:
        return bool(_hcm_hou.hipFile.hasUnsavedChanges())
    except BaseException:
        return None


def _hcm_houdini_info():
    version = None
    hip_file = None
    try:
        version = _hcm_hou.applicationVersionString()
    except BaseException:
        pass
    try:
        hip_file = _hcm_hou.hipFile.path()
    except BaseException:
        pass
    return {"version": version, "hip_file": hip_file}


class _HCMSessionService:
    def info(self):
        info = _hcm_houdini_info()
        info["hip_dirty"] = _hcm_hip_dirty()
        info["thread"] = _hcm_threading.current_thread().name
        return info


class _HCMNodeService:
    def summary(self, node):
        return _hcm_node_summary(_hcm_resolve_node(node))

    def find(
        self,
        root,
        type_name=None,
        category=None,
        name=None,
        max_depth=1,
        max_nodes=50,
        count_only=False,
    ):
        return _hcm_find_nodes(
            root,
            type_name,
            category,
            name,
            max_depth,
            max_nodes,
            count_only,
        )

    def list(self, root, max_depth=1, max_nodes=50, count_only=False):
        return _hcm_find_nodes(
            root, None, None, None, max_depth, max_nodes, count_only
        )

    def neighbors(self, node, direction="both", depth=1, max_nodes=50):
        return _hcm_neighbor_graph(node, direction, depth, max_nodes)

    def network_summary(
        self,
        root,
        max_depth=1,
        max_nodes=10000,
        top_types=20,
        include_boundaries=False,
        boundary_limit=50,
    ):
        return _hcm_network_summary(
            root,
            max_depth,
            max_nodes,
            top_types,
            include_boundaries,
            boundary_limit,
        )


class _HCMParmService:
    def list(
        self,
        node,
        name=None,
        parm_type=None,
        non_default=False,
        value_mode="summary",
        max_parms=100,
        max_items=10,
    ):
        return _hcm_parm_rows(
            node,
            name,
            parm_type,
            non_default,
            value_mode,
            max_parms,
            max_items,
        )

    def find(
        self,
        node,
        name,
        parm_type=None,
        non_default=False,
        value_mode="summary",
        max_parms=100,
        max_items=10,
    ):
        if not isinstance(name, str) or not name:
            raise TypeError("name must be a non-empty string")
        return _hcm_parm_rows(
            node,
            name,
            parm_type,
            non_default,
            value_mode,
            max_parms,
            max_items,
        )

    def project(self, node, names, value_mode="summary", max_items=10):
        return _hcm_project_parms(node, names, value_mode, max_items)


class _HCMContext:
    def __init__(self, mutation_events):
        self._mutation_events = mutation_events
        self.session = _HCMSessionService()
        self.nodes = _HCMNodeService()
        self.parms = _HCMParmService()
        self.parm_references = _HCMParmReferenceService()
        self.geometry = _HCMGeometryService()
        self.cop = _HCMCopService()
        self.cop_files = _HCMCopFileService(mutation_events)
        self.lop = _HCMLopService(mutation_events)
        self.hda = _HCMHdaService(mutation_events)
        self.opencl = _HCMOpenCLService(mutation_events)
        self.python = _HCMPythonService(mutation_events)
        self.wrangle = _HCMWrangleService(mutation_events)
        self.artifacts = _HCMArtifactService(mutation_events)
        self.help = _HCMHelpService()

    def capabilities(self, query=None, max_items=50):
        return self.help.list(query=query, max_items=max_items)


def _hcm_meta(
    request,
    start,
    truncations,
    dirty_before,
    dirty_after,
    result_bytes=None,
    mutation_events=None,
):
    meta = {
        "run_id": request["run_id"],
        "completion": "complete",
        "duration_ms": round((_hcm_time.perf_counter() - start) * 1000, 3),
        "protocol_version": _HCM_PROTOCOL_VERSION,
        "runtime_version": _HCM_RUNTIME_VERSION,
        "execution_model": "trusted-local-main-thread",
        "thread": _hcm_threading.current_thread().name,
        "truncations": truncations,
        "mutation": {
            "events": list(mutation_events or []),
            "direct_hom_tracking": "best_effort",
            "hip_dirty_before": dirty_before,
            "hip_dirty_after": dirty_after,
        },
        "houdini": _hcm_houdini_info(),
    }
    if result_bytes is not None:
        meta["result_bytes"] = result_bytes
    return meta


def _hcm_logs(stdout, stderr):
    return {
        "stdout": stdout.getvalue(),
        "stderr": stderr.getvalue(),
        "stdout_truncated": stdout.truncated,
        "stderr_truncated": stderr.truncated,
    }


def _hcm_failure(
    request,
    category,
    exc,
    start,
    stdout,
    stderr,
    dirty_before,
    truncations,
    mutation_events,
):
    dirty_after = _hcm_hip_dirty()
    try:
        traceback_text = _hcm_traceback_module.format_exc()
    except BaseException:
        traceback_text = ""
    traceback_text = _hcm_trim_utf8(traceback_text, 8192)[0]
    if stdout.truncated:
        truncations.append({"path": "$.logs.stdout", "reason": "max_log_bytes"})
    if stderr.truncated:
        truncations.append({"path": "$.logs.stderr", "reason": "max_log_bytes"})
    return {
        "ok": False,
        "error": {
            "category": category,
            "type": _hcm_error_type(exc),
            "message": _hcm_error_text(exc),
            "traceback": traceback_text,
        },
        "data": {"logs": _hcm_logs(stdout, stderr)},
        "meta": _hcm_meta(
            request,
            start,
            truncations,
            dirty_before,
            dirty_after,
            mutation_events=mutation_events,
        ),
    }


def _hcm_undo_context(policy):
    if not policy["undo_group"]:
        return _hcm_contextlib.nullcontext()
    return _hcm_hou.undos.group(policy["label"])


def _hcm_run_on_main(request):
    start = _hcm_time.perf_counter()
    policy = request["policy"]
    stdout = _HCMCappedWriter(policy["max_log_bytes"])
    stderr = _HCMCappedWriter(policy["max_log_bytes"])
    collector = _HCMResultCollector()
    mutation_events = []
    context = _HCMContext(mutation_events)
    dirty_before = _hcm_hip_dirty()
    truncations = []
    try:
        compiled = compile(request["source"], "<houdini-codemode>", "exec")
    except SyntaxError as exc:
        return _hcm_failure(
            request,
            "compile",
            exc,
            start,
            stdout,
            stderr,
            dirty_before,
            truncations,
            mutation_events,
        )
    globals_dict = {
        "__builtins__": _hcm_builtins,
        "__name__": "__houdini_codemode__",
        "hou": _hcm_hou,
        "ctx": context,
        "args": request["args"],
        "result": collector,
    }
    try:
        with _hcm_contextlib.redirect_stdout(stdout):
            with _hcm_contextlib.redirect_stderr(stderr):
                with _hcm_undo_context(policy):
                    exec(compiled, globals_dict, globals_dict)
    except _HCMResultError as exc:
        return _hcm_failure(
            request,
            "result",
            exc,
            start,
            stdout,
            stderr,
            dirty_before,
            truncations,
            mutation_events,
        )
    except BaseException as exc:
        return _hcm_failure(
            request,
            "execution",
            exc,
            start,
            stdout,
            stderr,
            dirty_before,
            truncations,
            mutation_events,
        )
    try:
        if collector.emitted:
            state = _HCMNormalizationState(policy)
            normalized = _hcm_normalize(collector.value, state)
            truncations.extend(state.truncations)
        else:
            normalized = None
        result_json = _hcm_compact_json(normalized)
        result_bytes = len(result_json.encode("utf-8"))
        if result_bytes > policy["max_result_bytes"]:
            raise _HCMResultError(
                "Normalized result uses {} bytes, exceeding the {}-byte result limit".format(
                    result_bytes, policy["max_result_bytes"]
                )
            )
    except BaseException as exc:
        return _hcm_failure(
            request,
            "result",
            exc,
            start,
            stdout,
            stderr,
            dirty_before,
            truncations,
            mutation_events,
        )
    if stdout.truncated:
        truncations.append({"path": "$.logs.stdout", "reason": "max_log_bytes"})
    if stderr.truncated:
        truncations.append({"path": "$.logs.stderr", "reason": "max_log_bytes"})
    dirty_after = _hcm_hip_dirty()
    return {
        "ok": True,
        "data": {
            "value": normalized,
            "emitted": collector.emitted,
            "logs": _hcm_logs(stdout, stderr),
        },
        "meta": _hcm_meta(
            request,
            start,
            truncations,
            dirty_before,
            dirty_after,
            result_bytes,
            mutation_events,
        ),
    }


def _hcm_minimal_error(run_id, category, error_type, message, completion):
    return {
        "ok": False,
        "error": {
            "category": category,
            "type": error_type,
            "message": _hcm_trim_utf8(message, 4096)[0],
        },
        "meta": {
            "run_id": run_id,
            "completion": completion,
            "protocol_version": _HCM_PROTOCOL_VERSION,
            "runtime_version": _HCM_RUNTIME_VERSION,
        },
    }


def _hcm_encode_response(response, maximum):
    try:
        payload = _hcm_compact_json(response)
    except BaseException as exc:
        payload = _hcm_compact_json(
            _hcm_minimal_error(
                response.get("meta", {}).get("run_id") if isinstance(response, dict) else None,
                "internal",
                _hcm_error_type(exc),
                "Failed to serialize the Houdini response: " + _hcm_error_text(exc),
                "unknown",
            )
        )
    size = len(payload.encode("utf-8"))
    if size <= maximum:
        return payload
    run_id = response.get("meta", {}).get("run_id") if isinstance(response, dict) else None
    return _hcm_compact_json(
        _hcm_minimal_error(
            run_id,
            "result",
            "ResponseTooLarge",
            "Houdini response used {} bytes, exceeding the {}-byte response limit".format(
                size, maximum
            ),
            "complete",
        )
    )


def _hcm_process_lock():
    lock = getattr(_hcm_hou.session, "_houdini_codemode_run_lock", None)
    if lock is None:
        lock = _hcm_threading.Lock()
        _hcm_hou.session._houdini_codemode_run_lock = lock
    return lock


def _houdini_codemode_execute_json(request_json):
    run_id = None
    try:
        raw_request = _hcm_json.loads(request_json)
        if isinstance(raw_request, dict):
            run_id = raw_request.get("run_id")
        request = _hcm_sanitize_request(raw_request)
    except BaseException as exc:
        response = _hcm_minimal_error(
            run_id,
            "validation",
            _hcm_error_type(exc),
            _hcm_error_text(exc),
            "not_started",
        )
        return _hcm_encode_response(response, 524288)

    maximum = request["policy"]["max_response_bytes"]
    lock = _hcm_process_lock()
    if not lock.acquire(False):
        response = _hcm_minimal_error(
            request["run_id"],
            "busy",
            "HoudiniRunBusy",
            "Another Code Mode program is already running in this Houdini process",
            "not_started",
        )
        return _hcm_encode_response(response, maximum)
    try:
        try:
            if _hcm_threading.current_thread() is _hcm_threading.main_thread():
                response = _hcm_run_on_main(request)
            else:
                response = _hcm_hdefereval.executeInMainThreadWithResult(
                    lambda: _hcm_run_on_main(request)
                )
        except BaseException as exc:
            response = _hcm_minimal_error(
                request["run_id"],
                "internal",
                _hcm_error_type(exc),
                "Main-thread execution failed: " + _hcm_error_text(exc),
                "unknown",
            )
    finally:
        lock.release()
    return _hcm_encode_response(response, maximum)
'''

RUNTIME_SOURCE += "\n" + OPENCL_SOURCE
RUNTIME_SOURCE += "\n" + PARM_REFERENCE_SOURCE
RUNTIME_SOURCE += "\n" + PYTHON_SOURCE
RUNTIME_SOURCE += "\n" + WRANGLE_SOURCE
RUNTIME_SOURCE += "\n" + ARTIFACT_SOURCE
RUNTIME_SOURCE += "\n" + GEOMETRY_SOURCE
RUNTIME_SOURCE += "\n" + COP_SOURCE
RUNTIME_SOURCE += "\n" + COP_FILE_SOURCE
RUNTIME_SOURCE += "\n" + LOP_SOURCE
RUNTIME_SOURCE += "\n" + HDA_SOURCE
RUNTIME_SOURCE += "\n" + HDA_REFERENCE_SOURCE
RUNTIME_SOURCE += "\n" + HDA_PROMOTION_SOURCE
RUNTIME_SOURCE += "\n" + HDA_UPDATE_SOURCE
RUNTIME_SOURCE += "\n" + HDA_PROMOTION_APPLY_SOURCE
RUNTIME_SOURCE += "\n" + HDA_PACKAGE_SOURCE
RUNTIME_SOURCE += "\n" + HELP_SOURCE
RUNTIME_SOURCE_HASH = hashlib.sha256(RUNTIME_SOURCE.encode("utf-8")).hexdigest()
