"""Narrow, explicit creation of one new externally stored HDA."""

from __future__ import annotations


HDA_CREATE_OWNED_SOURCE = r'''
import hashlib as _hcm_hda_create_hashlib
import os as _hcm_hda_create_os
import re as _hcm_hda_create_re

_HCM_HDA_CREATE_SUFFIXES = (".hda", ".hdalc", ".hdanc", ".otl")
_HCM_HDA_CREATE_TYPE = _hcm_hda_create_re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:::[A-Za-z][A-Za-z0-9_]*){1,3}$")

def _hcm_hda_create_text(value, name, maximum=512):
    if not isinstance(value, str) or not value.strip(): raise TypeError(name + " must be a non-empty string")
    value = value.strip()
    if len(value.encode("utf-8")) > maximum: raise ValueError(name + " exceeds {} UTF-8 bytes".format(maximum))
    return value

def _hcm_hda_create_bool(value, name):
    if not isinstance(value, bool): raise TypeError(name + " must be a boolean")
    return value

def _hcm_hda_create_inputs(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 64: raise ValueError(name + " must be an integer between 0 and 64")
    return value

def _hcm_hda_create_path(value):
    value = _hcm_hda_create_text(value, "destination_library", 4096)
    expand = getattr(_hcm_hou, "expandString", None)
    if callable(expand):
        try: value = expand(value)
        except BaseException: pass
    path = _hcm_hda_create_os.path.realpath(_hcm_hda_create_os.path.abspath(_hcm_hda_create_os.path.normpath(_hcm_hda_create_os.path.expandvars(value))))
    if _hcm_hda_create_os.path.splitext(path)[1].lower() not in _HCM_HDA_CREATE_SUFFIXES: raise ValueError("destination_library must use one of: " + ", ".join(_HCM_HDA_CREATE_SUFFIXES))
    return path

def _hcm_hda_create_manifest(path):
    if not _hcm_hda_create_os.path.exists(path): return {"exists": False, "path": path, "size": None, "mtime_ns": None, "sha256": None}
    stat = _hcm_hda_create_os.stat(path); digest = _hcm_hda_create_hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""): digest.update(chunk)
    return {"exists": True, "path": path, "size": int(stat.st_size), "mtime_ns": int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1000000000))), "sha256": digest.hexdigest()}

def _hcm_hda_create_under(path, root):
    try: return _hcm_hda_create_os.path.commonpath((path, root)) == root
    except ValueError: return False

def _hcm_hda_create_plan(node, type_name, label, destination_library, min_inputs, max_inputs):
    source = _hcm_resolve_node(node, "node")
    definition = source.type().definition()
    if definition is not None: raise ValueError("create_owned requires an explicit non-HDA source node")
    can_create = getattr(source, "canCreateDigitalAsset", None)
    if not callable(can_create) or not bool(can_create()): raise ValueError("Source node cannot create a digital asset")
    type_name = _hcm_hda_create_text(type_name, "type_name", 256)
    if not _HCM_HDA_CREATE_TYPE.match(type_name): raise ValueError("type_name must use a safe namespace::name form")
    label = _hcm_hda_create_text(label, "label")
    min_inputs, max_inputs = _hcm_hda_create_inputs(min_inputs, "min_inputs"), _hcm_hda_create_inputs(max_inputs, "max_inputs")
    if min_inputs > max_inputs: raise ValueError("min_inputs must not exceed max_inputs")
    destination = _hcm_hda_create_path(destination_library)
    parent = _hcm_hda_create_os.path.dirname(destination)
    if not _hcm_hda_create_os.path.isdir(parent): raise ValueError("destination_library parent directory must already exist; create_dirs is not supported")
    if _hcm_hda_create_os.path.exists(destination): raise FileExistsError("destination_library must be new; existing paths are refused")
    expand = getattr(_hcm_hou, "expandString", None); hfs = ""
    if callable(expand):
        try: hfs = str(expand("$HFS"))
        except BaseException: pass
    if (not hfs or hfs == "$HFS"): hfs = _hcm_hda_create_os.environ.get("HFS", "")
    if hfs and _hcm_hda_create_under(destination, _hcm_hda_create_os.path.realpath(_hcm_hda_create_os.path.abspath(hfs))): raise ValueError("destination_library must not be inside HFS / the Houdini installation")
    return source, type_name, label, destination, min_inputs, max_inputs

class _HCMHdaCreateOwnedService:
    """Create a new one-definition HDA library; it never overwrites or installs extras."""
    def __init__(self, mutation_events=None): self._mutation_events = mutation_events if mutation_events is not None else []
    def plan(self, node, type_name, label, destination_library, min_inputs=0, max_inputs=0):
        source, type_name, label, destination, minimum, maximum = _hcm_hda_create_plan(node, type_name, label, destination_library, min_inputs, max_inputs)
        return {"operation": "hda.create_owned.plan", "dry_run": True, "ok": True, "source": {"path": str(source.path()), "type_name": str(source.type().name()), "is_hda": False, "can_create_digital_asset": True}, "definition": {"type_name": type_name, "label": label, "min_inputs": minimum, "max_inputs": maximum, "source_interface": "not supported in v1", "structured_tool": "not supported in v1"}, "destination": {"path": destination, "manifest": _hcm_hda_create_manifest(destination), "parent_exists": True, "create_dirs": False, "overwrite": False}, "future_events": [{"kind": "hda.create_owned.createDigitalAsset", "method": "hou.OpNode.createDigitalAsset", "writes_library": True, "changes_source_node_type": True, "installs_library": "unavoidable_HOM_behavior"}], "expected_effects": {"current_call": {"writes_library": False, "installs_library": False, "saves_hip": False}, "apply": {"writes_library": True, "installs_library": True, "saves_hip": False, "changes_source_node_type": True}}, "rollback_limits": ["No mutation occurs in plan.", "Creation changes the source node's type and installs the new library as part of HOM createDigitalAsset; no automatic uninstall, node conversion, or file deletion is attempted on failure."]}
    def create_owned(self, node, type_name, label, destination_library, min_inputs=0, max_inputs=0, allow_library_write=False):
        _hcm_hda_create_bool(allow_library_write, "allow_library_write")
        if not allow_library_write: raise ValueError("create_owned writes and installs an HDA library; set allow_library_write=True after reviewing the plan")
        plan = self.plan(node, type_name, label, destination_library, min_inputs, max_inputs)
        source, type_name, label, destination, minimum, maximum = _hcm_hda_create_plan(node, type_name, label, destination_library, min_inputs, max_inputs)
        source_path = str(source.path())
        before = _hcm_hda_create_manifest(destination); event = {"kind": "hda.create_owned.createDigitalAsset", "node_path": source_path, "destination_library": destination, "status": "started", "writes_library": True, "changes_source_node_type": True, "installs_library": "unavoidable_HOM_behavior"}; self._mutation_events.append(event)
        try:
            returned_asset = source.createDigitalAsset(name=type_name, hda_file_name=destination, description=label, min_num_inputs=minimum, max_num_inputs=maximum, save_as_embedded=False, ignore_external_references=True, change_node_type=True, create_backup=False, install_path=destination)
            # HOM invalidates the original node wrapper when change_node_type
            # converts it. Re-resolve by the captured path before inspection.
            resolver = getattr(_hcm_hou, "node", None)
            asset = resolver(source_path) if callable(resolver) else returned_asset
            if asset is None: raise RuntimeError("createDigitalAsset converted the source but its replacement node could not be resolved")
            event["status"] = "complete"
        except BaseException:
            event["status"] = "error"; event["after"] = _hcm_hda_create_manifest(destination); raise
        definition = asset.type().definition()
        if definition is None or _hcm_hda_create_os.path.normcase(_hcm_hda_create_os.path.realpath(str(definition.libraryFilePath()))) != _hcm_hda_create_os.path.normcase(destination): raise RuntimeError("createDigitalAsset did not produce the requested external HDA definition")
        definitions = list(_hcm_hou.hda.definitionsInFile(destination)); types = [str(item.nodeType().name()) for item in definitions]
        if types != [type_name]: raise RuntimeError("new library did not contain exactly the requested definition")
        after = _hcm_hda_create_manifest(destination); event["after"] = after
        return {"operation": "hda.create_owned", "ok": True, "node_path": str(asset.path()), "type_name": type_name, "label": label, "library": {"before": before, "after": after, "installed_library": True, "installation": "unavoidable_createDigitalAsset_behavior", "hip_save_called": False}, "events": [event], "rollback_limits": "Non-transactional: createDigitalAsset changes the source node type and installs the new library. Cleanup requires explicit raw HOM uninstall/file removal after destroying or converting the created instance; this service does neither automatically."}
'''
