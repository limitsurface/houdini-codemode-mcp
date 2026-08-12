"""Houdini-side bounded Copernicus inspection extension source."""

from __future__ import annotations


COP_SOURCE = r'''
import math as _hcm_cop_math


def _hcm_cop_output_rows(node):
    names = list(node.outputNames())
    try:
        labels = list(node.outputLabels())
    except BaseException:
        labels = []
    try:
        data_types = [str(item) for item in node.outputDataTypes()]
    except BaseException:
        data_types = []
    return [
        {
            "index": index,
            "name": str(name),
            "label": str(labels[index]) if index < len(labels) else "",
            "data_type": str(data_types[index]) if index < len(data_types) else "",
        }
        for index, name in enumerate(names)
    ]


def _hcm_cop_output_index(node, output):
    rows = _hcm_cop_output_rows(node)
    if not rows:
        raise ValueError("Node has no Copernicus outputs: " + node.path())
    if output is None:
        return 0, rows
    if isinstance(output, bool):
        raise TypeError("output must be an integer, string, or null")
    if isinstance(output, int):
        index = output
    elif isinstance(output, str):
        try:
            index = int(output)
        except ValueError:
            matches = [
                row["index"]
                for row in rows
                if output in (row["name"], row["label"])
            ]
            if not matches:
                raise ValueError(
                    "Output not found on node {}: {}".format(node.path(), output)
                )
            index = matches[0]
    else:
        raise TypeError("output must be an integer, string, or null")
    if index < 0 or index >= len(rows):
        raise ValueError(
            "Output index out of range for {}: {}".format(node.path(), index)
        )
    return index, rows


def _hcm_cop_is_proxy(node):
    try:
        return str(node.type().name()) == "null"
    except BaseException:
        return True


def _hcm_cop_proxy(node, output_index):
    try:
        outputs = list(node.outputs())
    except BaseException:
        return None
    for child in outputs:
        if not _hcm_cop_is_proxy(child):
            continue
        try:
            connections = list(child.inputConnections())
        except BaseException:
            continue
        for connection in connections:
            source = connection.inputNode()
            if source is None or source.path() != node.path():
                continue
            if int(connection.outputIndex()) == output_index:
                return child
    return None


def _hcm_cop_first_input(node):
    try:
        connections = list(node.inputConnections())
    except BaseException:
        return None
    return connections[0] if connections else None


def _hcm_cop_layer_target(node, output):
    output_index, outputs = _hcm_cop_output_index(node, output)
    identity = {
        "source_node_path": node.path(),
        "output_index": output_index,
        "output_name": outputs[output_index]["name"],
        "output_label": outputs[output_index]["label"],
        "output_data_type": outputs[output_index]["data_type"],
    }
    if output is not None or len(outputs) > 1:
        if len(outputs) == 1 and output_index == 0:
            return node, output_index, identity, outputs
        proxy = _hcm_cop_proxy(node, output_index)
        return (proxy, 0, identity, outputs) if proxy is not None else (
            node,
            output_index,
            identity,
            outputs,
        )
    connection = _hcm_cop_first_input(node)
    if connection is not None and _hcm_cop_is_proxy(node):
        source = connection.inputNode()
        if source is not None:
            source_index = int(connection.outputIndex())
            source_rows = _hcm_cop_output_rows(source)
            if 0 <= source_index < len(source_rows):
                source_row = source_rows[source_index]
                identity = {
                    "source_node_path": source.path(),
                    "output_index": source_index,
                    "output_name": source_row["name"],
                    "output_label": source_row["label"],
                    "output_data_type": source_row["data_type"],
                }
                return node, 0, identity, source_rows
    return node, output_index, identity, outputs


def _hcm_cop_rect(rect):
    minimum = rect.min()
    maximum = rect.max()
    size = rect.size()
    return {
        "min_x": int(minimum[0]),
        "min_y": int(minimum[1]),
        "max_x": int(maximum[0]),
        "max_y": int(maximum[1]),
        "width": int(size[0]),
        "height": int(size[1]),
    }


def _hcm_cop_sequence(value):
    if isinstance(value, (list, tuple)):
        return list(value)
    method = getattr(value, "asTuple", None)
    if callable(method):
        return list(method())
    try:
        return list(value)
    except TypeError:
        return value


def _hcm_cop_layer_payload(layer):
    return {
        "resolution": {
            "buffer": list(layer.bufferResolution()),
            "data_window": _hcm_cop_rect(layer.dataWindow()),
            "display_window": _hcm_cop_rect(layer.displayWindow()),
            "pixel_scale": list(layer.pixelScale()),
            "pixel_aspect_ratio": float(layer.pixelAspectRatio()),
        },
        "channel_count": int(layer.channelCount()),
        "storage": {
            "type": str(layer.storageType()),
            "border": str(layer.border()),
            "type_info": str(layer.typeInfo()),
            "is_constant": bool(layer.isConstant()),
            "on_cpu": bool(layer.onCPU()),
            "on_gpu": bool(layer.onGPU()),
            "stores_integers": bool(layer.storesIntegers()),
        },
    }


def _hcm_cop_camera(layer):
    try:
        return {
            "camera_position": list(layer.cameraPosition()),
            "projection": str(layer.projection()),
            "focal_length": float(layer.focalLength()),
            "aperture": float(layer.aperture()),
            "clipping_range": list(layer.clippingRange()),
        }
    except BaseException as exc:
        return {
            "status": "unavailable",
            "error": _hcm_error_text(exc, 512),
        }


def _hcm_cop_points(points, maximum):
    if not isinstance(points, (list, tuple)):
        raise TypeError("points must be a list")
    if len(points) > maximum:
        raise ValueError(
            "points contains {} items, exceeding the {}-point limit".format(
                len(points), maximum
            )
        )
    result = []
    for index, item in enumerate(points):
        if isinstance(item, dict) and "x" in item and "y" in item:
            x, y = item["x"], item["y"]
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            x, y = item
        else:
            raise ValueError(
                "points[{}] must contain x and y coordinates".format(index)
            )
        if isinstance(x, bool) or not isinstance(x, int):
            raise TypeError("points[{}].x must be an integer".format(index))
        if isinstance(y, bool) or not isinstance(y, int):
            raise TypeError("points[{}].y must be an integer".format(index))
        result.append((x, y))
    return result


def _hcm_cop_sample(layer, x, y):
    position = layer.pixelToBuffer((x, y))
    buffer_x = _hcm_cop_math.floor(position[0] + 0.5)
    buffer_y = _hcm_cop_math.floor(position[1] + 0.5)
    width, height = layer.bufferResolution()
    if not (0 <= buffer_x < width and 0 <= buffer_y < height):
        raise ValueError("Point is outside the layer buffer: ({}, {})".format(x, y))
    return {
        "x": x,
        "y": y,
        "buffer_x": int(buffer_x),
        "buffer_y": int(buffer_y),
        "value": _hcm_cop_sequence(layer.bufferIndex(int(buffer_x), int(buffer_y))),
    }


class _HCMCopService:
    def info(self, node, output=None):
        resolved = _hcm_resolve_node(node)
        if not callable(getattr(resolved, "layer", None)):
            raise ValueError(
                "Node does not provide Copernicus layer data: " + resolved.path()
            )
        layer_node, layer_index, identity, outputs = _hcm_cop_layer_target(
            resolved, output
        )
        layer = layer_node.layer(layer_index)
        return {
            "node_path": resolved.path(),
            "layer_node_path": layer_node.path(),
            **identity,
            "outputs": outputs,
            **_hcm_cop_layer_payload(layer),
            "camera": _hcm_cop_camera(layer),
        }

    def sample(self, node, points, output=None, max_points=64):
        maximum = _hcm_geometry_positive(max_points, "max_points", 1000)
        resolved = _hcm_resolve_node(node)
        if not callable(getattr(resolved, "layer", None)):
            raise ValueError(
                "Node does not provide Copernicus layer data: " + resolved.path()
            )
        requested = _hcm_cop_points(points, maximum)
        layer_node, layer_index, identity, outputs = _hcm_cop_layer_target(
            resolved, output
        )
        layer = layer_node.layer(layer_index)
        return {
            "node_path": resolved.path(),
            "layer_node_path": layer_node.path(),
            **identity,
            "outputs": outputs,
            **_hcm_cop_layer_payload(layer),
            "samples": [_hcm_cop_sample(layer, x, y) for x, y in requested],
            "meta": {"point_limit": maximum, "returned": len(requested)},
        }
'''
