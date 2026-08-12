from __future__ import annotations

import socket
import uuid
import os
from pathlib import Path

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


def test_live_hda_promotion_apply_is_durable_and_cleans_up(tmp_path: Path) -> None:
    """Exercise durable promotion only in a pre-dirty live HIP session.

    HOM exposes no supported API for restoring a clean HIP's dirty bit without
    saving or reopening the scene.  This guard therefore preserves an existing
    dirty state (True) and skips a pristine artist scene rather than altering
    it merely for a test.
    """

    controller = Controller()
    dirty = controller.run("result.emit(hou.hipFile.hasUnsavedChanges())")
    assert dirty["ok"] is True
    if not dirty["data"]["value"]:
        pytest.skip("Live HDA mutation test requires an already-dirty HIP to preserve its dirty state without saving")

    token = uuid.uuid4().hex[:12]
    asset_name = "codemode_promote_" + token
    asset_type = "codemode::promote_{}::1.0".format(token)
    instance_path = "/obj/" + asset_name
    fresh_name = asset_name + "_fresh"
    fresh_path = "/obj/" + fresh_name
    library = tmp_path / (asset_name + ".hda")
    source = r'''
import glob
import hashlib
import os

parent = hou.node('/obj')
asset = None
fresh = None
out = {'dirty_before': hou.hipFile.hasUnsavedChanges()}
try:
    root = parent.createNode('subnet', args['asset_name'])
    internal = root.createNode('null', 'internal')
    internal_group = internal.parmTemplateGroup()
    internal_group.append(hou.FloatParmTemplate('gain', 'Gain', 1, default_value=(2.5,)))
    internal_group.append(hou.FloatParmTemplate('sentinel', 'Sentinel', 1, default_value=(0.0,)))
    internal.setParmTemplateGroup(internal_group)
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
        raise RuntimeError('new disposable asset could not be unlocked')
    # This is an existing unlocked edit that must survive the synchronization
    # performed after the promotion interface is added.
    asset.parm('internal/sentinel').set(7.25)
    definition = asset.type().definition()
    applied = ctx.hda.apply_promotion(
        asset,
        'internal/gain',
        ['ui_gain'],
        allow_library_write=True,
        owned_library=args['library'],
        create_backup=False,
    )
    outer = asset.parm('ui_gain')
    internal_after = asset.parm('internal/gain')
    # A fresh locked instance proves that updateFromNode persisted both the
    # interface and the reference into the definition, not just the instance.
    fresh = parent.createNode(args['asset_type'], args['fresh_name'])
    fresh_outer = fresh.parm('ui_gain')
    fresh_internal = fresh.parm('internal/gain')
    fresh_sentinel = fresh.parm('internal/sentinel')
    contents = definition.sections().get('Contents.gz')
    with open(args['library'], 'rb') as handle:
        library_sha256 = hashlib.sha256(handle.read()).hexdigest()
    out.update({
        'applied': applied,
        'outer_exists': outer is not None,
        'instance_expression': internal_after.expression(),
        'fresh_outer_exists': fresh_outer is not None,
        'fresh_expression': fresh_internal.expression(),
        'fresh_sentinel_value': fresh_sentinel.eval(),
        'fresh_locked': fresh.isLockedHDA(),
        'definition_contents_section': contents is not None,
        'definition_library': definition.libraryFilePath(),
        'library_exists': os.path.isfile(args['library']),
        'library_sha256': library_sha256,
        'dirty_during': hou.hipFile.hasUnsavedChanges(),
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
        hou.hda.uninstallFile(args['library'])
    except Exception:
        pass
    for candidate in glob.glob(args['library'] + '*'):
        if os.path.isfile(candidate):
            try:
                os.remove(candidate)
            except OSError:
                pass
    out['instance_removed'] = hou.node(args['instance_path']) is None
    out['fresh_removed'] = hou.node(args['fresh_path']) is None
    out['library_removed'] = not os.path.exists(args['library'])
    out['dirty_after_cleanup'] = hou.hipFile.hasUnsavedChanges()
result.emit(out)
'''

    response = controller.run(
        source,
        args={
            "asset_name": asset_name,
            "asset_type": asset_type,
            "library": str(library),
            "instance_path": instance_path,
            "fresh_name": fresh_name,
            "fresh_path": fresh_path,
        },
        policy={"label": "Houdini Code Mode durable HDA promotion proof"},
    )

    assert response["ok"] is True, response.get("error")
    value = response["data"]["value"]
    assert value["outer_exists"] is True, value
    assert value["fresh_outer_exists"] is True
    assert value["fresh_locked"] is True
    assert value["instance_expression"].startswith('ch("../ui_gain")')
    assert value["fresh_expression"].startswith('ch("../ui_gain")')
    assert value["fresh_sentinel_value"] == pytest.approx(7.25)
    assert value["definition_contents_section"] is True
    assert os.path.normcase(os.path.normpath(value["definition_library"])) == os.path.normcase(os.path.normpath(str(library)))
    assert value["library_exists"] is True
    assert len(value["library_sha256"]) == 64
    assert value["applied"]["library"]["before"]["sha256"] != value["applied"]["library"]["after"]["sha256"]
    assert [event["kind"] for event in value["applied"]["events"]] == [
        "preflight",
        "definition.updateFromNode_checkpoint",
        "preflight_recheck",
        "definition.setParmTemplateGroup",
        "node.matchCurrentDefinition",
        "node.allowEditingOfContents",
        "internal.setExpression_reference",
        "definition.updateFromNode",
    ]
    assert value["applied"]["events"][-1]["status"] == "complete"
    assert value["dirty_before"] is True
    assert value["dirty_during"] is True
    assert value["dirty_after_cleanup"] is True
    assert value["instance_removed"] is True
    assert value["fresh_removed"] is True
    assert value["library_removed"] is True
    assert not library.exists()
