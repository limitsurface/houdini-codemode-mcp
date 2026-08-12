"""Live proof for the public script-suppressed recipe extension."""

from __future__ import annotations

import json
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
import os

parent = hou.node('/obj')
root = None
cleanup = {}
node_recipe_key = args['node_recipe_key']
parm_recipe_key = args['parm_recipe_key']
try:
    existing = parent.node(args['root_name'])
    if existing is not None:
        existing.destroy()
    for sentinel_name in args['sentinel_names']:
        sentinel = parent.node(sentinel_name)
        if sentinel is not None:
            sentinel.destroy()

    root = parent.createNode('geo', args['root_name'])
    source = root.createNode('box', 'source')
    source.parmTuple('size').set((2.75, 1.0, 1.0))
    node_target = root.createNode('box', 'node_target')
    parm_target = root.createNode('box', 'parm_target')
    decoy = root.createNode('box', 'decoy')
    decoy.parm('sizex').set(8.0)
    node_target.setDisplayFlag(True)
    parm_target.setRenderFlag(True)

    pre_script = (
        "hou.node('/obj').createNode('null', '" + args['sentinel_names'][0] + "')"
    )
    post_script = (
        "hou.node('/obj').createNode('null', '" + args['sentinel_names'][1] + "')"
    )
    hou.data.saveNodePresetRecipe(
        node_recipe_key,
        'Code Mode disposable node-preset recipe proof',
        args['library_path'],
        source,
        parms=(source.parmTuple('size'),),
        visible=False,
        prescript=pre_script,
        postscript=post_script,
    )
    hou.data.saveParmPresetRecipe(
        parm_recipe_key,
        'Code Mode disposable parm-preset recipe proof',
        args['library_path'],
        source.parmTuple('size'),
        visible=False,
        prescript=pre_script,
        postscript=post_script,
    )

    recipes = ctx.recipes
    before_discovery = {
        'node_target_sizex': node_target.parm('sizex').eval(),
        'parm_target_sizex': parm_target.parm('sizex').eval(),
        'decoy_sizex': decoy.parm('sizex').eval(),
        'sentinels': [parent.node(name) is not None for name in args['sentinel_names']],
        'display': node_target.isDisplayFlagSet(),
        'render': parm_target.isRenderFlagSet(),
        'hip_mtime_ns': (
            os.stat(args['hip_path']).st_mtime_ns if os.path.isfile(args['hip_path']) else None
        ),
    }
    listed = recipes.list(category='node-preset', visible_only=False, max_items=1000)
    node_discovery = recipes.get(node_recipe_key)
    parm_discovery = recipes.get(parm_recipe_key)
    after_discovery = {
        'node_target_sizex': node_target.parm('sizex').eval(),
        'parm_target_sizex': parm_target.parm('sizex').eval(),
        'decoy_sizex': decoy.parm('sizex').eval(),
        'sentinels': [parent.node(name) is not None for name in args['sentinel_names']],
        'display': node_target.isDisplayFlagSet(),
        'render': parm_target.isRenderFlagSet(),
        'hip_mtime_ns': (
            os.stat(args['hip_path']).st_mtime_ns if os.path.isfile(args['hip_path']) else None
        ),
    }

    node_applied = recipes.apply_node_preset(node_recipe_key, node_target.path())
    parm_applied = recipes.apply_parm_preset(
        parm_recipe_key,
        parm_target.parm('sizex').path(),
    )
    result.emit({
        'discovery_unchanged': before_discovery == after_discovery,
        'listed_keys': [row['key'] for row in listed['items'] if row['key'] == node_recipe_key],
        'node_discovery': node_discovery,
        'parm_discovery': parm_discovery,
        'node_applied': node_applied,
        'parm_applied': parm_applied,
        'node_target': {
            'path': node_target.path(),
            'sizex': node_target.parm('sizex').eval(),
            'display': node_target.isDisplayFlagSet(),
        },
        'parm_target': {
            'path': parm_target.path(),
            'sizex': parm_target.parm('sizex').eval(),
            'render': parm_target.isRenderFlagSet(),
        },
        'decoy': {'path': decoy.path(), 'sizex': decoy.parm('sizex').eval()},
        'sentinels_created': [parent.node(name) is not None for name in args['sentinel_names']],
        'library_exists_during_run': os.path.isfile(args['library_path']),
        'hip_saved': False,
    })
