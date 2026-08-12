"""Live proof for the public staged HDA package-copy extension."""

from __future__ import annotations

import socket
from pathlib import Path
import uuid

import pytest

from houdini_codemode.controller import Controller


def _server_available(host: str = "localhost", port: int = 18811) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not _server_available(),
        reason="Live Houdini hrpyc server not available on localhost:18811",
    ),
]


def test_live_staged_hda_package_copy_preserves_rejected_target_and_cleans_up(
    tmp_path: Path,
) -> None:
    """Create and uninstall a disposable source HDA; never install the target."""
    token = uuid.uuid4().hex[:12]
    source_library = tmp_path / f"codemode-hda-package-source-{token}.hda"
    target_library = tmp_path / f"codemode-hda-package-target-{token}.hda"
    target_type = f"codemode::package_probe_{token}::1.0"
    node_name = f"codemode_hda_package_{token}"
    controller = Controller()
    doctor = controller.doctor()
    assert doctor["ok"] is True
    hip_path = Path(doctor["data"]["value"]["hip_file"])
    hip_mtime_before = hip_path.stat().st_mtime_ns if hip_path.is_file() else None

    program = r'''
import glob
import hashlib
import os

def file_digest(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return {'size': os.path.getsize(path), 'sha256': digest.hexdigest()}

parent = hou.node('/obj')
asset = None
created_source_loaded = False
copy_result = None
rejected_error = None
preserved_after_rejection = False
temporary_files = []
cleanup = {}
dirty_before = hou.hipFile.hasUnsavedChanges()
try:
    old = parent.node(args['node_name'])
    if old is not None:
        old.destroy()
    subnet = parent.createNode('subnet', args['node_name'])
    subnet.createNode('null', 'OUT').setDisplayFlag(True)
    asset = subnet.createDigitalAsset(
        name=args['target_type'],
        hda_file_name=args['source_library'],
        description='Code Mode package probe',
        change_node_type=True,
        create_backup=False,
    )
    created_source_loaded = os.path.realpath(args['source_library']) in {
        os.path.realpath(path) for path in hou.hda.loadedFiles()
    }
    copy_result = ctx.hda.package_copy(asset, args['target_library'])
    before_rejection = copy_result['after']
    try:
        ctx.hda.package_copy(asset, args['target_library'])
    except Exception as exc:
        rejected_error = {'type': exc.__class__.__name__, 'message': str(exc)}
    after_rejection = file_digest(args['target_library'])
    preserved_after_rejection = (
        before_rejection['size'] == after_rejection['size']
        and before_rejection['sha256'] == after_rejection['sha256']
    )
    temporary_files = glob.glob(
        os.path.join(
            os.path.dirname(args['target_library']),
            '.' + os.path.splitext(os.path.basename(args['target_library']))[0]
            + '.hcm-*' + os.path.splitext(args['target_library'])[1],
        )
    )
finally:
    if asset is not None:
        try:
            asset.destroy()
        except Exception:
            pass
    try:
        hou.hda.uninstallFile(args['source_library'], change_oplibraries_file=False)
    except Exception as exc:
        cleanup['uninstall_error'] = str(exc)
    for path in (args['source_library'], args['target_library']):
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError as exc:
                cleanup.setdefault('remove_errors', []).append(str(exc))
    target_stem, target_extension = os.path.splitext(
        os.path.basename(args['target_library'])
    )
    for path in glob.glob(os.path.join(
        os.path.dirname(args['target_library']),
        '.' + target_stem + '.hcm-*' + target_extension,
    )):
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError as exc:
                cleanup.setdefault('remove_errors', []).append(str(exc))
    cleanup['source_exists'] = os.path.exists(args['source_library'])
    cleanup['target_exists'] = os.path.exists(args['target_library'])
    cleanup['source_loaded'] = os.path.realpath(args['source_library']) in {
        os.path.realpath(path) for path in hou.hda.loadedFiles()
    }
    cleanup['target_loaded'] = os.path.realpath(args['target_library']) in {
        os.path.realpath(path) for path in hou.hda.loadedFiles()
    }
    cleanup['node_exists'] = hou.node(args['node_path']) is not None

result.emit({
    'copy': copy_result,
    'created_source_loaded': created_source_loaded,
    'rejected_error': rejected_error,
    'preserved_after_rejection': preserved_after_rejection,
    'temporary_files': temporary_files,
    'dirty_before': dirty_before,
    'dirty_after': hou.hipFile.hasUnsavedChanges(),
    'cleanup': cleanup,
})
'''

    try:
        response = controller.run(
            program,
            args={
                "node_name": node_name,
                "node_path": f"/obj/{node_name}",
                "target_type": target_type,
                "source_library": str(source_library),
                "target_library": str(target_library),
            },
            policy={"label": "Houdini Code Mode staged HDA package proof"},
        )
        assert response["ok"] is True, response.get("error")
        value = response["data"]["value"]
        assert value["created_source_loaded"] is True
        assert value["copy"]["after"]["exists"] is True
        assert value["copy"]["library_installed"] is False
        assert value["copy"]["instance_changed"] is False
        assert value["copy"]["hip_saved"] is False
        assert value["rejected_error"]["type"] in {"FileExistsError", "ValueError"}
        assert value["preserved_after_rejection"] is True
        assert value["temporary_files"] == []
        assert response["meta"]["mutation"]["events"][0]["kind"] == "hda.library_package"
        assert response["meta"]["mutation"]["events"][0]["installed_library"] is False
        assert value["cleanup"] == {
            "source_exists": False,
            "target_exists": False,
            "source_loaded": False,
            "target_loaded": False,
            "node_exists": False,
        }
    finally:
        # Defense in depth if the in-Houdini cleanup failed before emitting.
        for path in tmp_path.glob(f"codemode-hda-package-*-{token}*"):
            if path.is_file():
                path.unlink()

    if hip_mtime_before is not None:
        assert hip_path.stat().st_mtime_ns == hip_mtime_before
