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

def test_live_create_owned_disposable_subnet_and_cleanup(tmp_path: Path) -> None:
    controller = Controller(); dirty = controller.run("result.emit(hou.hipFile.hasUnsavedChanges())")
    assert dirty["ok"]
    if not dirty["data"]["value"]: pytest.skip("Live HDA mutation test requires an already-dirty HIP to preserve its dirty state without saving")
    token = uuid.uuid4().hex[:12]; name = "codemode_create_" + token; asset_type = "codemode::create_{}".format(token); library = tmp_path / (name + ".hda")
    source = r'''
import glob
import os
parent = hou.node("/obj"); source = None; out = {"dirty_before": hou.hipFile.hasUnsavedChanges()}
try:
    source = parent.createNode("subnet", args["name"])
    service = ctx.hda_create; plan = service.plan(source, args["asset_type"], args["name"], args["library"], 1, 2)
    created = service.create_owned(source, args["asset_type"], args["name"], args["library"], 1, 2, allow_library_write=True)
    source = hou.node(created["node_path"]); definition = source.type().definition(); fresh = parent.createNode(args["asset_type"], args["name"] + "_fresh"); fresh_path = fresh.path(); fresh.destroy()
    out.update({"plan":plan,"created":created,"source_type":source.type().name(),"definition_library":definition.libraryFilePath(),"min_inputs":definition.minNumInputs(),"max_inputs":definition.maxNumInputs(),"fresh_removed":hou.node(fresh_path) is None,"library_exists":os.path.isfile(args["library"]),"dirty_during":hou.hipFile.hasUnsavedChanges()})
finally:
    if source is not None:
        try: source.destroy()
        except Exception: pass
    try: hou.hda.uninstallFile(args["library"])
    except Exception: pass
    for candidate in glob.glob(args["library"] + "*"):
        if os.path.isfile(candidate):
            try: os.remove(candidate)
            except OSError: pass
    out["source_removed"] = hou.node("/obj/" + args["name"]) is None; out["library_removed"] = not os.path.exists(args["library"]); out["dirty_after_cleanup"] = hou.hipFile.hasUnsavedChanges()
result.emit(out)
'''
    response = controller.run(source, args={"name":name,"asset_type":asset_type,"library":str(library)}, policy={"label":"Houdini Code Mode owned HDA create proof"})
    assert response["ok"] is True, response.get("error")
    value = response["data"]["value"]
    assert value["plan"]["ok"] and value["source_type"] == asset_type and os.path.normcase(os.path.realpath(value["definition_library"])) == os.path.normcase(os.path.realpath(str(library)))
    assert value["min_inputs"] == 1 and value["max_inputs"] == 2 and value["fresh_removed"] and value["library_exists"]
    assert value["created"]["library"]["before"]["exists"] is False and value["created"]["library"]["after"]["exists"] is True
    assert value["created"]["library"]["installed_library"] is True
    assert value["source_removed"] and value["library_removed"] and value["dirty_before"] and value["dirty_during"] and value["dirty_after_cleanup"]