finally:
    if root is not None:
        root.destroy()
    cleanup['root_removed'] = parent.node(args['root_name']) is None
    for sentinel_name in args['sentinel_names']:
        sentinel = parent.node(sentinel_name)
        if sentinel is not None:
            sentinel.destroy()
    cleanup['sentinels_removed'] = all(
        parent.node(name) is None for name in args['sentinel_names']
    )
    try:
        hou.hda.uninstallFile(args['library_path'], change_oplibraries_file=False)
        cleanup['library_uninstalled'] = True
    except Exception as exc:
        cleanup['uninstall_error'] = str(exc)
    if os.path.isfile(args['library_path']):
        os.remove(args['library_path'])
    cleanup['library_removed'] = not os.path.exists(args['library_path'])
'''


def test_live_recipe_discovery_and_safe_preset_apply_cleanup(tmp_path: Path) -> None:
    token = uuid.uuid4().hex[:12]
    root_name = f"codemode_recipe_probe_{token}"
    node_recipe_key = f"recipeprobe{token}node"
    parm_recipe_key = f"recipeprobe{token}parm"
    sentinel_names = [f"recipepre{token}", f"recipepost{token}"]
    library_path = tmp_path / f"codemode-recipe-probe-{token}.hda"
    controller = Controller()
    doctor = controller.doctor()
    assert doctor["ok"] is True
    hip_path = Path(doctor["data"]["value"]["hip_file"])
    hip_mtime_before = hip_path.stat().st_mtime_ns if hip_path.is_file() else None

    response = controller.run(
        _LIVE_PROGRAM,
        args={
            "root_name": root_name,
            "node_recipe_key": node_recipe_key,
            "parm_recipe_key": parm_recipe_key,
            "sentinel_names": sentinel_names,
            "library_path": str(library_path),
            "hip_path": str(hip_path),
        },
        policy={"label": "Houdini Code Mode safe recipe preset proof"},
    )

    try:
        assert response["ok"] is True, response.get("error")
        value = response["data"]["value"]
        assert value["discovery_unchanged"] is True
        assert value["listed_keys"] == [node_recipe_key]
        assert value["node_discovery"]["category"] == "node-preset"
        assert value["parm_discovery"]["category"] == "parm-preset"
        assert value["node_discovery"]["scripts"] == {
            "prescript_present": True,
            "postscript_present": True,
        }
        assert value["parm_discovery"]["scripts"] == {
            "prescript_present": True,
            "postscript_present": True,
        }
        discovery_json = json.dumps(
            {"node": value["node_discovery"], "parm": value["parm_discovery"]},
            sort_keys=True,
        )
        assert sentinel_names[0] not in discovery_json
        assert sentinel_names[1] not in discovery_json
        assert value["node_target"] == {
            "path": f"/obj/{root_name}/node_target",
            "sizex": pytest.approx(2.75),
            "display": True,
        }
        assert value["parm_target"] == {
            "path": f"/obj/{root_name}/parm_target",
            "sizex": pytest.approx(2.75),
            "render": True,
        }
        assert value["decoy"] == {
            "path": f"/obj/{root_name}/decoy",
            "sizex": pytest.approx(8.0),
        }
        assert value["node_applied"]["safety"] == {
            "prescript": False,
            "postscript": False,
            "parmtemplates": False,
            "children": False,
            "editables": False,
            "skip_notes": True,
        }
        assert value["parm_applied"]["safety"] == {"prescript": False, "postscript": False}
        assert value["sentinels_created"] == [False, False]
        assert value["library_exists_during_run"] is True
        assert value["hip_saved"] is False
    finally:
        # Defense in depth when Houdini raised before the in-runtime finally.
        if library_path.exists():
            library_path.unlink()

    cleanup = controller.run(
        "result.emit({path: hou.node(path) is None for path in args['paths']})",
        args={
            "paths": [
                f"/obj/{root_name}",
                *(f"/obj/{name}" for name in sentinel_names),
            ]
        },
    )
    assert cleanup["ok"] is True
    assert all(cleanup["data"]["value"].values())
    assert library_path.exists() is False
    if hip_mtime_before is not None:
        assert hip_path.stat().st_mtime_ns == hip_mtime_before
