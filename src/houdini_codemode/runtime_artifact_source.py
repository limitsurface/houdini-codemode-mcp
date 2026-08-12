"""Houdini-side bounded artifact extension source."""

from __future__ import annotations


ARTIFACT_SOURCE = r'''
import hashlib as _hcm_artifact_hashlib
import os as _hcm_artifact_os
import tempfile as _hcm_artifact_tempfile
import time as _hcm_artifact_time
import uuid as _hcm_artifact_uuid


_HCM_ARTIFACT_SCHEMA = "houdini-codemode.node-artifact"
_HCM_ARTIFACT_SCHEMA_VERSION = 1
_HCM_ARTIFACT_DEFAULT_MAX_BYTES = 64 * 1024 * 1024
_HCM_ARTIFACT_HARD_MAX_BYTES = 64 * 1024 * 1024
_HCM_ARTIFACT_SUFFIX = ".hcm-node.json"


def _hcm_artifact_root():
    configured = _hcm_artifact_os.environ.get("HOUDINI_CODEMODE_ARTIFACT_ROOT")
    if configured:
        root = configured
    else:
        try:
            houdini_temp = _hcm_hou.expandString("$HOUDINI_TEMP_DIR")
        except BaseException:
            houdini_temp = ""
        if not houdini_temp or "$HOUDINI_TEMP_DIR" in houdini_temp:
            houdini_temp = _hcm_artifact_tempfile.gettempdir()
        root = _hcm_artifact_os.path.join(houdini_temp, "houdini-codemode-artifacts")
    return _hcm_artifact_os.path.realpath(_hcm_artifact_os.path.abspath(root))


def _hcm_artifact_limit(value):
    return _hcm_helper_int(
        value,
        "max_bytes",
        _HCM_ARTIFACT_DEFAULT_MAX_BYTES,
        1024,
        _HCM_ARTIFACT_HARD_MAX_BYTES,
    )


def _hcm_artifact_safe_name(name):
    if name is None:
        return _hcm_artifact_uuid.uuid4().hex + _HCM_ARTIFACT_SUFFIX
    if not isinstance(name, str) or not name:
        raise TypeError("artifact name must be a non-empty string or None")
    if name != _hcm_artifact_os.path.basename(name) or name in (".", ".."):
        raise ValueError("artifact name must not contain a directory")
    if len(name.encode("utf-8")) > 200:
        raise ValueError("artifact name must be at most 200 UTF-8 bytes")
    if not name.endswith(_HCM_ARTIFACT_SUFFIX):
        name += _HCM_ARTIFACT_SUFFIX
    return name


def _hcm_artifact_reference_value(reference):
    if isinstance(reference, dict):
        nested = reference.get("artifact")
        if isinstance(nested, dict):
            reference = nested
        if isinstance(reference, dict):
            reference = reference.get("id") or reference.get("path")
    if not isinstance(reference, str) or not reference:
        raise TypeError("artifact reference must be an id, path, or artifact manifest")
    return reference


def _hcm_artifact_resolve(reference):
    value = _hcm_artifact_reference_value(reference)
    root = _hcm_artifact_root()
    if _hcm_artifact_os.path.isabs(value):
        path = _hcm_artifact_os.path.realpath(value)
    else:
        if value != _hcm_artifact_os.path.basename(value):
            raise ValueError("artifact ids must not contain directories")
        path = _hcm_artifact_os.path.realpath(_hcm_artifact_os.path.join(root, value))
    try:
        within_root = _hcm_artifact_os.path.commonpath([root, path]) == root
    except ValueError:
        within_root = False
    if not within_root:
        raise ValueError("artifact path is outside the configured artifact root")
    return path


def _hcm_artifact_digest(path):
    digest = _hcm_artifact_hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


class _HCMArtifactCappedStream:
    def __init__(self, stream, maximum):
        self._stream = stream
        self._maximum = maximum
        self._used = 0

    def write(self, text):
        encoded_size = len(text.encode("utf-8"))
        if self._used + encoded_size > self._maximum:
            raise ValueError(
                "Artifact exceeds the configured {}-byte limit".format(self._maximum)
            )
        written = self._stream.write(text)
        self._used += encoded_size
        return written

    def flush(self):
        return self._stream.flush()

    def fileno(self):
        return self._stream.fileno()


def _hcm_artifact_record_count(value):
    count = 0
    pending = [value]
    seen = set()
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            identity = id(current)
            if identity in seen:
                continue
            seen.add(identity)
            count += int("type" in current)
            pending.extend(current.values())
        elif isinstance(current, (list, tuple)):
            identity = id(current)
            if identity in seen:
                continue
            seen.add(identity)
            pending.extend(current)
    return count


def _hcm_artifact_file_manifest(path, envelope=None):
    stat = _hcm_artifact_os.stat(path)
    result = {
        "id": _hcm_artifact_os.path.basename(path),
        "path": path,
        "bytes": stat.st_size,
        "sha256": _hcm_artifact_digest(path),
        "modified_unix": stat.st_mtime,
    }
    if isinstance(envelope, dict):
        result["schema"] = envelope.get("schema")
        result["schema_version"] = envelope.get("schema_version")
        source = envelope.get("source")
        if isinstance(source, dict):
            result["runtime_version"] = source.get("runtime_version")
            result["houdini_version"] = source.get("houdini_version")
        summary = envelope.get("summary")
        if isinstance(summary, dict):
            result["captured_records"] = summary.get("captured_records")
            result["captured_items"] = summary.get("captured_items")
    return result


def _hcm_artifact_write_envelope(path, envelope, maximum):
    directory = _hcm_artifact_os.path.dirname(path)
    _hcm_artifact_os.makedirs(directory, exist_ok=True)
    descriptor, temporary_path = _hcm_artifact_tempfile.mkstemp(
        prefix="." + _hcm_artifact_os.path.basename(path) + ".",
        suffix=".tmp",
        dir=directory,
    )
    try:
        with _hcm_artifact_os.fdopen(descriptor, "w", encoding="utf-8") as raw:
            stream = _HCMArtifactCappedStream(raw, maximum)
            _hcm_json.dump(
                envelope,
                stream,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            stream.flush()
            _hcm_artifact_os.fsync(stream.fileno())
        _hcm_artifact_os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path and _hcm_artifact_os.path.exists(temporary_path):
            try:
                _hcm_artifact_os.remove(temporary_path)
            except OSError:
                pass


def _hcm_artifact_export_node(
    node_value,
    name,
    children,
    all_parms,
    editables,
    overwrite,
    max_bytes,
    mutation_events,
):
    started = _hcm_artifact_time.perf_counter()
    node = _hcm_resolve_node(node_value)
    for value, label in (
        (children, "children"),
        (all_parms, "all_parms"),
        (editables, "editables"),
        (overwrite, "overwrite"),
    ):
        if not isinstance(value, bool):
            raise TypeError("{} must be a boolean".format(label))
    maximum = _hcm_artifact_limit(max_bytes)
    filename = _hcm_artifact_safe_name(name)
    path = _hcm_artifact_resolve(filename)
    existed_before = _hcm_artifact_os.path.exists(path)
    if existed_before and not overwrite:
        raise FileExistsError("Artifact already exists: " + path)
    try:
        definition = node.type().definition()
    except BaseException:
        definition = None
    if definition is not None:
        try:
            unlocked = not node.matchesCurrentDefinition()
        except BaseException:
            unlocked = False
        if unlocked and not children:
            raise ValueError(
                "Unlocked asset contents require children=True: " + node.path()
            )
    data = node.asData(
        children=children,
        editables=editables,
        inputs=True,
        position=True,
        flags=True,
        parms=True,
        default_parmvalues=all_parms,
        evaluate_parmvalues=False,
        parms_as_brief=True,
        parmtemplates="spare_only",
        metadata=False,
    )
    child_data = data.get("children", {}) if isinstance(data, dict) else {}
    summary = {
        "direct_nodes": len(node.children()) if children else 0,
        "direct_items": len(node.allItems()) if children else 0,
        "captured_records": _hcm_artifact_record_count(data),
        "captured_items": len(child_data) if isinstance(child_data, dict) else 0,
    }
    envelope = {
        "schema": _HCM_ARTIFACT_SCHEMA,
        "schema_version": _HCM_ARTIFACT_SCHEMA_VERSION,
        "source": {
            "runtime_version": _HCM_RUNTIME_VERSION,
            "protocol_version": _HCM_PROTOCOL_VERSION,
            "houdini_version": _hcm_hou.applicationVersionString(),
            "hip_file": _hcm_hou.hipFile.path(),
            "node_path": node.path(),
            "node_name": node.name(),
            "node_type": node.type().name(),
        },
        "capture": {
            "children": children,
            "all_parms": all_parms,
            "editables": editables,
            "evaluated": False,
        },
        "summary": summary,
        "data": data,
    }
    if _hcm_artifact_os.path.exists(path) and not overwrite:
        raise FileExistsError("Artifact already exists: " + path)
    _hcm_artifact_write_envelope(path, envelope, maximum)
    manifest = _hcm_artifact_file_manifest(path, envelope)
    mutation_events.append(
        {
            "kind": "artifact.write",
            "helper": "ctx.artifacts.export_node",
            "path": path,
            "bytes": manifest["bytes"],
            "overwrote": bool(existed_before and overwrite),
        }
    )
    return {
        "operation": "export_node",
        "artifact": manifest,
        "source": envelope["source"],
        "capture": envelope["capture"],
        "summary": summary,
        "elapsed_ms": round(
            (_hcm_artifact_time.perf_counter() - started) * 1000.0, 3
        ),
    }


def _hcm_artifact_read(reference, maximum):
    path = _hcm_artifact_resolve(reference)
    if not _hcm_artifact_os.path.isfile(path):
        raise FileNotFoundError("Artifact not found: " + path)
    size = _hcm_artifact_os.path.getsize(path)
    if size > maximum:
        raise ValueError(
            "Artifact uses {} bytes, exceeding the {}-byte read limit".format(
                size, maximum
            )
        )
    with open(path, "r", encoding="utf-8") as stream:
        envelope = _hcm_json.load(stream)
    if not isinstance(envelope, dict):
        raise ValueError("Artifact root must be a JSON object")
    if envelope.get("schema") != _HCM_ARTIFACT_SCHEMA:
        raise ValueError("Unsupported artifact schema")
    if envelope.get("schema_version") != _HCM_ARTIFACT_SCHEMA_VERSION:
        raise ValueError("Unsupported artifact schema version")
    for key in ("source", "capture", "summary", "data"):
        if not isinstance(envelope.get(key), dict):
            raise ValueError("Artifact {} data is missing or invalid".format(key))
    return path, envelope


def _hcm_artifact_restore_inverse(node, data, capture):
    """Apply a narrow node-data inverse when the artifact has no other scope.

    ``OpNode.asData`` root records use the nested ``parms`` and ``inputs``
    payloads accepted by their corresponding inverse methods.  Do not attempt
    that shortcut if another root property is present: ``setFromData`` remains
    the lossless reconciliation path for those records.
    """
    if (
        bool(capture.get("children", False))
        or bool(capture.get("editables", False))
        or not isinstance(data, dict)
        or not set(data).issubset({"type", "parms", "inputs"})
    ):
        return None
    if "parms" in data and not isinstance(data["parms"], dict):
        return None
    if "inputs" in data and not isinstance(data["inputs"], list):
        return None
    methods = []
    if "parms" in data:
        parms = data["parms"]
        if len(parms) == 1:
            parm_name, parm_data = next(iter(parms.items()))
            parm = node.parm(parm_name) if isinstance(parm_name, str) else None
            setter = getattr(parm, "setValueFromData", None)
            if callable(setter):
                setter(parm_data)
                methods.append("setValueFromData")
            else:
                node.setParmsFromData(parms)
                methods.append("setParmsFromData")
        elif parms:
            node.setParmsFromData(parms)
            methods.append("setParmsFromData")
    if "inputs" in data:
        inputs = data["inputs"]
        if inputs:
            node.setInputsFromData(inputs)
            methods.append("setInputsFromData")
    return methods


def _hcm_artifact_import_node(
    reference,
    parent_value,
    name,
    unique,
    max_bytes,
    mutation_events,
):
    started = _hcm_artifact_time.perf_counter()
    if name is not None and (not isinstance(name, str) or not name):
        raise TypeError("name must be a non-empty string or None")
    if not isinstance(unique, bool):
        raise TypeError("unique must be a boolean")
    maximum = _hcm_artifact_limit(max_bytes)
    path, envelope = _hcm_artifact_read(reference, maximum)
    parent = _hcm_resolve_node(parent_value, "parent")
    if not parent.isEditable():
        raise ValueError("Destination parent is not editable: " + parent.path())
    source = envelope["source"]
    capture = envelope["capture"]
    source_summary = envelope["summary"]
    data = envelope["data"]
    root_type = source.get("node_type")
    source_name = source.get("node_name")
    if not isinstance(root_type, str) or not root_type:
        raise ValueError("Artifact source node type is missing")
    destination_name = name if name is not None else source_name
    if not isinstance(destination_name, str) or not destination_name:
        raise ValueError("Destination node name is missing")
    if parent.node(destination_name) is not None and not unique:
        raise ValueError(
            "Destination node already exists: {}/{}".format(
                parent.path(), destination_name
            )
        )
    mutation_events.append(
        {
            "kind": "artifact.read",
            "helper": "ctx.artifacts.import_node",
            "path": path,
            "bytes": _hcm_artifact_os.path.getsize(path),
        }
    )
    created = None
    previous_update_mode = None
    update_mode_changed = False
    try:
        try:
            previous_update_mode = _hcm_hou.updateModeSetting()
            _hcm_hou.setUpdateMode(_hcm_hou.updateMode.Manual)
            update_mode_changed = True
        except BaseException:
            pass
        created = parent.createNode(root_type, destination_name)
        try:
            created.setDisplayFlag(False)
        except BaseException:
            pass
        inverse_methods = _hcm_artifact_restore_inverse(created, data, capture)
        if inverse_methods is None:
            created.setFromData(
                data,
                clear_content=True,
                force_item_creation=True,
                parms=True,
                parmtemplates=True,
                children=True,
                editables=True,
                skip_notes=False,
            )
            inverse_methods = ["setFromData"]
        destination_summary = {
            "direct_nodes": len(created.children()),
            "direct_items": len(created.allItems()),
        }
        children_captured = bool(capture.get("children", False))
        verified = (
            created.type().name() == root_type
            and (
                not children_captured
                or destination_summary["direct_nodes"]
                == int(source_summary.get("direct_nodes", 0))
            )
            and (
                not children_captured
                or destination_summary["direct_items"]
                == int(source_summary.get("direct_items", 0))
            )
        )
        inspected = [created]
        if children_captured:
            inspected.extend(created.children())
        error_count = 0
        warning_count = 0
        for inspected_node in inspected:
            try:
                error_count += len(inspected_node.errors())
                warning_count += len(inspected_node.warnings())
            except BaseException:
                pass
        mutation_events.append(
            {
                "kind": "node.create_from_artifact",
                "helper": "ctx.artifacts.import_node",
                "node_path": created.path(),
                "artifact_id": _hcm_artifact_os.path.basename(path),
            }
        )
        return {
            "operation": "import_node",
            "artifact": _hcm_artifact_file_manifest(path, envelope),
            "path": created.path(),
            "name": created.name(),
            "type": created.type().name(),
            "destination": {
                "houdini_version": _hcm_hou.applicationVersionString(),
                "hip_file": _hcm_hou.hipFile.path(),
            },
            "source": source,
            "capture": capture,
            "source_summary": source_summary,
            "destination_summary": destination_summary,
            "inverse_methods": inverse_methods,
            "error_count": error_count,
            "warning_count": warning_count,
            "verified": verified,
            "elapsed_ms": round(
                (_hcm_artifact_time.perf_counter() - started) * 1000.0, 3
            ),
        }
    except BaseException:
        if created is not None:
            try:
                removed_path = created.path()
                created.destroy()
                mutation_events.append(
                    {
                        "kind": "node.remove_partial_import",
                        "helper": "ctx.artifacts.import_node",
                        "node_path": removed_path,
                    }
                )
            except BaseException:
                pass
        raise
    finally:
        if update_mode_changed:
            try:
                _hcm_hou.setUpdateMode(previous_update_mode)
            except BaseException:
                pass


def _hcm_artifact_inspect(reference, max_bytes):
    maximum = _hcm_artifact_limit(max_bytes)
    path, envelope = _hcm_artifact_read(reference, maximum)
    return {
        "artifact": _hcm_artifact_file_manifest(path, envelope),
        "source": envelope["source"],
        "capture": envelope["capture"],
        "summary": envelope["summary"],
    }


def _hcm_artifact_list(max_items):
    max_items = _hcm_helper_int(max_items, "max_items", 50, 1, 1000)
    root = _hcm_artifact_root()
    if not _hcm_artifact_os.path.isdir(root):
        return {
            "root": root,
            "cols": ["id", "bytes", "modified_unix"],
            "rows": [],
            "count": 0,
            "total": 0,
            "truncated": False,
        }
    names = sorted(
        name
        for name in _hcm_artifact_os.listdir(root)
        if name.endswith(_HCM_ARTIFACT_SUFFIX)
        and _hcm_artifact_os.path.isfile(_hcm_artifact_os.path.join(root, name))
    )
    rows = []
    for name in names[:max_items]:
        stat = _hcm_artifact_os.stat(_hcm_artifact_os.path.join(root, name))
        rows.append([name, stat.st_size, stat.st_mtime])
    return {
        "root": root,
        "cols": ["id", "bytes", "modified_unix"],
        "rows": rows,
        "count": len(rows),
        "total": len(names),
        "truncated": len(names) > len(rows),
    }


class _HCMArtifactService:
    def __init__(self, mutation_events):
        self._mutation_events = mutation_events

    def root(self):
        return {"path": _hcm_artifact_root(), "max_bytes": _HCM_ARTIFACT_HARD_MAX_BYTES}

    def export_node(
        self,
        node,
        name=None,
        children=False,
        all_parms=False,
        editables=False,
        overwrite=False,
        max_bytes=_HCM_ARTIFACT_DEFAULT_MAX_BYTES,
    ):
        return _hcm_artifact_export_node(
            node,
            name,
            children,
            all_parms,
            editables,
            overwrite,
            max_bytes,
            self._mutation_events,
        )

    def import_node(
        self,
        artifact,
        parent,
        name=None,
        unique=False,
        max_bytes=_HCM_ARTIFACT_DEFAULT_MAX_BYTES,
    ):
        return _hcm_artifact_import_node(
            artifact,
            parent,
            name,
            unique,
            max_bytes,
            self._mutation_events,
        )

    def inspect(self, artifact, max_bytes=_HCM_ARTIFACT_DEFAULT_MAX_BYTES):
        return _hcm_artifact_inspect(artifact, max_bytes)

    def list(self, max_items=50):
        return _hcm_artifact_list(max_items)

    def remove(self, artifact):
        path = _hcm_artifact_resolve(artifact)
        if not _hcm_artifact_os.path.isfile(path):
            raise FileNotFoundError("Artifact not found: " + path)
        size = _hcm_artifact_os.path.getsize(path)
        _hcm_artifact_os.remove(path)
        self._mutation_events.append(
            {
                "kind": "artifact.remove",
                "helper": "ctx.artifacts.remove",
                "path": path,
                "bytes": size,
            }
        )
        return {"removed": True, "path": path, "bytes": size}
'''
