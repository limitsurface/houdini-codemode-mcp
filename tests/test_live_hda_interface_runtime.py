from __future__ import annotations

import os
from pathlib import Path
import socket
import uuid
import pytest
from houdini_codemode.controller import Controller

def _available():
    try:
        with socket.create_connection(("localhost", 18811), timeout=0.5): return True
    except OSError: return False

pytestmark = [pytest.mark.live, pytest.mark.skipif(not _available(), reason="Live Houdini hrpyc server not available on localhost:18811")]

def test_live_interface_schema_fresh_instance_and_cleanup(tmp_path: Path) -> None:
    controller = Controller(); dirty = controller.run("result.emit(hou.hipFile.hasUnsavedChanges())")
    assert dirty["ok"]
    if not dirty["data"]["value"]: pytest.skip("Live HDA mutation test requires an already-dirty HIP to preserve its dirty state without saving")
    token = uuid.uuid4().hex[:12]; name = "codemode_interface_" + token; asset_type = "codemode::interface_{}::1.0".format(token); library = tmp_path / (name + ".hda")
    source = r'''
import glob
import os
parent = hou.node("/obj"); asset = None; backup_path = None; out = {"dirty_before": hou.hipFile.hasUnsavedChanges()}
try:
    root = parent.createNode("subnet", args["name"])
    asset = root.createDigitalAsset(name=args["asset_type"], hda_file_name=args["library"], description=args["name"], save_as_embedded=False, ignore_external_references=True, change_node_type=True, create_backup=False, install_path=args["library"])
    asset.allowEditingOfContents(); asset.createNode("null", "checkpoint_sentinel")
    items = [{"name":"gain","type":"float","components":3,"default":[1.0,2.0,3.0]},{"name":"divisions","type":"int","default":[4]},{"name":"title","type":"string","default":["Code Mode"]},{"name":"enabled","type":"toggle","default":True},{"name":"mode","type":"menu","menu_items":["fast","safe"],"menu_labels":["Fast","Safe"],"default":1}]
    service = ctx.hda_interface; plan = service.plan(asset, items, args["library"]); applied = service.apply(asset, items, args["library"], allow_library_write=True, create_backup=True); backup_path = applied["library"]["backup"]["path"]
    asset.allowEditingOfContents(); asset.parmTuple("gain").set((7.0,8.0,9.0)); asset.parm("enabled").set(0); asset.parm("mode").set(0)
    defaults_plan = service.plan_defaults_from_current(asset, ["gain", "enabled", "mode"], args["library"])
    defaults = service.set_defaults_from_current(asset, ["gain", "enabled", "mode"], args["library"], allow_library_write=True, create_backup=False)
    fresh = parent.createNode(args["asset_type"], args["name"] + "_fresh"); fresh_path = fresh.path()
    out.update({"plan":plan,"applied":applied,"defaults_plan":defaults_plan,"defaults":defaults,"fresh_locked":fresh.isLockedHDA(),"fresh_gain":list(fresh.parmTuple("gain").eval()),"fresh_divisions":fresh.parm("divisions").eval(),"fresh_title":fresh.parm("title").eval(),"fresh_enabled":fresh.parm("enabled").eval(),"fresh_mode":fresh.parm("mode").eval(),"fresh_checkpoint":fresh.node("checkpoint_sentinel") is not None,"library_exists":os.path.isfile(args["library"]),"backup_exists":os.path.isfile(backup_path),"dirty_during":hou.hipFile.hasUnsavedChanges()})
    fresh.destroy(); out["fresh_removed"] = hou.node(fresh_path) is None
finally:
    if asset is not None:
        try: asset.destroy()
        except Exception: pass
    try: hou.hda.uninstallFile(args["library"])
    except Exception: pass
    for candidate in glob.glob(args["library"] + "*"):
        if os.path.isfile(candidate):
            try: os.remove(candidate)
            except OSError: pass
    if backup_path and os.path.isfile(backup_path):
        try: os.remove(backup_path)
        except OSError: pass
    out["instance_removed"] = hou.node("/obj/" + args["name"]) is None; out["library_removed"] = not os.path.exists(args["library"]); out["backup_removed"] = not backup_path or not os.path.exists(backup_path); out["dirty_after_cleanup"] = hou.hipFile.hasUnsavedChanges()
result.emit(out)
'''
    response = controller.run(source, args={"name":name,"asset_type":asset_type,"library":str(library)}, policy={"label":"Houdini Code Mode HDA interface proof"})
    assert response["ok"] is True, response.get("error")
    value = response["data"]["value"]
    assert value["plan"]["ok"] and value["fresh_locked"] and value["fresh_checkpoint"]
    assert value["defaults_plan"]["ok"] is True
    assert value["fresh_gain"] == [7.0,8.0,9.0] and value["fresh_divisions"] == 4 and value["fresh_title"] == "Code Mode" and bool(value["fresh_enabled"]) is False and value["fresh_mode"] in ("fast",0)
    assert value["applied"]["library"]["before"]["sha256"] != value["applied"]["library"]["after"]["sha256"]
    assert [event["kind"] for event in value["applied"]["events"]] == ["hda.interface.preflight","hda.interface.backup","hda.interface.content_checkpoint","hda.interface.set_group","hda.interface.match_current"]
    assert [event["kind"] for event in value["defaults"]["events"]] == ["hda.interface.defaults.preflight","hda.interface.defaults.content_checkpoint","hda.interface.defaults.set_group","hda.interface.defaults.match_current"]
    assert value["library_exists"] and value["backup_exists"] and value["fresh_removed"] and value["instance_removed"] and value["library_removed"] and value["backup_removed"]
    assert value["dirty_before"] and value["dirty_during"] and value["dirty_after_cleanup"]
