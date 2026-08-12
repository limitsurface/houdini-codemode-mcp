"""Houdini-side bounded USD stage inspection extension source."""

from __future__ import annotations


LOP_SOURCE = r'''
def _hcm_lop_path_bucket(limit):
    return {"count": 0, "paths": [], "returned": 0, "truncated": False, "limit": limit}


def _hcm_lop_add_path(bucket, path):
    bucket["count"] += 1
    if len(bucket["paths"]) < bucket["limit"]:
        bucket["paths"].append(str(path))
        bucket["returned"] += 1
    else:
        bucket["truncated"] = True


def _hcm_lop_has_collection(prim):
    try:
        return any(
            str(schema).startswith("CollectionAPI:")
            for schema in prim.GetAppliedSchemas()
        )
    except BaseException:
        return False


def _hcm_lop_active_settings(stage, UsdRender):
    try:
        settings = UsdRender.Settings.GetStageRenderSettings(stage)
        if settings and settings.GetPrim().IsValid():
            return settings
    except BaseException:
        pass
    try:
        path = stage.GetMetadata("renderSettingsPrimPath")
        if path:
            settings = UsdRender.Settings.Get(stage, path)
            if settings and settings.GetPrim().IsValid():
                return settings
    except BaseException:
        pass
    return None


def _hcm_lop_output_count(node):
    counts = [1]
    for name in ("outputNames", "outputConnectors"):
        try:
            counts.append(len(getattr(node, name)()))
        except BaseException:
            pass
    return max(counts)


class _HCMLopService:
    def __init__(self, mutation_events):
        self._mutation_events = mutation_events

    def summary(
        self,
        node,
        output=0,
        max_depth=None,
        max_prims=10000,
        top_types=20,
        include_paths=False,
        path_limit=20,
    ):
        from pxr import Usd, UsdGeom, UsdLux, UsdRender, UsdShade

        resolved = _hcm_resolve_node(node)
        category = str(resolved.type().category().name())
        if category != "Lop":
            raise ValueError(
                "Node is not a LOP: {} (category: {})".format(
                    resolved.path(), category
                )
            )
        if isinstance(output, bool) or not isinstance(output, int):
            raise TypeError("output must be an integer")
        output_count = _hcm_lop_output_count(resolved)
        if output < 0 or output >= output_count:
            raise ValueError(
                "Output index out of range for {}: {} (output count: {})".format(
                    resolved.path(), output, output_count
                )
            )
        if max_depth is not None:
            if isinstance(max_depth, bool) or not isinstance(max_depth, int):
                raise TypeError("max_depth must be an integer or null")
            if max_depth < 0:
                raise ValueError("max_depth must be non-negative")
            max_depth = min(max_depth, 1000)
        maximum = _hcm_geometry_positive(max_prims, "max_prims", 1000000)
        type_limit = _hcm_geometry_positive(top_types, "top_types", 1000)
        path_maximum = _hcm_geometry_positive(path_limit, "path_limit", 1000)
        if not isinstance(include_paths, bool):
            raise TypeError("include_paths must be a boolean")

        try:
            cook_before = int(resolved.cookCount())
        except BaseException:
            cook_before = None
        try:
            needed_before = bool(resolved.needsToCook())
        except BaseException:
            needed_before = None
        acquire_started = _hcm_time.perf_counter()
        stage = resolved.stage(output_index=output)
        acquire_seconds = _hcm_time.perf_counter() - acquire_started
        try:
            cook_after = int(resolved.cookCount())
        except BaseException:
            cook_after = None
        if stage is None:
            raise ValueError("LOP node did not provide a stage: " + resolved.path())
        cooked = (
            cook_before is not None
            and cook_after is not None
            and cook_after > cook_before
        )
        if cooked:
            self._mutation_events.append(
                {
                    "kind": "houdini.cook",
                    "helper": "ctx.lop.summary",
                    "node_path": resolved.path(),
                    "cook_count_before": cook_before,
                    "cook_count_after": cook_after,
                }
            )

        path_keys = (
            "top_level",
            "cameras",
            "lights",
            "materials",
            "render_settings",
            "render_products",
            "prototypes",
            "composition_arcs",
        )
        paths = {key: _hcm_lop_path_bucket(path_maximum) for key in path_keys}
        counts = {
            "prims": 0,
            "active": 0,
            "inactive": 0,
            "instances": 0,
            "prototypes": 0,
            "materials": 0,
            "lights": 0,
            "cameras": 0,
            "render_settings": 0,
            "render_products": 0,
            "collections": 0,
        }
        references = 0
        payloads = 0
        type_counts = {}
        truncated = False

        traverse_started = _hcm_time.perf_counter()
        iterator = iter(Usd.PrimRange.Stage(stage, Usd.PrimAllPrimsPredicate))
        for prim in iterator:
            path = prim.GetPath()
            depth = int(path.pathElementCount)
            if max_depth is not None and depth > max_depth:
                iterator.PruneChildren()
                continue
            if counts["prims"] >= maximum:
                truncated = True
                break
            counts["prims"] += 1
            active = bool(prim.IsActive())
            counts["active" if active else "inactive"] += 1
            if prim.IsInstance():
                counts["instances"] += 1
            type_name = str(prim.GetTypeName()) or "<untyped>"
            type_counts[type_name] = type_counts.get(type_name, 0) + 1

            is_camera = bool(prim.IsA(UsdGeom.Camera))
            is_material = bool(prim.IsA(UsdShade.Material))
            is_render_settings = bool(prim.IsA(UsdRender.Settings))
            is_render_product = bool(prim.IsA(UsdRender.Product))
            try:
                is_light = bool(prim.HasAPI(UsdLux.LightAPI))
            except BaseException:
                is_light = False
            classifications = (
                ("cameras", is_camera),
                ("materials", is_material),
                ("lights", is_light),
                ("render_settings", is_render_settings),
                ("render_products", is_render_product),
            )
            for key, present in classifications:
                if present:
                    counts[key] += 1
            if _hcm_lop_has_collection(prim):
                counts["collections"] += 1

            has_reference = bool(prim.HasAuthoredReferences())
            has_payload = bool(prim.HasAuthoredPayloads())
            references += int(has_reference)
            payloads += int(has_payload)
            if include_paths:
                if depth == 1:
                    _hcm_lop_add_path(paths["top_level"], path)
                for key, present in classifications:
                    if present:
                        _hcm_lop_add_path(paths[key], path)
                if has_reference or has_payload:
                    _hcm_lop_add_path(paths["composition_arcs"], path)
            if max_depth is not None and depth >= max_depth:
                iterator.PruneChildren()

        prototypes = list(stage.GetPrototypes())
        counts["prototypes"] = len(prototypes)
        if include_paths:
            for prototype in prototypes:
                _hcm_lop_add_path(paths["prototypes"], prototype.GetPath())
        traverse_seconds = _hcm_time.perf_counter() - traverse_started

        ordered_types = sorted(
            type_counts.items(), key=lambda item: (-item[1], item[0])
        )
        shown_types = ordered_types[:type_limit]
        other_types = sum(count for _, count in ordered_types[type_limit:])
        default_prim = stage.GetDefaultPrim()
        default_path = (
            str(default_prim.GetPath())
            if default_prim and default_prim.IsValid()
            else None
        )
        active_settings = _hcm_lop_active_settings(stage, UsdRender)
        active_settings_path = None
        active_camera_path = None
        if active_settings is not None:
            active_settings_path = str(active_settings.GetPath())
            try:
                targets = active_settings.GetCameraRel().GetTargets()
                if targets:
                    active_camera_path = str(targets[0])
            except BaseException:
                pass
        root_layer = stage.GetRootLayer()
        result = {
            "node_path": resolved.path(),
            "output": output,
            "stage": {
                "default_prim": default_path,
                "up_axis": str(UsdGeom.GetStageUpAxis(stage)),
                "meters_per_unit": float(UsdGeom.GetStageMetersPerUnit(stage)),
                "time_codes_per_second": float(stage.GetTimeCodesPerSecond()),
                "root_layer": str(root_layer.identifier) if root_layer else None,
            },
            "counts": counts,
            "type_histogram": [
                {"type": name, "count": count} for name, count in shown_types
            ],
            "type_histogram_other": other_types,
            "active_render_settings": active_settings_path,
            "active_camera": active_camera_path,
            "composition": {
                "references": references,
                "payloads": payloads,
                "sublayers": len(root_layer.subLayerPaths) if root_layer else 0,
            },
            "timings": {
                "stage_acquisition_seconds": acquire_seconds,
                "traversal_seconds": traverse_seconds,
            },
            "cook": {
                "occurred": cooked,
                "needed_before": needed_before,
                "count_before": cook_before,
                "count_after": cook_after,
            },
            "meta": {
                "truncated": truncated,
                "counts_complete": not truncated,
                "max_depth": max_depth,
                "max_prims": maximum,
                "visited_prims": counts["prims"],
                "top_types": type_limit,
                "type_histogram_truncated": len(ordered_types) > type_limit,
                "included_paths": include_paths,
                "path_limit": path_maximum if include_paths else None,
                "instance_proxies": "excluded",
            },
        }
        if include_paths:
            result["paths"] = paths
        return result
'''
