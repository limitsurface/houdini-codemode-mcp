"""Narrow declarative authoring of a safe HDA parameter-interface subset."""

from __future__ import annotations


HDA_INTERFACE_SOURCE = r'''
import hashlib as _hcm_hda_interface_hashlib
import os as _hcm_hda_interface_os
import re as _hcm_hda_interface_re
import shutil as _hcm_hda_interface_shutil
import tempfile as _hcm_hda_interface_tempfile

_HCM_HDA_INTERFACE_SUFFIXES = (".hda", ".hdalc", ".hdanc", ".otl")
_HCM_HDA_INTERFACE_TYPES = ("float", "int", "string", "toggle", "menu")
_HCM_HDA_INTERFACE_NAME = _hcm_hda_interface_re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")

def _hcm_hda_interface_bool(value, name):
    if not isinstance(value, bool): raise TypeError(name + " must be a boolean")
    return value

def _hcm_hda_interface_limit(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int): raise TypeError(name + " must be an integer")
    if value < low or value > high: raise ValueError(name + " must be between {} and {}".format(low, high))
    return value

def _hcm_hda_interface_text(value, name, maximum=512, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and not value.strip()): raise TypeError(name + " must be a " + ("string" if allow_empty else "non-empty string"))
    if len(value.encode("utf-8")) > maximum: raise ValueError(name + " exceeds {} UTF-8 bytes".format(maximum))
    return value

def _hcm_hda_interface_path(value, name, library=True):
    value = _hcm_hda_interface_text(value, name, 4096)
    expand = getattr(_hcm_hou, "expandString", None)
    if callable(expand):
        try: value = expand(value)
        except BaseException: pass
    path = _hcm_hda_interface_os.path.realpath(_hcm_hda_interface_os.path.abspath(_hcm_hda_interface_os.path.normpath(_hcm_hda_interface_os.path.expandvars(value))))
    if library and _hcm_hda_interface_os.path.splitext(path)[1].lower() not in _HCM_HDA_INTERFACE_SUFFIXES: raise ValueError(name + " must use one of: " + ", ".join(_HCM_HDA_INTERFACE_SUFFIXES))
    return path

def _hcm_hda_interface_manifest(path):
    stat = _hcm_hda_interface_os.stat(path); digest = _hcm_hda_interface_hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""): digest.update(chunk)
    return {"path": path, "size": int(stat.st_size), "mtime_ns": int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1000000000))), "sha256": digest.hexdigest()}

def _hcm_hda_interface_under(path, root):
    try: return _hcm_hda_interface_os.path.commonpath((path, root)) == root
    except ValueError: return False

def _hcm_hda_interface_preflight(node, owned_library, require_unlocked=True):
    instance = _hcm_resolve_node(node, "node"); definition = instance.type().definition()
    if definition is None: raise ValueError("Node is not an HDA instance: " + str(instance.path()))
    if require_unlocked and bool(instance.isLockedHDA()): raise ValueError("Interface apply requires an unlocked sole HDA instance for the content checkpoint")
    current = str(definition.libraryFilePath())
    if not current or current == "Embedded": raise ValueError("Embedded HDA definitions are not supported")
    library, owned = _hcm_hda_interface_path(current, "definition library"), _hcm_hda_interface_path(owned_library, "owned_library")
    if _hcm_hda_interface_os.path.normcase(library) != _hcm_hda_interface_os.path.normcase(owned): raise ValueError("owned_library must exactly match the HDA definition library")
    expand = getattr(_hcm_hou, "expandString", None); hfs = ""
    if callable(expand):
        try: hfs = str(expand("$HFS"))
        except BaseException: pass
    if (not hfs or hfs == "$HFS"): hfs = _hcm_hda_interface_os.environ.get("HFS", "")
    if hfs and _hcm_hda_interface_under(library, _hcm_hda_interface_path(hfs, "HFS", False)): raise ValueError("owned_library must not be inside HFS / the Houdini installation")
    if not _hcm_hda_interface_os.path.isfile(library): raise ValueError("owned_library must be an existing regular HDA library file")
    method = getattr(instance.type(), "instances", None)
    if not callable(method): raise ValueError("Cannot verify a sole HDA instance")
    instances = list(method()); paths = [str(item.path()) for item in instances]
    if paths != [str(instance.path())]: raise ValueError("Interface apply requires the definition's sole instance; found {} instance(s)".format(len(paths)))
    method = getattr(getattr(_hcm_hou, "hda", None), "definitionsInFile", None)
    if not callable(method): raise ValueError("Cannot verify the owned library contains a sole definition")
    definitions = list(method(library)); type_name = str(instance.type().name()); types = [str(item.nodeType().name()) for item in definitions]
    if types != [type_name]: raise ValueError("Interface apply requires owned_library to contain exactly this one HDA definition")
    return instance, definition, library, paths, type_name

def _hcm_hda_interface_schema(items, max_items, max_depth):
    maximum = _hcm_hda_interface_limit(max_items, "max_items", 1, 100)
    _hcm_hda_interface_limit(max_depth, "max_depth", 1, 1)
    if not isinstance(items, (list, tuple)) or not items: raise TypeError("items must be a non-empty list of parameter specifications")
    if len(items) > maximum: raise ValueError("items exceeds max_items")
    out, names = [], set()
    for index, spec in enumerate(items):
        if not isinstance(spec, dict): raise TypeError("items[{}] must be an object".format(index))
        kind = spec.get("type")
        if kind not in _HCM_HDA_INTERFACE_TYPES: raise ValueError("items[{}].type unsupported; supported: {} (folders and other template types are intentionally unsupported)".format(index, ", ".join(_HCM_HDA_INTERFACE_TYPES)))
        name = _hcm_hda_interface_text(spec.get("name"), "items[{}].name".format(index), 128)
        if not _HCM_HDA_INTERFACE_NAME.match(name): raise ValueError("items[{}].name must be a Houdini-safe identifier".format(index))
        if name in names: raise ValueError("items contains duplicate name: " + name)
        names.add(name); label = _hcm_hda_interface_text(spec.get("label", name), "items[{}].label".format(index), 512)
        components = spec.get("components", 1)
        if kind in ("toggle", "menu"):
            if components != 1: raise ValueError(kind + " supports exactly one component")
        else: components = _hcm_hda_interface_limit(components, "items[{}].components".format(index), 1, 4)
        default = spec.get("default")
        if kind in ("float", "int"):
            if default is None: default = [0.0 if kind == "float" else 0] * components
            if not isinstance(default, (list, tuple)) or len(default) != components: raise ValueError("items[{}].default must have exactly {} components".format(index, components))
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in default): raise TypeError("numeric defaults must be numbers")
            default = tuple(float(value) if kind == "float" else int(value) for value in default)
        elif kind == "string":
            if default is None: default = [""] * components
            if not isinstance(default, (list, tuple)) or len(default) != components: raise ValueError("string default must have exactly {} components".format(components))
            default = tuple(_hcm_hda_interface_text(value, "string default", 4096, True) for value in default)
        elif kind == "toggle":
            if default is None: default = False
            if not isinstance(default, bool): raise TypeError("toggle default must be a boolean")
        else:
            items_value = spec.get("menu_items")
            if not isinstance(items_value, (list, tuple)) or not items_value or len(items_value) > 64: raise ValueError("menu_items must contain 1 to 64 tokens")
            items_value = tuple(_hcm_hda_interface_text(value, "menu token", 256) for value in items_value)
            if len(set(items_value)) != len(items_value): raise ValueError("menu_items must be unique")
            labels = spec.get("menu_labels", items_value)
            if not isinstance(labels, (list, tuple)) or len(labels) != len(items_value): raise ValueError("menu_labels must match menu_items")
            labels = tuple(_hcm_hda_interface_text(value, "menu label", 256) for value in labels)
            default = 0 if default is None else default
            if isinstance(default, bool) or not isinstance(default, int) or default < 0 or default >= len(items_value): raise ValueError("menu default must be a valid item index")
            spec = dict(spec); spec["menu_items"], spec["menu_labels"] = items_value, labels
        out.append({"name": name, "label": label, "type": kind, "components": components, "default": default, "menu_items": spec.get("menu_items"), "menu_labels": spec.get("menu_labels")})
    return out

def _hcm_hda_interface_template(spec):
    name, label, kind = spec["name"], spec["label"], spec["type"]
    if kind == "float": return _hcm_hou.FloatParmTemplate(name, label, spec["components"], default_value=spec["default"])
    if kind == "int": return _hcm_hou.IntParmTemplate(name, label, spec["components"], default_value=spec["default"])
    if kind == "string": return _hcm_hou.StringParmTemplate(name, label, spec["components"], default_value=spec["default"])
    # HOM's ToggleParmTemplate takes its default as the third positional
    # argument; unlike scalar numeric templates it does not reliably accept
    # the default_value keyword across the supported Houdini builds.
    if kind == "toggle": return _hcm_hou.ToggleParmTemplate(name, label, spec["default"])
    return _hcm_hou.MenuParmTemplate(name, label, spec["menu_items"], spec["menu_labels"], default_value=spec["default"])

class _HCMHdaInterfaceService:
    """Author only documented scalar/vector templates; folders are intentionally excluded."""
    def __init__(self, mutation_events=None): self._mutation_events = mutation_events if mutation_events is not None else []
    def plan(self, node, items, owned_library=None, conflict_policy="error", max_items=25, max_depth=1):
        if conflict_policy not in ("error", "replace"): raise ValueError("conflict_policy must be 'error' or 'replace'")
        if owned_library is None: raise TypeError("owned_library must be explicit")
        schema = _hcm_hda_interface_schema(items, max_items, max_depth)
        instance, definition, library, paths, type_name = _hcm_hda_interface_preflight(node, owned_library)
        group = definition.parmTemplateGroup(); conflicts = [spec["name"] for spec in schema if group.find(spec["name"]) is not None]
        blockers = (["existing parameter conflicts: " + ", ".join(conflicts)] if conflicts and conflict_policy == "error" else [])
        return {"operation": "hda.interface.plan", "dry_run": True, "ok": not blockers, "blockers": blockers, "node_path": str(instance.path()), "type_name": type_name, "library": {"path": library, "manifest": _hcm_hda_interface_manifest(library), "sole_instance_paths": paths, "sole_definition": True}, "items": schema, "conflict_policy": conflict_policy, "conflicts": conflicts, "future_events": [{"kind": "hda.interface.content_checkpoint", "method": "hou.HDADefinition.updateFromNode", "writes_library": "implicit_by_HOM"}, {"kind": "hda.interface.set_group", "method": "hou.HDADefinition.setParmTemplateGroup", "writes_library": "implicit_by_HOM"}, {"kind": "hda.interface.match_current", "method": "hou.OpNode.matchCurrentDefinition", "mutates_instance": True}], "expected_effects": {"current_call": {"writes_library": False, "installs_library": False, "saves_hip": False}, "apply": {"writes_library": True, "installs_library": False, "saves_hip": False, "may_affect_other_instances": False}}, "rollback_limits": ["No mutation occurs in plan.", "Apply checkpoints unlocked contents before matching, but HOM interface writes and matchCurrentDefinition are non-transactional."]}
    def apply(self, node, items, owned_library=None, conflict_policy="error", allow_library_write=False, create_backup=True, max_items=25, max_depth=1):
        _hcm_hda_interface_bool(allow_library_write, "allow_library_write"); _hcm_hda_interface_bool(create_backup, "create_backup")
        if not allow_library_write: raise ValueError("Interface apply writes the HDA library; set allow_library_write=True after reviewing the plan")
        plan = self.plan(node, items, owned_library, conflict_policy, max_items, max_depth)
        if not plan["ok"]: raise ValueError("Interface preflight failed: " + "; ".join(plan["blockers"]))
        instance, definition, library, paths, type_name = _hcm_hda_interface_preflight(node, owned_library)
        before = _hcm_hda_interface_manifest(library); events = [{"kind": "hda.interface.preflight", "sole_instance_paths": paths, "sole_definition": True}]; backup = None
        if create_backup:
            descriptor, path = _hcm_hda_interface_tempfile.mkstemp(prefix=".hcm-interface-backup-", suffix=".hda", dir=_hcm_hda_interface_os.path.dirname(library)); _hcm_hda_interface_os.close(descriptor); _hcm_hda_interface_shutil.copy2(library, path); backup = {"path": path, "manifest": _hcm_hda_interface_manifest(path)}
            if backup["manifest"]["sha256"] != before["sha256"]: raise RuntimeError("Interface backup verification failed")
            events.append({"kind": "hda.interface.backup", "path": path, "manifest": backup["manifest"]})
        checkpoint = {"kind": "hda.interface.content_checkpoint", "status": "started", "library_write": "implicit_by_HOM"}; events.append(checkpoint)
        try: definition.updateFromNode(instance); checkpoint["status"] = "complete"
        except BaseException: checkpoint["status"] = "error"; self._mutation_events.extend(events); raise
        group = definition.parmTemplateGroup()
        for spec in plan["items"]:
            template = _hcm_hda_interface_template(spec)
            if group.find(spec["name"]) is None: group.append(template)
            else: group.replace(spec["name"], template)
        changed = {"kind": "hda.interface.set_group", "status": "started", "items": len(plan["items"]), "conflict_policy": conflict_policy, "create_backup": create_backup, "library_write": "implicit_by_HOM"}; events.append(changed)
        try: definition.setParmTemplateGroup(group, rename_conflicting_parms=False, create_backup=create_backup); changed["status"] = "complete"
        except BaseException: changed["status"] = "error"; self._mutation_events.extend(events); raise
        matched = {"kind": "hda.interface.match_current", "status": "started", "node_path": str(instance.path())}; events.append(matched)
        try: instance.matchCurrentDefinition(); matched["status"] = "complete"
        except BaseException: matched["status"] = "error"; self._mutation_events.extend(events); raise
        after = _hcm_hda_interface_manifest(library); self._mutation_events.extend(events)
        return {"operation": "hda.interface.apply", "ok": True, "node_path": str(instance.path()), "type_name": type_name, "items": plan["items"], "conflict_policy": conflict_policy, "library": {"before": before, "after": after, "backup": backup, "update_from_node_called": True, "hda_definition_save_called": False, "install_called": False, "hip_save_called": False}, "events": events, "rollback_limits": "Non-transactional: the content checkpoint, interface mutation, and matchCurrentDefinition cannot be atomically reversed. The optional backup is not automatically restored because it cannot reliably synchronize the loaded definition."}

    def plan_defaults_from_current(self, node, names, owned_library=None, max_items=25, max_components=4):
        if owned_library is None: raise TypeError("owned_library must be explicit")
        maximum = _hcm_hda_interface_limit(max_items, "max_items", 1, 100); components_limit = _hcm_hda_interface_limit(max_components, "max_components", 1, 4)
        if not isinstance(names, (list, tuple)) or not names: raise TypeError("names must be an explicit non-empty list of parameter tuple names")
        if len(names) > maximum: raise ValueError("names exceeds max_items")
        names = [_hcm_hda_interface_text(name, "names[]", 128) for name in names]
        if len(set(names)) != len(names): raise ValueError("names must be unique")
        instance, definition, library, paths, type_name = _hcm_hda_interface_preflight(node, owned_library)
        group, rows = definition.parmTemplateGroup(), []
        for name in names:
            template, parm_tuple = group.find(name), instance.parmTuple(name)
            if template is None or parm_tuple is None: raise ValueError("Published parameter tuple not found: " + name)
            kind = str(template.type().name())
            if kind not in ("Float", "Int", "String", "Toggle", "Menu"): raise ValueError("Unsupported default-capture template type for {}: {}".format(name, kind))
            count = int(template.numComponents())
            if count < 1 or count > components_limit: raise ValueError("Parameter component count is outside max_components: " + name)
            if kind in ("Toggle", "Menu") and count != 1: raise ValueError(kind + " default capture requires one component: " + name)
            if kind == "Menu":
                generator = getattr(template, "itemGeneratorScript", None)
                if not callable(generator) or generator(): raise ValueError("Dynamic or unverifiable menu defaults are unsupported: " + name)
            values = tuple(parm_tuple.eval())
            if len(values) != count: raise ValueError("Current value component count changed for: " + name)
            for component in parm_tuple:
                expression = getattr(component, "expression", None)
                if callable(expression):
                    try: expression()
                    except BaseException: pass
                    else: raise ValueError("Expression-driven current defaults are unsupported: " + name)
            if kind == "Float" and any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values): raise TypeError("Float current value is invalid: " + name)
            if kind == "Int" and any(isinstance(value, bool) or not isinstance(value, int) for value in values): raise TypeError("Int current value is invalid: " + name)
            if kind == "String" and any(not isinstance(value, str) or len(value.encode("utf-8")) > 4096 for value in values): raise TypeError("String current value is invalid or too large: " + name)
            if kind == "Toggle" and values[0] not in (0, 1, False, True): raise TypeError("Toggle current value must be 0 or 1: " + name)
            if kind == "Menu" and (isinstance(values[0], bool) or not isinstance(values[0], int) or values[0] < 0 or values[0] >= len(template.menuItems())): raise TypeError("Menu current value is not a static menu index: " + name)
            rows.append({"name": name, "type": kind, "components": count, "current": list(values)})
        return {"operation": "hda.interface.defaults.plan", "dry_run": True, "ok": True, "node_path": str(instance.path()), "type_name": type_name, "library": {"path": library, "manifest": _hcm_hda_interface_manifest(library), "sole_instance_paths": paths, "sole_definition": True}, "items": rows, "future_events": [{"kind": "hda.interface.defaults.content_checkpoint", "method": "hou.HDADefinition.updateFromNode", "writes_library": "implicit_by_HOM"}, {"kind": "hda.interface.defaults.set_group", "method": "hou.HDADefinition.setParmTemplateGroup", "writes_library": "implicit_by_HOM"}, {"kind": "hda.interface.defaults.match_current", "method": "hou.OpNode.matchCurrentDefinition", "mutates_instance": True}], "rollback_limits": ["No mutation occurs in plan.", "Current values are sampled only for explicit scalar/vector supported tuples without expressions or dynamic menus."]}

    def set_defaults_from_current(self, node, names, owned_library=None, allow_library_write=False, create_backup=True, max_items=25, max_components=4):
        _hcm_hda_interface_bool(allow_library_write, "allow_library_write"); _hcm_hda_interface_bool(create_backup, "create_backup")
        if not allow_library_write: raise ValueError("Default capture writes the HDA library; set allow_library_write=True after reviewing the plan")
        plan = self.plan_defaults_from_current(node, names, owned_library, max_items, max_components)
        instance, definition, library, paths, type_name = _hcm_hda_interface_preflight(node, owned_library)
        before = _hcm_hda_interface_manifest(library); events = [{"kind": "hda.interface.defaults.preflight", "sole_instance_paths": paths, "sole_definition": True}]; backup = None
        if create_backup:
            descriptor, path = _hcm_hda_interface_tempfile.mkstemp(prefix=".hcm-defaults-backup-", suffix=".hda", dir=_hcm_hda_interface_os.path.dirname(library)); _hcm_hda_interface_os.close(descriptor); _hcm_hda_interface_shutil.copy2(library, path); backup = {"path": path, "manifest": _hcm_hda_interface_manifest(path)}
            if backup["manifest"]["sha256"] != before["sha256"]: raise RuntimeError("Default capture backup verification failed")
            events.append({"kind": "hda.interface.defaults.backup", "path": path, "manifest": backup["manifest"]})
        checkpoint = {"kind": "hda.interface.defaults.content_checkpoint", "status": "started", "library_write": "implicit_by_HOM"}; events.append(checkpoint)
        try: definition.updateFromNode(instance); checkpoint["status"] = "complete"
        except BaseException: checkpoint["status"] = "error"; self._mutation_events.extend(events); raise
        group = definition.parmTemplateGroup()
        for row in plan["items"]:
            template = group.find(row["name"]).clone(); value = row["current"][0] if row["type"] in ("Toggle", "Menu") else tuple(row["current"]); template.setDefaultValue(value); group.replace(row["name"], template)
        changed = {"kind": "hda.interface.defaults.set_group", "status": "started", "items": len(plan["items"]), "create_backup": create_backup, "library_write": "implicit_by_HOM"}; events.append(changed)
        try: definition.setParmTemplateGroup(group, rename_conflicting_parms=False, create_backup=create_backup); changed["status"] = "complete"
        except BaseException: changed["status"] = "error"; self._mutation_events.extend(events); raise
        matched = {"kind": "hda.interface.defaults.match_current", "status": "started", "node_path": str(instance.path())}; events.append(matched)
        try: instance.matchCurrentDefinition(); matched["status"] = "complete"
        except BaseException: matched["status"] = "error"; self._mutation_events.extend(events); raise
        after = _hcm_hda_interface_manifest(library); self._mutation_events.extend(events)
        return {"operation": "hda.interface.defaults.set_from_current", "ok": True, "node_path": str(instance.path()), "type_name": type_name, "items": plan["items"], "library": {"before": before, "after": after, "backup": backup, "update_from_node_called": True, "hda_definition_save_called": False, "install_called": False, "hip_save_called": False}, "events": events, "rollback_limits": "Non-transactional: checkpoint, default mutation, and matchCurrentDefinition cannot be atomically reversed; optional backup is not automatically restored into the loaded definition."}
'''
