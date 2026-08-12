"""Narrow, structured HDA ``Tools.shelf`` mutation source.

This deliberately does not accept arbitrary shelf XML.  It writes only the
small H22 shelf-document shape used for an HDA tab-menu tool, with the viewer
and network contexts generated from validated structured inputs.
"""

from __future__ import annotations


HDA_TOOL_SOURCE = r'''
import hashlib as _hcm_hda_tool_hashlib
import os as _hcm_hda_tool_os
import shutil as _hcm_hda_tool_shutil
import tempfile as _hcm_hda_tool_tempfile
import xml.sax.saxutils as _hcm_hda_tool_xml_utils


_HCM_HDA_TOOL_SUFFIXES = (".hda", ".hdalc", ".hdanc", ".otl")
_HCM_HDA_TOOL_MAX_TEXT_BYTES = 512
_HCM_HDA_TOOL_CONTEXTS = {"SOP": ("SOP", "soptoolutils"), "COP": ("COP", "coptoolutils")}


def _hcm_hda_tool_bool(value, name):
    if not isinstance(value, bool): raise TypeError(name + " must be a boolean")
    return value


def _hcm_hda_tool_limit(value, name, ceiling):
    if isinstance(value, bool) or not isinstance(value, int): raise TypeError(name + " must be an integer")
    if value < 1 or value > ceiling: raise ValueError(name + " must be between 1 and " + str(ceiling))
    return value


def _hcm_hda_tool_text(value, name, maximum=_HCM_HDA_TOOL_MAX_TEXT_BYTES, optional=False):
    if value is None and optional: return None
    if not isinstance(value, str) or not value.strip(): raise TypeError(name + " must be a non-empty string" + (" or null" if optional else ""))
    value = value.strip()
    if len(value.encode("utf-8")) > maximum: raise ValueError(name + " exceeds " + str(maximum) + " UTF-8 bytes")
    return value


def _hcm_hda_tool_path(value, name, library=True):
    value = _hcm_hda_tool_text(value, name, 4096)
    expand = getattr(_hcm_hou, "expandString", None)
    if callable(expand):
        try: value = expand(value)
        except BaseException: pass
    path = _hcm_hda_tool_os.path.realpath(_hcm_hda_tool_os.path.abspath(_hcm_hda_tool_os.path.normpath(_hcm_hda_tool_os.path.expandvars(value))))
    if library and _hcm_hda_tool_os.path.splitext(path)[1].lower() not in _HCM_HDA_TOOL_SUFFIXES:
        raise ValueError(name + " must use one of: " + ", ".join(_HCM_HDA_TOOL_SUFFIXES))
    return path


def _hcm_hda_tool_under(path, root):
    try: return _hcm_hda_tool_os.path.commonpath((path, root)) == root
    except ValueError: return False


def _hcm_hda_tool_reject_hfs(path):
    expand = getattr(_hcm_hou, "expandString", None)
    hfs = ""
    if callable(expand):
        try: hfs = str(expand("$HFS"))
        except BaseException: hfs = ""
    if not hfs or hfs == "$HFS": hfs = _hcm_hda_tool_os.environ.get("HFS", "")
    if hfs and _hcm_hda_tool_under(path, _hcm_hda_tool_path(hfs, "HFS", library=False)):
        raise ValueError("owned_library must not be inside HFS / the Houdini installation")


def _hcm_hda_tool_manifest(path):
    stat = _hcm_hda_tool_os.stat(path); digest = _hcm_hda_tool_hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""): digest.update(chunk)
    return {"path": path, "size": int(stat.st_size), "mtime_ns": int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1000000000))), "sha256": digest.hexdigest()}


def _hcm_hda_tool_backup_path(library):
    directory, filename = _hcm_hda_tool_os.path.split(library); stem, extension = _hcm_hda_tool_os.path.splitext(filename)
    descriptor, path = _hcm_hda_tool_tempfile.mkstemp(prefix="." + stem + ".hcm-tool-backup-", suffix=extension, dir=directory)
    _hcm_hda_tool_os.close(descriptor); return path


def _hcm_hda_tool_definition(node):
    instance = _hcm_resolve_node(node, "node"); definition = instance.type().definition()
    if definition is None: raise ValueError("Node is not an HDA instance: " + str(instance.path()))
    return instance, definition


def _hcm_hda_tool_preflight(node, owned_library):
    instance, definition = _hcm_hda_tool_definition(node)
    current = str(definition.libraryFilePath())
    if not current or current == "Embedded": raise ValueError("Embedded HDA definitions are not supported")
    library = _hcm_hda_tool_path(current, "definition library"); owned = _hcm_hda_tool_path(owned_library, "owned_library")
    if _hcm_hda_tool_os.path.normcase(library) != _hcm_hda_tool_os.path.normcase(owned): raise ValueError("owned_library must exactly match the HDA definition library")
    _hcm_hda_tool_reject_hfs(library)
    if not _hcm_hda_tool_os.path.isfile(library): raise ValueError("owned_library must be an existing regular HDA library file")
    method = getattr(instance.type(), "instances", None)
    if not callable(method): raise ValueError("Cannot verify a sole HDA instance: node type does not expose instances()")
    try: instances = list(method())
    except BaseException as exc: raise ValueError("Cannot verify a sole HDA instance: " + str(exc))
    paths = [str(item.path()) for item in instances]
    if paths != [str(instance.path())]: raise ValueError("Tool mutation requires the definition's sole instance; found {} instance(s)".format(len(paths)))
    definitions_method = getattr(getattr(_hcm_hou, "hda", None), "definitionsInFile", None)
    if not callable(definitions_method): raise ValueError("Cannot verify the owned library contains a sole definition")
    try: definitions = list(definitions_method(library))
    except BaseException as exc: raise ValueError("Cannot inspect owned_library definitions: " + str(exc))
    type_name = str(instance.type().name()); types = [str(item.nodeType().name()) for item in definitions]
    if len(types) != 1 or types != [type_name]: raise ValueError("Tool mutation requires owned_library to contain exactly this one HDA definition")
    return instance, definition, library, paths, type_name


def _hcm_hda_tool_xml(submenu, context):
    net_type, utility = _HCM_HDA_TOOL_CONTEXTS[context]
    escaped = _hcm_hda_tool_xml_utils.escape(submenu)
    script = "import {0}\n{0}.genericTool(kwargs, '$HDA_NAME')".format(utility)
    return """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<shelfDocument>
  <tool name=\"$HDA_DEFAULT_TOOL\" label=\"$HDA_LABEL\" icon=\"$HDA_ICON\">
    <toolMenuContext name=\"viewer\"><contextNetType>{0}</contextNetType></toolMenuContext>
    <toolMenuContext name=\"network\"><contextOpType>$HDA_TABLE_AND_NAME</contextOpType></toolMenuContext>
    <toolSubmenu>{1}</toolSubmenu>
    <script scriptType=\"python\"><![CDATA[{2}]]></script>
  </tool>
</shelfDocument>
""".format(net_type, escaped, script)


def _hcm_hda_tool_inputs(submenu, context):
    submenu = _hcm_hda_tool_text(submenu, "submenu")
    context = _hcm_hda_tool_text(context, "context", 16).upper()
    if context not in _HCM_HDA_TOOL_CONTEXTS: raise ValueError("context must be one of: SOP, COP")
    return submenu, context


class _HCMHdaToolService:
    """Inspect and safely replace/remove a generated single HDA tab-menu tool."""
    def __init__(self, mutation_events=None): self._mutation_events = mutation_events if mutation_events is not None else []

    def inspect(self, node, max_items=100):
        maximum = _hcm_hda_tool_limit(max_items, "max_items", 1000)
        instance, definition = _hcm_hda_tool_definition(node)
        try: names = sorted(str(name) for name in definition.tools().keys())
        except BaseException: names = []
        try: section = definition.sections().get("Tools.shelf")
        except BaseException: section = None
        try: size = None if section is None else int(section.size())
        except BaseException: size = None
        return {"operation": "hda.tools.inspect", "node_path": str(instance.path()), "type_name": str(instance.type().name()), "tools": {"count": len(names), "items": names[:maximum], "truncated": len(names) > maximum, "limit": maximum}, "tools_shelf": {"present": section is not None, "size": size, "contents_read": False}, "effects": {"writes_library": False, "installs_library": False, "saves_hip": False}}

    def plan(self, node, action="set", submenu=None, context=None, owned_library=None):
        if action not in ("set", "remove"): raise ValueError("action must be 'set' or 'remove'")
        if owned_library is None: raise TypeError("owned_library must be an explicit non-empty string")
        if action == "set": submenu, context = _hcm_hda_tool_inputs(submenu, context)
        elif submenu is not None or context is not None: raise ValueError("submenu and context must be null when action='remove'")
        instance, definition, library, instances, type_name = _hcm_hda_tool_preflight(node, owned_library)
        try: existing = definition.sections().get("Tools.shelf")
        except BaseException as exc: raise ValueError("Cannot inspect Tools.shelf: " + str(exc))
        blockers = []
        if action == "remove" and existing is None: blockers.append("Tools.shelf is not present")
        return {"operation": "hda.tools.plan", "dry_run": True, "ok": not blockers, "blockers": blockers, "action": action, "node_path": str(instance.path()), "type_name": type_name, "library": {"path": library, "manifest": _hcm_hda_tool_manifest(library), "sole_instance_paths": instances, "sole_definition": True}, "tool": {"submenu": submenu, "context": context, "generated_xml_utf8_bytes": None if action == "remove" else len(_hcm_hda_tool_xml(submenu, context).encode("utf-8")), "existing_tools_shelf": existing is not None}, "future_events": [{"kind": "hda.tools.preflight", "mutates": False}, {"kind": "hda.definition.addSection" if action == "set" else "hda.definition.removeSection", "name": "Tools.shelf", "mutates_definition": True, "writes_library": "implicit_by_HOM"}], "expected_effects": {"current_call": {"writes_library": False, "installs_library": False, "saves_hip": False}, "apply": {"writes_library": True, "installs_library": False, "saves_hip": False, "may_affect_other_instances": False}}, "rollback_limits": ["No mutation occurs in plan.", "HOM Tools.shelf writes are non-transactional; an optional disk backup is for manual recovery, not automatic live-definition rollback."]}

    def set(self, node, submenu, context, owned_library=None, allow_library_write=False, create_backup=True):
        return self._apply(node, "set", submenu, context, owned_library, allow_library_write, create_backup)

    def remove(self, node, owned_library=None, allow_library_write=False, create_backup=True):
        return self._apply(node, "remove", None, None, owned_library, allow_library_write, create_backup)

    def _apply(self, node, action, submenu, context, owned_library, allow_library_write, create_backup):
        _hcm_hda_tool_bool(allow_library_write, "allow_library_write"); _hcm_hda_tool_bool(create_backup, "create_backup")
        if not allow_library_write: raise ValueError("Tool apply writes the HDA library; set allow_library_write=True after reviewing the plan")
        plan = self.plan(node, action, submenu, context, owned_library)
        if not plan["ok"]: raise ValueError("Tool preflight failed: " + "; ".join(plan["blockers"]))
        instance, definition, library, instances, type_name = _hcm_hda_tool_preflight(node, owned_library)
        before = _hcm_hda_tool_manifest(library); events = [{"kind": "hda.tools.preflight", "node_path": str(instance.path()), "library": library, "sole_instance_paths": instances, "sole_definition": True}]; backup = None
        if create_backup:
            path = _hcm_hda_tool_backup_path(library); _hcm_hda_tool_shutil.copy2(library, path); backup = {"path": path, "manifest": _hcm_hda_tool_manifest(path)}
            if backup["manifest"]["sha256"] != before["sha256"]: raise RuntimeError("HDA tool backup verification failed")
            events.append({"kind": "hda.tools.backup", "path": path, "manifest": backup["manifest"]})
        event = {"kind": "hda.definition.addSection" if action == "set" else "hda.definition.removeSection", "name": "Tools.shelf", "library_write": "implicit_by_HOM", "status": "started"}; events.append(event)
        try:
            if action == "set": definition.addSection("Tools.shelf", _hcm_hda_tool_xml(plan["tool"]["submenu"], plan["tool"]["context"]))
            else: definition.removeSection("Tools.shelf")
            event["status"] = "complete"
        except BaseException:
            event["status"] = "error"; self._mutation_events.extend(events); raise
        after = _hcm_hda_tool_manifest(library); self._mutation_events.extend(events)
        return {"operation": "hda.tools." + action, "ok": True, "action": action, "node_path": str(instance.path()), "type_name": type_name, "tool": plan["tool"], "library": {"before": before, "after": after, "backup": backup, "hda_definition_save_called": False, "install_called": False, "hip_save_called": False}, "events": events, "rollback_limits": "Non-transactional: Tools.shelf is changed immediately by HOM. The optional verified backup is not automatically restored because that cannot reliably synchronize the loaded definition."}
'''
