"""Narrow, staged copy of one installed HDA definition into a safe library.

The source is appended to the Houdini runtime by a later integration slice.  It
deliberately only packages an existing definition to an explicitly supplied
external library; it never updates the source definition or scene instances.
"""

from __future__ import annotations


HDA_PACKAGE_SOURCE = r'''
import hashlib as _hcm_hda_package_hashlib
import os as _hcm_hda_package_os
import shutil as _hcm_hda_package_shutil
import tempfile as _hcm_hda_package_tempfile


_HCM_HDA_PACKAGE_SUFFIXES = (".hda", ".hdalc", ".hdanc", ".otl")


def _hcm_hda_package_bool(value, name):
    if not isinstance(value, bool):
        raise TypeError(name + " must be a boolean")
    return value


def _hcm_hda_package_text(value, name, maximum=4096, allow_none=True):
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value.strip():
        raise TypeError(name + " must be a non-empty string" + (" or null" if allow_none else ""))
    value = value.strip()
    if len(value) > maximum:
        raise ValueError(name + " exceeds " + str(maximum) + " characters")
    return value


def _hcm_hda_package_path(value, name):
    value = _hcm_hda_package_text(value, name, allow_none=False)
    expand = getattr(_hcm_hou, "expandString", None)
    if callable(expand):
        try:
            value = expand(value)
        except BaseException:
            pass
    value = _hcm_hda_package_os.path.expandvars(value)
    path = _hcm_hda_package_os.path.realpath(
        _hcm_hda_package_os.path.abspath(_hcm_hda_package_os.path.normpath(value))
    )
    if _hcm_hda_package_os.path.splitext(path)[1].lower() not in _HCM_HDA_PACKAGE_SUFFIXES:
        raise ValueError("{} must use one of: {}".format(name, ", ".join(_HCM_HDA_PACKAGE_SUFFIXES)))
    return path


def _hcm_hda_package_under(path, root):
    try:
        return _hcm_hda_package_os.path.commonpath((path, root)) == root
    except ValueError:
        return False


def _hcm_hda_package_install_roots():
    roots = []
    get_env = getattr(_hcm_hou, "getenv", None)
    if callable(get_env):
        try:
            hfs = get_env("HFS")
        except BaseException:
            hfs = None
        if isinstance(hfs, str) and hfs.strip():
            roots.append(_hcm_hda_package_os.path.realpath(
                _hcm_hda_package_os.path.abspath(_hcm_hda_package_os.path.normpath(hfs))
            ))
    application_path = getattr(_hcm_hou, "applicationPath", None)
    if callable(application_path):
        try:
            executable = application_path()
        except BaseException:
            executable = None
        if isinstance(executable, str) and executable.strip():
            roots.append(_hcm_hda_package_os.path.realpath(
                _hcm_hda_package_os.path.dirname(_hcm_hda_package_os.path.abspath(executable))
            ))
    return tuple(sorted(set(roots)))


def _hcm_hda_package_reject_install(path, label):
    for root in _hcm_hda_package_install_roots():
        if _hcm_hda_package_under(path, root):
            raise ValueError(label + " must not be inside the Houdini installation: " + root)


def _hcm_hda_package_reject_loaded_destination(path):
    loaded = getattr(getattr(_hcm_hou, "hda", None), "loadedFiles", None)
    if not callable(loaded):
        raise RuntimeError("cannot verify whether destination_library is loaded")
    try:
        paths = loaded()
    except BaseException as exc:
        raise RuntimeError("cannot verify whether destination_library is loaded: " + str(exc))
    target = _hcm_hda_package_os.path.normcase(path)
    for item in paths:
        if not isinstance(item, str) or not item or item == "Embedded":
            continue
        try:
            candidate = _hcm_hda_package_path(item, "loaded library")
        except BaseException:
            continue
        if _hcm_hda_package_os.path.normcase(candidate) == target:
            raise ValueError("destination_library is currently loaded by Houdini")


def _hcm_hda_package_manifest(path):
    if not _hcm_hda_package_os.path.exists(path):
        return {"exists": False, "size": None, "sha256": None, "mtime_ns": None}
    stat = _hcm_hda_package_os.stat(path)
    digest = _hcm_hda_package_hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "exists": True,
        "size": int(stat.st_size),
        "sha256": digest.hexdigest(),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def _hcm_hda_package_temporary_sibling(target):
    directory, filename = _hcm_hda_package_os.path.split(target)
    stem, extension = _hcm_hda_package_os.path.splitext(filename)
    descriptor, path = _hcm_hda_package_tempfile.mkstemp(
        prefix="." + stem + ".hcm-", suffix=extension, dir=directory
    )
    _hcm_hda_package_os.close(descriptor)
    return path


def _hcm_hda_package_backup_path(target):
    directory, filename = _hcm_hda_package_os.path.split(target)
    stem, extension = _hcm_hda_package_os.path.splitext(filename)
    descriptor, path = _hcm_hda_package_tempfile.mkstemp(
        prefix="." + stem + ".hcm-backup-", suffix=extension, dir=directory
    )
    _hcm_hda_package_os.close(descriptor)
    return path


def _hcm_hda_package_same_manifest(left, right):
    return (
        left["exists"] == right["exists"]
        and left["size"] == right["size"]
        and left["sha256"] == right["sha256"]
        and left["mtime_ns"] == right["mtime_ns"]
    )


class _HCMHdaPackageService:
    """Stage one definition then atomically publish it without installation."""

    def __init__(self, mutation_events=None, planner=None):
        self._mutation_events = mutation_events if mutation_events is not None else []
        self._planner = planner

    def copy(
        self,
        node,
        destination_library,
        type_name=None,
        label=None,
        overwrite=False,
        backup=False,
        max_items=100,
    ):
        _hcm_hda_package_bool(overwrite, "overwrite")
        _hcm_hda_package_bool(backup, "backup")
        if backup and not overwrite:
            raise ValueError("backup=True requires overwrite=True")
        destination = _hcm_hda_package_path(destination_library, "destination_library")
        if not _hcm_hda_package_os.path.isdir(_hcm_hda_package_os.path.dirname(destination)):
            raise ValueError("destination_library parent directory does not exist")
        _hcm_hda_package_reject_install(destination, "destination_library")
        _hcm_hda_package_reject_loaded_destination(destination)
        instance = _hcm_resolve_node(node, "node")
        definition = instance.type().definition()
        if definition is None:
            raise ValueError("Node is not an HDA instance: " + str(instance.path()))
        source_library = str(definition.libraryFilePath())
        if not source_library or source_library == "Embedded":
            raise ValueError("Embedded HDA definitions cannot be packaged by this operation")
        source = _hcm_hda_package_path(source_library, "source library")
        _hcm_hda_package_reject_install(source, "source library")
        if not _hcm_hda_package_os.path.isfile(source):
            raise ValueError("source library does not exist as a regular file: " + source)
        if _hcm_hda_package_os.path.normcase(source) == _hcm_hda_package_os.path.normcase(destination):
            raise ValueError("destination_library must differ from the source library")
        requested_type = _hcm_hda_package_text(type_name, "type_name", 256)
        requested_label = _hcm_hda_package_text(label, "label", 512)
        planner = self._planner if self._planner is not None else _HCMHdaUpdateService()
        plan = planner.plan(
            instance,
            mode="copy",
            library=destination,
            type_name=requested_type,
            label=requested_label,
            contents=False,
            interface=False,
            preserve_sections=False,
            preserve_tools=False,
            reference_audit=True,
            overwrite=overwrite,
            match_current=False,
            create_backup=False,
            max_items=max_items,
        )
        if not plan.get("ok"):
            raise ValueError("HDA package preflight failed: " + "; ".join(plan.get("blockers", ())))
        target_type = plan["definition"]["target_type"]
        definitions = plan["destination"]["definitions"]
        before = _hcm_hda_package_manifest(destination)
        exists = before["exists"]
        if exists and not overwrite:
            raise FileExistsError("destination_library already exists: " + destination)
        if exists:
            types = definitions.get("types", ())
            if (
                not definitions.get("available")
                or not definitions.get("count_complete")
                or definitions.get("count") != 1
                or list(types) != [target_type]
            ):
                raise ValueError(
                    "overwrite is limited to a destination library containing exactly the target type"
                )
        temporary = None
        backup_path = None
        backup_manifest = None
        event = {
            "kind": "hda.library_package",
            "helper": "ctx.hda.package.copy",
            "node_path": str(instance.path()),
            "source_library": source,
            "source": _hcm_hda_package_manifest(source),
            "destination_library": destination,
            "target_type": target_type,
            "overwrite": overwrite,
            "before": before,
            "backup": None,
            "after": None,
            "atomic_replace": "os.replace",
            "installed_library": False,
            "hip_saved": False,
        }
        try:
            temporary = _hcm_hda_package_temporary_sibling(destination)
            definition.copyToHDAFile(temporary, new_name=target_type, new_menu_name=requested_label)
            staged = _hcm_hda_package_manifest(temporary)
            if not staged["exists"] or staged["size"] < 1:
                raise RuntimeError("copyToHDAFile did not create a non-empty staged library")
            current = _hcm_hda_package_manifest(destination)
            if not _hcm_hda_package_same_manifest(before, current):
                raise RuntimeError("destination library changed during staging; refusing to replace it")
            if exists and backup:
                backup_path = _hcm_hda_package_backup_path(destination)
                _hcm_hda_package_shutil.copy2(destination, backup_path)
                backup_manifest = _hcm_hda_package_manifest(backup_path)
                if not _hcm_hda_package_same_manifest(before, backup_manifest):
                    raise RuntimeError("backup verification failed")
            _hcm_hda_package_os.replace(temporary, destination)
            temporary = None
            after = _hcm_hda_package_manifest(destination)
            event["after"] = after
            event["backup"] = None if backup_path is None else {
                "path": backup_path, "manifest": backup_manifest
            }
            self._mutation_events.append(event)
            return {
                "operation": "hda.package.copy",
                "node_path": str(instance.path()),
                "type_name": target_type,
                "source_library": source,
                "source": event["source"],
                "destination_library": destination,
                "overwrite": overwrite,
                "before": before,
                "after": after,
                "backup": event["backup"],
                "staging": {"method": "copyToHDAFile_then_os.replace", "cleaned": True},
                "library_installed": False,
                "instance_changed": False,
                "hip_saved": False,
            }
        except BaseException:
            event["after"] = _hcm_hda_package_manifest(destination)
            event["backup"] = None if backup_path is None else {
                "path": backup_path, "manifest": _hcm_hda_package_manifest(backup_path)
            }
            event["failed"] = True
            self._mutation_events.append(event)
            raise
        finally:
            if temporary and _hcm_hda_package_os.path.exists(temporary):
                try:
                    _hcm_hda_package_os.remove(temporary)
                except OSError:
                    pass
'''
