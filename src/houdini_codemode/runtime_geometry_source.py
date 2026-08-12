"""Houdini-side bounded geometry inspection extension source."""

from __future__ import annotations


GEOMETRY_SOURCE = r'''
_HCM_GEOMETRY_CLASSES = ("point", "prim", "vertex", "detail")
_HCM_GEOMETRY_ACCESSORS = {
    "point": ("pointAttribs", "findPointAttrib"),
    "prim": ("primAttribs", "findPrimAttrib"),
    "vertex": ("vertexAttribs", "findVertexAttrib"),
    "detail": ("globalAttribs", "findGlobalAttrib"),
}


def _hcm_geometry(node):
    resolved = _hcm_resolve_node(node)
    try:
        geometry = resolved.geometry()
    except BaseException as exc:
        raise ValueError(
            "Node does not provide cooked geometry: " + resolved.path()
        ) from exc
    if geometry is None:
        raise ValueError("Node does not provide cooked geometry: " + resolved.path())
    return resolved, geometry


def _hcm_geometry_class(value, allow_none=False):
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or value not in _HCM_GEOMETRY_CLASSES:
        raise ValueError(
            "attrib_class must be one of: " + ", ".join(_HCM_GEOMETRY_CLASSES)
        )
    return value


def _hcm_geometry_positive(value, name, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(name + " must be an integer")
    if value <= 0:
        raise ValueError(name + " must be positive")
    return min(value, maximum)


def _hcm_geometry_data_type(attrib):
    text = str(attrib.dataType())
    return text.rsplit(".", 1)[-1].lower()


def _hcm_geometry_attrib_definition(attrib, attrib_class):
    item = {
        "name": str(attrib.name()),
        "class": attrib_class,
        "size": int(attrib.size()),
        "data_type": _hcm_geometry_data_type(attrib),
    }
    method = getattr(attrib, "isArrayType", None)
    if callable(method):
        item["array"] = bool(method())
    return item


def _hcm_geometry_flags(attrib):
    method = getattr(attrib, "isArrayType", None)
    return "A" if callable(method) and bool(method()) else ""


def _hcm_geometry_count(geometry, attrib_class):
    if attrib_class == "point":
        return int(geometry.pointCount())
    if attrib_class == "prim":
        return int(geometry.primCount())
    if attrib_class == "vertex":
        return int(geometry.vertexCount())
    return 1


def _hcm_geometry_prim_type(prim):
    try:
        value = prim.type()
        return str(value.name() if hasattr(value, "name") else value)
    except BaseException:
        return type(prim).__name__


def _hcm_geometry_histogram(counts, maximum):
    rows = [[key, count] for key, count in counts.items()]
    rows.sort(key=lambda row: (-int(row[1]), str(row[0])))
    return {
        "count": len(rows),
        "cols": ["value", "count"],
        "rows": rows[:maximum],
        "truncated": len(rows) > maximum,
    }


def _hcm_geometry_find_attrib(geometry, attrib_class, name):
    if not isinstance(name, str) or not name:
        raise TypeError("name must be a non-empty string")
    find_name = _HCM_GEOMETRY_ACCESSORS[attrib_class][1]
    attrib = getattr(geometry, find_name)(name)
    if attrib is None:
        raise ValueError(
            "Attribute not found: class={} name={}".format(attrib_class, name)
        )
    return attrib


def _hcm_geometry_samples(geometry, attrib_class, limit):
    if attrib_class == "point":
        rows = []
        for index, item in enumerate(geometry.iterPoints()):
            rows.append((index, item))
            if len(rows) >= limit:
                break
        return rows
    if attrib_class == "prim":
        rows = []
        for index, item in enumerate(geometry.iterPrims()):
            rows.append((index, item))
            if len(rows) >= limit:
                break
        return rows
    if attrib_class == "vertex":
        rows = []
        index = 0
        for prim in geometry.iterPrims():
            for vertex in prim.vertices():
                rows.append((index, vertex))
                index += 1
                if len(rows) >= limit:
                    return rows
        return rows
    return [(0, geometry)]


def _hcm_geometry_element(geometry, attrib_class, index):
    if isinstance(index, bool) or not isinstance(index, int):
        raise TypeError("element must be an integer")
    if index < 0:
        raise ValueError("element must be non-negative")
    count = _hcm_geometry_count(geometry, attrib_class)
    if index >= count:
        raise ValueError(
            "{} element index out of range: {}".format(attrib_class, index)
        )
    if attrib_class == "point":
        for current, item in enumerate(geometry.iterPoints()):
            if current == index:
                return item
    elif attrib_class == "prim":
        for current, item in enumerate(geometry.iterPrims()):
            if current == index:
                return item
    elif attrib_class == "vertex":
        current = 0
        for prim in geometry.iterPrims():
            for item in prim.vertices():
                if current == index:
                    return item
                current += 1
    raise ValueError("Unable to resolve {} element {}".format(attrib_class, index))


class _HCMGeometryService:
    def summary(
        self,
        node,
        topology=False,
        max_prims=100000,
        max_histogram=20,
    ):
        if not isinstance(topology, bool):
            raise TypeError("topology must be a boolean")
        resolved, geometry = _hcm_geometry(node)
        prim_count = _hcm_geometry_count(geometry, "prim")
        result = {
            "node": resolved.path(),
            "counts": {
                "point": _hcm_geometry_count(geometry, "point"),
                "prim": prim_count,
                "vertex": _hcm_geometry_count(geometry, "vertex"),
            },
        }
        if not topology:
            return result
        max_prims = _hcm_geometry_positive(max_prims, "max_prims", 1000000)
        max_histogram = _hcm_geometry_positive(
            max_histogram, "max_histogram", 1000
        )
        prim_types = {}
        vertex_counts = {}
        scanned = 0
        for prim in geometry.iterPrims():
            if scanned >= max_prims:
                break
            type_name = _hcm_geometry_prim_type(prim)
            prim_types[type_name] = prim_types.get(type_name, 0) + 1
            vertex_count = len(prim.vertices())
            vertex_counts[vertex_count] = vertex_counts.get(vertex_count, 0) + 1
            scanned += 1
        result["prim_types"] = _hcm_geometry_histogram(prim_types, max_histogram)
        result["prim_vertex_counts"] = _hcm_geometry_histogram(
            vertex_counts, max_histogram
        )
        result["meta"] = {
            "topology": True,
            "max_prims": max_prims,
            "scanned_prims": scanned,
            "scan_truncated": prim_count > scanned,
            "max_histogram": max_histogram,
        }
        return result

    def attributes(self, node, attrib_class=None, max_attribs=100):
        attrib_class = _hcm_geometry_class(attrib_class, allow_none=True)
        maximum = _hcm_geometry_positive(max_attribs, "max_attribs", 10000)
        resolved, geometry = _hcm_geometry(node)
        classes = [attrib_class] if attrib_class else list(_HCM_GEOMETRY_CLASSES)
        groups = {}
        totals = {}
        total = 0
        returned = 0
        for current_class in classes:
            list_name = _HCM_GEOMETRY_ACCESSORS[current_class][0]
            attribs = list(getattr(geometry, list_name)())
            totals[current_class] = len(attribs)
            total += len(attribs)
            for attrib in attribs:
                if returned >= maximum:
                    continue
                data_type = _hcm_geometry_data_type(attrib)
                key = (current_class, data_type)
                group = groups.setdefault(
                    key,
                    {
                        "class": current_class,
                        "type": data_type,
                        "count": 0,
                        "cols": ["name", "size", "flags"],
                        "rows": [],
                    },
                )
                group["rows"].append(
                    [str(attrib.name()), int(attrib.size()), _hcm_geometry_flags(attrib)]
                )
                group["count"] += 1
                returned += 1
        return {
            "node": resolved.path(),
            "count": returned,
            "groups": list(groups.values()),
            "meta": {
                "limit": maximum,
                "returned": returned,
                "total": total,
                "total_by_class": totals,
                "truncated": total > returned,
            },
        }

    def get(self, node, name, attrib_class="point", element=None, limit=10):
        attrib_class = _hcm_geometry_class(attrib_class)
        maximum = _hcm_geometry_positive(limit, "limit", 1000)
        resolved, geometry = _hcm_geometry(node)
        attrib = _hcm_geometry_find_attrib(geometry, attrib_class, name)
        count = _hcm_geometry_count(geometry, attrib_class)
        result = {
            "node": resolved.path(),
            "attribute": _hcm_geometry_attrib_definition(attrib, attrib_class),
        }
        if attrib_class == "detail":
            if element is not None:
                raise ValueError("Detail attributes do not accept element")
            result["value"] = geometry.attribValue(attrib)
            return result
        if element is not None:
            item = _hcm_geometry_element(geometry, attrib_class, element)
            result["value"] = {"element": element, "value": item.attribValue(attrib)}
            return result
        sampled = _hcm_geometry_samples(geometry, attrib_class, maximum)
        result["values"] = [
            {"element": index, "value": item.attribValue(attrib)}
            for index, item in sampled
        ]
        result["meta"] = {
            "limit": maximum,
            "returned": len(sampled),
            "total_elements": count,
            "truncated": count > len(sampled),
        }
        return result
'''
