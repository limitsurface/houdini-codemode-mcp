"""Bounded Houdini-side discovery and safe preset recipe application.

This source intentionally excludes recipe creation and tool/decoration
application.  Those surfaces either write an HDA library or can execute a
recipe script without a HOM switch to suppress it.  Node and parameter preset
application, in contrast, provides ``prescript`` and ``postscript`` switches;
the service always disables both and suppresses content/template application.
"""

from __future__ import annotations


RECIPE_SOURCE = r'''
import json as _hcm_recipe_json


_HCM_RECIPE_CATEGORY_ALIASES = {
    "tool": {"tool_recipe", "tab_tool_recipe"},
    "decoration": {"decoration_recipe"},
    "node-preset": {"node_preset_recipe"},
    "parm-preset": {"parm_preset_recipe"},
}
_HCM_RECIPE_SAFE_APPLY_CATEGORIES = {"node-preset", "parm-preset"}
_HCM_RECIPE_DEFAULT_BYTES = 262144
_HCM_RECIPE_MAX_BYTES = 1048576


def _hcm_recipe_limit(value, name, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(name + " must be an integer")
    if value < 1:
        raise ValueError(name + " must be positive")
    return min(value, maximum)


def _hcm_recipe_text(value, name, maximum=512):
    if not isinstance(value, str) or not value.strip():
        raise TypeError(name + " must be a non-empty string")
    value = value.strip()
    if len(value) > maximum:
        raise ValueError(name + " exceeds " + str(maximum) + " characters")
    return value


def _hcm_recipe_category_alias(category):
    for alias, values in _HCM_RECIPE_CATEGORY_ALIASES.items():
        if category in values:
            return alias
    return str(category)


def _hcm_recipe_category_filter(category):
    if category is None:
        return None
    category = _hcm_recipe_text(category, "category", 64)
    if category not in _HCM_RECIPE_CATEGORY_ALIASES:
        raise ValueError("category must be one of: " + ", ".join(sorted(_HCM_RECIPE_CATEGORY_ALIASES)))
    return _HCM_RECIPE_CATEGORY_ALIASES[category]


def _hcm_recipe_error_text(exc):
    formatter = globals().get("_hcm_error_text")
    if callable(formatter):
        return formatter(exc, 512)
    try:
        return str(exc)[:512]
    except BaseException:
        return exc.__class__.__name__


def _hcm_recipe_section_size(section):
    size = getattr(section, "size", None)
    if not callable(size):
        return None
    try:
        value = size()
    except BaseException:
        return None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _hcm_recipe_payload(node_type, max_bytes):
    definition = node_type.definition()
    if definition is None:
        return None, None, None
    sections = definition.sections()
    section = sections.get("data.recipe.json")
    if section is None:
        return definition, None, sections
    size = _hcm_recipe_section_size(section)
    if size is not None and size > max_bytes:
        raise ValueError("Recipe data exceeds max_recipe_bytes: " + str(size))
    contents = section.contents()
    if not isinstance(contents, str):
        raise ValueError("Recipe data is not text")
    if len(contents.encode("utf-8")) > max_bytes:
        raise ValueError("Recipe data exceeds max_recipe_bytes")
    try:
        payload = _hcm_recipe_json.loads(contents)
    except (TypeError, ValueError) as exc:
        raise ValueError("Recipe data is not valid JSON: " + _hcm_recipe_error_text(exc))
    if not isinstance(payload, dict):
        raise ValueError("Recipe data JSON must be an object")
    return definition, payload, sections


def _hcm_recipe_summary(key, node_type, definition, payload, sections):
    properties = payload.get("properties", {})
    if not isinstance(properties, dict):
        properties = {}
    tool = payload.get("tool", {})
    if not isinstance(tool, dict):
        tool = {}
    recipe_category = str(properties.get("recipe_category", ""))
    category = _hcm_recipe_category_alias(recipe_category)
    try:
        label = str(node_type.description())
    except BaseException:
        label = str(properties.get("label") or key)
    try:
        library = str(definition.libraryFilePath())
    except BaseException:
        library = None
    try:
        section_names = set(str(name) for name in sections.keys())
    except BaseException:
        section_names = set()
    data = payload.get("data")
    return {
        "key": str(key),
        "label": label,
        "category": category,
        "recipe_category": recipe_category,
        "visible": bool(properties.get("visible", True)),
        "library": library,
        "properties": {
            "name": str(properties.get("name", "")),
            "nodetype_category": str(properties.get("nodetype_category", "")),
            "nodetype_name": str(properties.get("nodetype_name", "")),
            "nodetype_patterns": [str(value) for value in properties.get("nodetype_patterns", ())][:100],
        },
        "tool": {
            "network_categories": [str(value) for value in tool.get("network_categories", ())][:100],
            "tab_submenus": [str(value) for value in tool.get("tab_submenus", ())][:100],
            "icon": str(tool.get("icon", "")),
        },
        "data": {
            "present": "data" in payload,
            "kind": type(data).__name__ if data is not None else None,
            "top_level_keys": (
                sorted(str(value) for value in data.keys())[:100]
                if isinstance(data, dict)
                else []
            ),
        },
        "scripts": {
            "prescript_present": "pre-script.recipe.py" in section_names,
            "postscript_present": "post-script.recipe.py" in section_names,
        },
    }


def _hcm_recipe_lookup(recipe_key, max_bytes):
    recipe_key = _hcm_recipe_text(recipe_key, "recipe_key", 512)
    node_type = _hcm_hou.dataNodeTypeCategory().nodeTypes().get(recipe_key)
    if node_type is None:
        raise ValueError("Recipe not found: " + recipe_key)
    definition, payload, sections = _hcm_recipe_payload(node_type, max_bytes)
    if payload is None:
        raise ValueError("Data node type is not a recipe: " + recipe_key)
    summary = _hcm_recipe_summary(recipe_key, node_type, definition, payload, sections)
    if not summary["recipe_category"]:
        raise ValueError("Recipe category is missing: " + recipe_key)
    return summary


def _hcm_recipe_result_parms(result, maximum):
    rows = []
    for parm in result.get("parms", ()):
        if len(rows) >= maximum:
            break
        try:
            rows.append(str(parm.path()))
        except BaseException:
            try:
                rows.append(str(parm.name()))
            except BaseException:
                rows.append("<unavailable>")
    try:
        total = len(result.get("parms", ()))
    except BaseException:
        total = len(rows)
    return {"count": total, "items": rows, "truncated": total > len(rows), "limit": maximum}


class _HCMRecipeService:
    """Capped recipe metadata discovery and script-suppressed preset apply."""

    def __init__(self, mutation_events=None):
        self._mutation_events = mutation_events if mutation_events is not None else []

    def list(
        self,
        category=None,
        visible_only=False,
        max_items=100,
        max_scan=1000,
        max_recipe_bytes=_HCM_RECIPE_DEFAULT_BYTES,
        max_errors=100,
    ):
        if not isinstance(visible_only, bool):
            raise TypeError("visible_only must be a boolean")
        accepted = _hcm_recipe_category_filter(category)
        item_limit = _hcm_recipe_limit(max_items, "max_items", 1000)
        scan_limit = _hcm_recipe_limit(max_scan, "max_scan", 10000)
        byte_limit = _hcm_recipe_limit(max_recipe_bytes, "max_recipe_bytes", _HCM_RECIPE_MAX_BYTES)
        error_limit = _hcm_recipe_limit(max_errors, "max_errors", 1000)
        try:
            node_types = _hcm_hou.dataNodeTypeCategory().nodeTypes()
        except BaseException as exc:
            raise RuntimeError("Unable to enumerate Data node types: " + _hcm_recipe_error_text(exc))
        rows = []
        errors = []
        scanned = 0
        for key in sorted(node_types, key=lambda value: str(value).lower()):
            if scanned >= scan_limit or len(rows) >= item_limit:
                break
            scanned += 1
            try:
                definition, payload, sections = _hcm_recipe_payload(node_types[key], byte_limit)
                if payload is None:
                    continue
                row = _hcm_recipe_summary(key, node_types[key], definition, payload, sections)
                if accepted is not None and row["recipe_category"] not in accepted:
                    continue
                if visible_only and not row["visible"]:
                    continue
                rows.append(row)
            except BaseException as exc:
                if len(errors) < error_limit:
                    errors.append({"key": str(key), "error": _hcm_recipe_error_text(exc)})
        return {
            "count": len(rows),
            "items": rows,
            "errors": errors,
            "meta": {
                "scanned": scanned,
                "limits": {"max_items": item_limit, "max_scan": scan_limit, "max_recipe_bytes": byte_limit, "max_errors": error_limit},
                "truncated": scanned >= scan_limit or len(rows) >= item_limit,
                "scan_limit_reached": scanned >= scan_limit,
                "item_limit_reached": len(rows) >= item_limit,
                "errors_truncated": len(errors) >= error_limit,
            },
        }

    def get(self, recipe_key, max_recipe_bytes=_HCM_RECIPE_DEFAULT_BYTES):
        byte_limit = _hcm_recipe_limit(max_recipe_bytes, "max_recipe_bytes", _HCM_RECIPE_MAX_BYTES)
        return _hcm_recipe_lookup(recipe_key, byte_limit)

    def apply_node_preset(self, recipe_key, node, max_items=100):
        maximum = _hcm_recipe_limit(max_items, "max_items", 1000)
        recipe = self.get(recipe_key)
        if recipe["category"] != "node-preset":
            raise ValueError("Recipe category must be node-preset, got: " + recipe["category"])
        target = _hcm_resolve_node(node, "node")
        result = _hcm_hou.data.applyNodePresetRecipe(
            recipe["key"], target, prescript=False, postscript=False,
            parms=True, parmtemplates=False, children=False, editables=False,
            skip_notes=True,
        )
        target_path = str(target.path())
        event = {
            "kind": "recipe.apply_node_preset",
            "helper": "ctx.recipes.apply_node_preset",
            "recipe": recipe["key"],
            "node_path": target_path,
            "scripts_skipped": True,
        }
        self._mutation_events.append(event)
        return {
            "recipe": recipe["key"], "category": "node-preset", "node": target_path,
            "parms": _hcm_recipe_result_parms(result, maximum),
            "safety": {
                "prescript": False, "postscript": False, "parmtemplates": False,
                "children": False, "editables": False, "skip_notes": True,
            },
        }

    def apply_parm_preset(self, recipe_key, parm, multiparm_operation="", multiparm_start_index=0):
        recipe = self.get(recipe_key)
        if recipe["category"] != "parm-preset":
            raise ValueError("Recipe category must be parm-preset, got: " + recipe["category"])
        if not isinstance(multiparm_operation, str) or multiparm_operation not in ("", "set", "set_from_index", "insert_at_index", "insert_first", "append"):
            raise ValueError("multiparm_operation is not supported")
        if isinstance(multiparm_start_index, bool) or not isinstance(multiparm_start_index, int) or multiparm_start_index < 0:
            raise ValueError("multiparm_start_index must be a non-negative integer")
        target = parm
        if isinstance(parm, str):
            target = _hcm_hou.parmTuple(parm) or _hcm_hou.parm(parm)
        if target is None:
            raise ValueError("Parameter not found: " + str(parm))
        result = _hcm_hou.data.applyParmPresetRecipe(
            recipe["key"], target, multiparm_operation=multiparm_operation,
            multiparm_start_index=multiparm_start_index, prescript=False, postscript=False,
        )
        try:
            target_path = str(target.path())
        except BaseException:
            target_path = str(parm)
        node = result.get("node")
        try:
            node_path = str(node.path()) if node is not None else None
        except BaseException:
            node_path = None
        self._mutation_events.append({
            "kind": "recipe.apply_parm_preset", "helper": "ctx.recipes.apply_parm_preset",
            "recipe": recipe["key"], "parm_path": target_path, "node_path": node_path,
            "scripts_skipped": True,
        })
        return {
            "recipe": recipe["key"], "category": "parm-preset", "parm": target_path,
            "node": node_path, "multiparm_operation": multiparm_operation,
            "multiparm_start_index": multiparm_start_index,
            "safety": {"prescript": False, "postscript": False},
        }
'''
