"""Houdini-side, bounded Scene Viewer capture extension source."""

from __future__ import annotations


VIEWPORT_SOURCE = r'''
import os as _hcm_viewport_os
import tempfile as _hcm_viewport_tempfile


_HCM_VIEWPORT_DEFAULT_MAX_BYTES = 64 * 1024 * 1024
_HCM_VIEWPORT_HARD_MAX_BYTES = 256 * 1024 * 1024
_HCM_VIEWPORT_MAX_PATH_BYTES = 4096
_HCM_VIEWPORT_MAX_DIMENSION = 8192


def _hcm_viewport_int(value, label, default, minimum, maximum):
    if value is None:
        value = default
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("{} must be an integer".format(label))
    if value < minimum or value > maximum:
        raise ValueError("{} must be between {} and {}".format(label, minimum, maximum))
    return value


def _hcm_viewport_bool(value, label):
    if not isinstance(value, bool):
        raise TypeError("{} must be a boolean".format(label))
    return value


def _hcm_viewport_path(value):
    if not isinstance(value, str) or not value:
        raise TypeError("output_path must be a non-empty string")
    if "\x00" in value:
        raise ValueError("output_path must not contain a NUL character")
    try:
        expanded = _hcm_hou.expandString(value)
    except BaseException:
        expanded = value
    if not isinstance(expanded, str) or not expanded or "$" in expanded:
        raise ValueError("output_path contains an unresolved Houdini variable")
    path = _hcm_viewport_os.path.realpath(_hcm_viewport_os.path.abspath(expanded))
    if len(path.encode("utf-8")) > _HCM_VIEWPORT_MAX_PATH_BYTES:
        raise ValueError("output_path exceeds the path limit")
    if _hcm_viewport_os.path.splitext(path)[1].lower() != ".png":
        raise ValueError("output_path must use the .png extension")
    parent = _hcm_viewport_os.path.dirname(path)
    if not _hcm_viewport_os.path.isdir(parent):
        raise ValueError("output_path parent directory does not exist: " + parent)
    return path


def _hcm_viewport_scene_viewers():
    try:
        desktop = _hcm_hou.ui.curDesktop()
    except BaseException as exc:
        raise RuntimeError("Viewport capture requires graphical Houdini") from exc
    if desktop is None:
        raise RuntimeError("Viewport capture requires graphical Houdini")
    return [pane for pane in desktop.paneTabs()
            if pane.type() == _hcm_hou.paneTabType.SceneViewer]


def _hcm_viewport_resolve(pane_name, index):
    if pane_name is not None and index is not None:
        raise ValueError("Provide pane_name or index, not both")
    if pane_name is not None and (not isinstance(pane_name, str) or not pane_name):
        raise TypeError("pane_name must be a non-empty string or None")
    if index is not None and (isinstance(index, bool) or not isinstance(index, int)):
        raise TypeError("index must be an integer or None")
    viewers = _hcm_viewport_scene_viewers()
    if not viewers:
        raise RuntimeError("No Scene Viewer panes are available")
    if pane_name is not None:
        for viewer in viewers:
            if viewer.name() == pane_name:
                return viewer
        raise ValueError("Scene Viewer not found: " + pane_name)
    if index is not None:
        if index < 0 or index >= len(viewers):
            raise ValueError("Scene Viewer index out of range: {}".format(index))
        return viewers[index]
    current = [pane for pane in _hcm_hou.ui.curDesktop().currentPaneTabs()
               if pane.type() == _hcm_hou.paneTabType.SceneViewer]
    if len(current) == 1:
        return current[0]
    if len(viewers) == 1:
        return viewers[0]
    raise ValueError("Multiple Scene Viewers are available; provide pane_name or index")


def _hcm_viewport_context(viewer):
    viewport = viewer.curViewport()
    if viewport is None:
        raise RuntimeError("Scene Viewer has no active viewport")
    payload = {
        "pane_name": viewer.name(),
        "viewport_name": viewport.name(),
        "viewport_type": str(viewport.type()),
    }
    for key, callback in (
        ("current_network", lambda: viewer.pwd().path() if viewer.pwd() else None),
        ("current_node", lambda: viewer.currentNode().path() if viewer.currentNode() else None),
        ("current_state", viewer.currentState),
        ("camera", lambda: viewport.camera().path() if viewport.camera() else None),
    ):
        try:
            payload[key] = callback()
        except BaseException:
            payload[key] = None
    return payload


def _hcm_viewport_temporary_sibling(target):
    directory, filename = _hcm_viewport_os.path.split(target)
    stem, extension = _hcm_viewport_os.path.splitext(filename)
    descriptor, temporary_path = _hcm_viewport_tempfile.mkstemp(
        prefix="." + stem + ".hcm-", suffix=extension, dir=directory
    )
    _hcm_viewport_os.close(descriptor)
    return temporary_path


class _HCMViewportService:
    def __init__(self, mutation_events):
        self._mutation_events = mutation_events

    def capture(self, output_path, pane_name=None, index=None, frame=None,
                width=512, height=512, overwrite=False,
                max_bytes=_HCM_VIEWPORT_DEFAULT_MAX_BYTES):
        target = _hcm_viewport_path(output_path)
        _hcm_viewport_bool(overwrite, "overwrite")
        width = _hcm_viewport_int(width, "width", 512, 1, _HCM_VIEWPORT_MAX_DIMENSION)
        height = _hcm_viewport_int(height, "height", 512, 1, _HCM_VIEWPORT_MAX_DIMENSION)
        if frame is None:
            frame = int(_hcm_hou.frame())
        frame = _hcm_viewport_int(frame, "frame", 1, -10000000, 10000000)
        maximum = _hcm_viewport_int(max_bytes, "max_bytes",
            _HCM_VIEWPORT_DEFAULT_MAX_BYTES, 1, _HCM_VIEWPORT_HARD_MAX_BYTES)
        existed_before = _hcm_viewport_os.path.exists(target)
        if existed_before and not overwrite:
            raise FileExistsError("Output file already exists: " + target)
        viewer = _hcm_viewport_resolve(pane_name, index)
        viewer_context = _hcm_viewport_context(viewer)
        temporary_path = _hcm_viewport_temporary_sibling(target)
        try:
            assetutils = __import__("husd.assetutils", fromlist=["assetutils"])
            assetutils.saveThumbnailFromViewer(
                sceneviewer=viewer, frame=frame, res=(width, height), output=temporary_path
            )
            if not _hcm_viewport_os.path.isfile(temporary_path):
                raise RuntimeError("Viewport capture did not create the expected file")
            size = int(_hcm_viewport_os.path.getsize(temporary_path))
            if size > maximum:
                raise ValueError("Captured image uses {} bytes, exceeding the {}-byte limit".format(size, maximum))
            _hcm_viewport_os.replace(temporary_path, target)
            temporary_path = None
        finally:
            if temporary_path and _hcm_viewport_os.path.exists(temporary_path):
                try:
                    _hcm_viewport_os.remove(temporary_path)
                except OSError:
                    pass
        size = int(_hcm_viewport_os.path.getsize(target))
        self._mutation_events.append({
            "kind": "viewport.capture", "helper": "ctx.viewport.capture",
            "output_path": target, "pane_name": viewer_context["pane_name"],
        })
        return {
            "file": {"path": target, "bytes": size}, "frame": frame,
            "width": width, "height": height, "overwrite": overwrite,
            "existed_before": existed_before, "max_bytes": maximum,
            "viewer": viewer_context, "hip_saved": False,
        }
'''
