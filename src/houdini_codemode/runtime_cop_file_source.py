"""Houdini-side, bounded Copernicus image file IO extension source.

This is intentionally an opt-in extension.  Append ``COP_FILE_SOURCE`` after
the base runtime (and ``runtime_cop_source.COP_SOURCE``) when wiring the
service into a runtime build.  It does not save the HIP file.
"""

from __future__ import annotations


COP_FILE_SOURCE = r'''
import os as _hcm_cop_file_os
import tempfile as _hcm_cop_file_tempfile


_HCM_COP_FILE_DEFAULT_MAX_BYTES = 512 * 1024 * 1024
_HCM_COP_FILE_HARD_MAX_BYTES = 1024 * 1024 * 1024
_HCM_COP_FILE_MAX_PATH_BYTES = 4096
_HCM_COP_FILE_RAW_EXTENSIONS = (".exr",)
_HCM_COP_FILE_VIEW_EXTENSIONS = (
    ".bmp", ".exr", ".jpg", ".jpeg", ".png", ".tif", ".tiff",
)


def _hcm_cop_file_limit(value):
    return _hcm_helper_int(
        value,
        "max_bytes",
        _HCM_COP_FILE_DEFAULT_MAX_BYTES,
        1,
        _HCM_COP_FILE_HARD_MAX_BYTES,
    )


def _hcm_cop_file_path(value, label, must_exist):
    if not isinstance(value, str) or not value:
        raise TypeError("{} must be a non-empty string".format(label))
    if "\x00" in value:
        raise ValueError("{} must not contain a NUL character".format(label))
    try:
        expanded = _hcm_hou.expandString(value)
    except BaseException:
        expanded = value
    if not isinstance(expanded, str) or not expanded or "$" in expanded:
        raise ValueError("{} contains an unresolved Houdini variable".format(label))
    path = _hcm_cop_file_os.path.realpath(_hcm_cop_file_os.path.abspath(expanded))
    if len(path.encode("utf-8")) > _HCM_COP_FILE_MAX_PATH_BYTES:
        raise ValueError(
            "{} exceeds the {}-byte path limit".format(
                label, _HCM_COP_FILE_MAX_PATH_BYTES
            )
        )
    if must_exist and not _hcm_cop_file_os.path.isfile(path):
        raise FileNotFoundError("{} is not an existing file: {}".format(label, path))
    return path


def _hcm_cop_file_extension(path, mode):
    extension = _hcm_cop_file_os.path.splitext(path)[1].lower()
    allowed = (
        _HCM_COP_FILE_RAW_EXTENSIONS
        if mode == "raw"
        else _HCM_COP_FILE_VIEW_EXTENSIONS
    )
    if extension not in allowed:
        raise ValueError(
            "output_path extension {} is not allowed for {} export".format(
                extension or "<none>", mode
            )
        )
    return extension


def _hcm_cop_file_bool(value, label):
    if not isinstance(value, bool):
        raise TypeError("{} must be a boolean".format(label))
    return value


def _hcm_cop_file_name(value, fallback):
    if value is None:
        return fallback
    if not isinstance(value, str) or not value:
        raise TypeError("name must be a non-empty string or None")
    parts = []
    previous_underscore = False
    for character in value:
        allowed = character.isascii() and (character.isalnum() or character == "_")
        if allowed:
            parts.append(character)
            previous_underscore = False
        elif not previous_underscore:
            parts.append("_")
            previous_underscore = True
    name = "".join(parts).strip("_") or fallback
    if name[0].isdigit():
        name = "_" + name
    if len(name) > 128:
        name = name[:128]
    return name


def _hcm_cop_file_unique_child_name(parent, base_name):
    candidate = base_name
    index = 1
    while parent.node(candidate) is not None:
        candidate = "{}_{}".format(base_name, index)
        index += 1
        if index > 10000:
            raise RuntimeError("Unable to allocate a unique node name")
    return candidate


def _hcm_cop_file_set_parm(node, name, value, required=True):
    parm = node.parm(name)
    if parm is None:
        if required:
            raise ValueError("Parameter not found on {}: {}".format(node.path(), name))
        return False
    parm.set(value)
    return True


def _hcm_cop_file_set_menu(node, name, token, required=True):
    parm = node.parm(name)
    if parm is None:
        if required:
            raise ValueError("Parameter not found on {}: {}".format(node.path(), name))
        return False
    template = parm.parmTemplate()
    items = list(template.menuItems())
    if token not in items:
        raise ValueError("Menu item not found on {}/{}: {}".format(node.path(), name, token))
    try:
        current = parm.eval()
    except BaseException:
        current = None
    parm.set(items.index(token) if isinstance(current, int) else token)
    return True


def _hcm_cop_file_press(node, name, required=True):
    parm = node.parm(name)
    if parm is None:
        if required:
            raise ValueError("Button not found on {}: {}".format(node.path(), name))
        return False
    parm.pressButton()
    return True


def _hcm_cop_file_output(node, output):
    if not callable(getattr(node, "layer", None)):
        raise ValueError("Node does not provide Copernicus layer data: " + node.path())
    layer_node, layer_index, identity, _outputs = _hcm_cop_layer_target(node, output)
    return layer_node, layer_index, identity


def _hcm_cop_file_manifest(path):
    stat = _hcm_cop_file_os.stat(path)
    return {"path": path, "bytes": int(stat.st_size)}


def _hcm_cop_file_temporary_sibling(target):
    directory, filename = _hcm_cop_file_os.path.split(target)
    stem, extension = _hcm_cop_file_os.path.splitext(filename)
    descriptor, temporary_path = _hcm_cop_file_tempfile.mkstemp(
        prefix="." + stem + ".hcm-",
        suffix=extension,
        dir=directory,
    )
    _hcm_cop_file_os.close(descriptor)
    return temporary_path


class _HCMCopFileService:
    def __init__(self, mutation_events):
        self._mutation_events = mutation_events

    def export_image(
        self,
        node,
        output_path,
        mode="raw",
        output=None,
        overwrite=False,
        max_bytes=_HCM_COP_FILE_DEFAULT_MAX_BYTES,
        display=None,
        view=None,
    ):
        if mode not in ("raw", "view"):
            raise ValueError("mode must be 'raw' or 'view'")
        _hcm_cop_file_bool(overwrite, "overwrite")
        if display is not None and not isinstance(display, str):
            raise TypeError("display must be a string or None")
        if view is not None and not isinstance(view, str):
            raise TypeError("view must be a string or None")
        maximum = _hcm_cop_file_limit(max_bytes)
        target = _hcm_cop_file_path(output_path, "output_path", False)
        _hcm_cop_file_extension(target, mode)
        directory = _hcm_cop_file_os.path.dirname(target)
        if not _hcm_cop_file_os.path.isdir(directory):
            raise ValueError("output_path parent directory does not exist: " + directory)
        existed_before = _hcm_cop_file_os.path.exists(target)
        if existed_before and not overwrite:
            raise FileExistsError("Output file already exists: " + target)
        resolved = _hcm_resolve_node(node)
        layer_node, _layer_index, identity = _hcm_cop_file_output(resolved, output)
        parent = layer_node.parent()
        if parent is None:
            raise ValueError("COP output node has no parent network: " + layer_node.path())
        temporary_path = _hcm_cop_file_temporary_sibling(target)
        helper = None
        helper_path = None
        try:
            helper = parent.createNode(
                "rop_image", _hcm_cop_file_unique_child_name(parent, "_hcm_export_image")
            )
            helper_path = helper.path()
            _hcm_cop_file_set_parm(helper, "coppath", layer_node.path())
            _hcm_cop_file_set_parm(helper, "copoutput", temporary_path)
            _hcm_cop_file_set_menu(
                helper, "colorconversion", "raw" if mode == "raw" else "bakeocio"
            )
            _hcm_cop_file_set_parm(helper, "mkpath", 0, required=False)
            _hcm_cop_file_set_parm(helper, "outputaovs", 1, required=False)
            _hcm_cop_file_set_parm(helper, "aov1", "C", required=False)
            if layer_node.path() == resolved.path():
                _hcm_cop_file_set_parm(helper, "useport1", 1, required=False)
                _hcm_cop_file_set_parm(
                    helper, "port1", int(identity["output_index"]), required=False
                )
            if mode == "view":
                if display:
                    _hcm_cop_file_set_parm(helper, "ociodisplay", display, required=False)
                if view:
                    _hcm_cop_file_set_parm(helper, "ocioview", view, required=False)
            _hcm_cop_file_press(helper, "execute")
            if not _hcm_cop_file_os.path.isfile(temporary_path):
                raise RuntimeError("ROP Image did not create the expected file: " + temporary_path)
            file_data = _hcm_cop_file_manifest(temporary_path)
            if file_data["bytes"] > maximum:
                raise ValueError(
                    "Exported image uses {} bytes, exceeding the {}-byte limit".format(
                        file_data["bytes"], maximum
                    )
                )
            _hcm_cop_file_os.replace(temporary_path, target)
            temporary_path = None
            file_data = _hcm_cop_file_manifest(target)
        finally:
            if helper is not None:
                try:
                    helper.destroy()
                except BaseException:
                    pass
            if temporary_path and _hcm_cop_file_os.path.exists(temporary_path):
                try:
                    _hcm_cop_file_os.remove(temporary_path)
                except OSError:
                    pass
        self._mutation_events.append(
            {
                "kind": "cop.image_export",
                "helper": "ctx.cop_files.export_image",
                "node_path": resolved.path(),
                "output_path": target,
            }
        )
        return {
            "node_path": resolved.path(),
            "layer_node_path": layer_node.path(),
            "output": identity,
            "mode": mode,
            "file": file_data,
            "overwrite": overwrite,
            "existed_before": existed_before,
            "max_bytes": maximum,
            "color_conversion": {
                "mode": "raw" if mode == "raw" else "bakeocio",
                "display": display or "Default",
                "view": view or "Default",
            },
            "temporary_helper": {"path": helper_path, "removed": True},
            "hip_saved": False,
        }

    def import_image(
        self,
        image_path,
        parent,
        name=None,
        colorspace="ocio",
        set_display=False,
        max_bytes=_HCM_COP_FILE_DEFAULT_MAX_BYTES,
    ):
        if colorspace not in ("ocio", "raw"):
            raise ValueError("colorspace must be 'ocio' or 'raw'")
        _hcm_cop_file_bool(set_display, "set_display")
        maximum = _hcm_cop_file_limit(max_bytes)
        source = _hcm_cop_file_path(image_path, "image_path", True)
        file_data = _hcm_cop_file_manifest(source)
        if file_data["bytes"] > maximum:
            raise ValueError(
                "Image uses {} bytes, exceeding the {}-byte limit".format(
                    file_data["bytes"], maximum
                )
            )
        destination = _hcm_resolve_node(parent)
        stem = _hcm_cop_file_os.path.splitext(_hcm_cop_file_os.path.basename(source))[0]
        node_name = _hcm_cop_file_unique_child_name(
            destination, _hcm_cop_file_name(name, "hcm_image_" + _hcm_cop_file_name(stem, "image"))
        )
        created = destination.createNode("file", node_name)
        created_path = created.path()
        try:
            _hcm_cop_file_set_parm(created, "filename", source)
            _hcm_cop_file_set_menu(created, "colorspace", colorspace)
            reload_pressed = _hcm_cop_file_press(created, "reload", required=False)
            addaovs_pressed = _hcm_cop_file_press(created, "addaovs", required=False)
            if set_display:
                created.setDisplayFlag(True)
                try:
                    created.setRenderFlag(True)
                except BaseException:
                    pass
        except BaseException:
            try:
                created.destroy()
            except BaseException:
                pass
            raise
        self._mutation_events.append(
            {
                "kind": "cop.image_import",
                "helper": "ctx.cop_files.import_image",
                "node_path": created_path,
                "image_path": source,
            }
        )
        return {
            "node_path": created_path,
            "parent_path": destination.path(),
            "file": file_data,
            "colorspace": colorspace,
            "reload_pressed": reload_pressed,
            "addaovs_pressed": addaovs_pressed,
            "display": set_display,
            "max_bytes": maximum,
            "hip_saved": False,
        }
'''
