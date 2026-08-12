"""Live proof for the public owned-library HDA update primitive."""

from __future__ import annotations

from pathlib import Path
import socket
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


_LIVE_PROGRAM = r'''
import glob
import os

parent = hou.node('/obj')
asset = None
fresh = None
out = {'dirty_before': hou.hipFile.hasUnsavedChanges()}
try:
    old = parent.node(args['asset_name'])
    if old is not None:
        old.destroy()
    root = parent.createNode('subnet', args['asset_name'])
    root.createNode('null', 'OUT').setDisplayFlag(True)
    asset = root.createDigitalAsset(
        name=args['asset_type'],
        hda_file_name=args['library'],
        description=args['asset_name'],
        save_as_embedded=False,
        ignore_external_references=True,
        change_node_type=True,
        create_backup=False,
        install_path=args['library'],
    )
    asset.allowEditingOfContents()
    if asset.isLockedHDA():
        raise RuntimeError('disposable HDA instance could not be unlocked')
    asset.createNode('null', 'UPDATED')
    definition = asset.type().definition()
    definition.addSection('Readme', 'owned-update-preserve')
    definition.addSection('Tools.shelf', '<shelfDocument/>')
    owned = ctx.hda_update
    applied = owned.update_owned(
        asset,
        args['library'],
        allow_library_write=True,
        contents=True,
        interface=True,
        preserve_sections=True,
        preserve_tools=False,
        create_backup=True,
        match_current=True,
        validate=False,
    )
    fresh = parent.createNode(args['asset_type'], args['fresh_name'])
    validation = ctx.hda.validate(fresh, fresh=True, dry_run=False, max_items=100)
    readme = definition.sections().get('Readme')
    tools = definition.sections().get('Tools.shelf')
    out.update({
        'applied': applied,
        'events': applied['events'],
        'fresh_locked': fresh.isLockedHDA(),
        'fresh_updated_exists': fresh.node('UPDATED') is not None,
        'readme_contents': readme.contents() if readme is not None else None,
        'tools_contents': tools.contents() if tools is not None else None,
        'validation': validation,
        'library_exists': os.path.isfile(args['library']),
        'backup_exists': os.path.isfile(applied['library']['backup']['path']),
        'dirty_during': hou.hipFile.hasUnsavedChanges(),
        'hip_saved': False,
    })
finally:
    if fresh is not None:
        try:
            fresh.destroy()
        except Exception:
            pass
    if asset is not None:
        try:
            asset.destroy()
        except Exception:
            pass
    try:
        hou.hda.uninstallFile(args['library'], change_oplibraries_file=False)
    except Exception:
        pass
    candidates = [args['library']]
    candidates.extend(glob.glob(os.path.join(
        os.path.dirname(args['library']),
        '.' + os.path.basename(args['library']) + '.hcm-backup-*',
    )))
    for candidate in candidates:
        if os.path.isfile(candidate):
            try:
                os.remove(candidate)
            except OSError:
                pass
    out['asset_removed'] = hou.node(args['asset_path']) is None
    out['fresh_removed'] = hou.node(args['fresh_path']) is None
    out['library_removed'] = not os.path.exists(args['library'])
    out['backup_removed'] = not glob.glob(os.path.join(
        os.path.dirname(args['library']),
        '.' + os.path.basename(args['library']) + '.hcm-backup-*',
    ))
    out['dirty_after_cleanup'] = hou.hipFile.hasUnsavedChanges()
result.emit(out)
'''


def test_live_update_owned_persists_contents_and_preserves_sections(tmp_path: Path) -> None:
    """Use a disposable, already-dirty session; never save its HIP."""
    controller = Controller()
    doctor = controller.doctor()
    assert doctor["ok"] is True
    hip_path = Path(doctor["data"]["value"]["hip_file"])
    hip_mtime_before = hip_path.stat().st_mtime_ns if hip_path.is_file() else None
    dirty = controller.run("result.emit(hou.hipFile.hasUnsavedChanges())")
    assert dirty["ok"] is True
    if not dirty["data"]["value"]:
        pytest.skip("Live HDA mutation proof requires an already-dirty HIP to preserve its state without saving")

    token = uuid.uuid4().hex[:12]
    asset_name = f"codemode_owned_update_{token}"
    fresh_name = asset_name + "_fresh"
    asset_type = f"codemode::owned_update_{token}::1.0"
    library = tmp_path / f"{asset_name}.hda"
    response = controller.run(
        _LIVE_PROGRAM,
        args={
            "asset_name": asset_name,
            "fresh_name": fresh_name,
            "asset_path": f"/obj/{asset_name}",
            "fresh_path": f"/obj/{fresh_name}",
            "asset_type": asset_type,
            "library": str(library),
        },
        policy={"label": "Houdini Code Mode owned HDA update proof"},
    )

    assert response["ok"] is True, response.get("error")
    value = response["data"]["value"]
    assert value["fresh_locked"] is True
    assert value["fresh_updated_exists"] is True
    assert value["readme_contents"] == "owned-update-preserve"
    assert value["tools_contents"] == "<shelfDocument/>"
    assert value["validation"]["ok"] is True
    assert value["library_exists"] is True
    assert value["backup_exists"] is True
    assert value["hip_saved"] is False
    assert value["applied"]["library"]["before"]["sha256"] != value["applied"]["library"]["after"]["sha256"]
    assert value["applied"]["library"]["install_called"] is False
    assert value["applied"]["library"]["hda_definition_save_called"] is False
    assert value["applied"]["library"]["hip_save_called"] is False
    event_kinds = [event["kind"] for event in value["events"]]
    assert event_kinds[:4] == [
        "hda.update_owned.preflight",
        "hda.update_owned.backup",
        "hda.update_owned.updateFromNode",
        "hda.update_owned.setParmTemplateGroup",
    ]
    assert event_kinds[-1] == "hda.update_owned.matchCurrentDefinition"
    restored = {
        event["name"] for event in value["events"]
        if event["kind"] == "hda.update_owned.restore_section"
    }
    # H22 retains the Tools.shelf payload across updateFromNode itself; the
    # readme is the explicit non-managed section restored by the helper.
    assert "Readme" in restored
    assert value["asset_removed"] is True
    assert value["fresh_removed"] is True
    assert value["library_removed"] is True
    assert value["backup_removed"] is True
    assert value["dirty_before"] is True
    assert value["dirty_during"] is True
    assert value["dirty_after_cleanup"] is True
    assert library.exists() is False
    if hip_mtime_before is not None:
        assert hip_path.stat().st_mtime_ns == hip_mtime_before
