from __future__ import annotations

import os
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


pytestmark = [pytest.mark.live, pytest.mark.skipif(not _server_available(), reason="Live Houdini hrpyc server not available on localhost:18811")]


def test_live_owned_hda_tool_set_inspect_remove_and_cleanup(tmp_path: Path) -> None:
    controller = Controller()
    dirty = controller.run("result.emit(hou.hipFile.hasUnsavedChanges())")
    assert dirty["ok"] is True
    if not dirty["data"]["value"]:
        pytest.skip("Live HDA mutation test requires an already-dirty HIP to preserve its dirty state without saving")

    token = uuid.uuid4().hex[:12]
    asset_name, asset_type = "codemode_tools_" + token, "codemode::tools_{}::1.0".format(token)
    library = tmp_path / (asset_name + ".hda")
    source = r'''
import glob
import os
parent = hou.node("/obj")
asset = None
backup_path = None
out = {"dirty_before": hou.hipFile.hasUnsavedChanges()}
try:
    root = parent.createNode("subnet", args["asset_name"])
    asset = root.createDigitalAsset(name=args["asset_type"], hda_file_name=args["library"], description=args["asset_name"], save_as_embedded=False, ignore_external_references=True, change_node_type=True, create_backup=False, install_path=args["library"])
    service = ctx.hda_tools
    plan = service.plan(asset, "set", "Code Mode/Test", "SOP", args["library"])
    set_result = service.set(asset, "Code Mode/Test", "SOP", args["library"], allow_library_write=True, create_backup=True)
    backup_path = set_result["library"]["backup"]["path"]
    after_set = service.inspect(asset)
    remove_result = service.remove(asset, args["library"], allow_library_write=True, create_backup=False)
    after_remove = service.inspect(asset)
    out.update({"plan": plan, "set": set_result, "after_set": after_set, "remove": remove_result, "after_remove": after_remove, "library_exists": os.path.isfile(args["library"]), "backup_exists": os.path.isfile(backup_path), "dirty_during": hou.hipFile.hasUnsavedChanges()})
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
    out["instance_removed"] = hou.node("/obj/" + args["asset_name"]) is None
    out["library_removed"] = not os.path.exists(args["library"])
    out["backup_removed"] = not backup_path or not os.path.exists(backup_path)
    out["dirty_after_cleanup"] = hou.hipFile.hasUnsavedChanges()
result.emit(out)
'''
    response = controller.run(source, args={"asset_name": asset_name, "asset_type": asset_type, "library": str(library)}, policy={"label": "Houdini Code Mode owned HDA tool proof"})
    assert response["ok"] is True, response.get("error")
    value = response["data"]["value"]
    assert value["plan"]["ok"] is True
    assert value["after_set"]["tools_shelf"]["present"] is True
    assert value["after_set"]["tools"]["count"] >= 1
    assert value["after_remove"]["tools_shelf"]["present"] is False
    assert value["set"]["library"]["before"]["sha256"] != value["set"]["library"]["after"]["sha256"]
    assert [item["kind"] for item in value["set"]["events"]] == ["hda.tools.preflight", "hda.tools.backup", "hda.definition.addSection"]
    assert [item["kind"] for item in value["remove"]["events"]] == ["hda.tools.preflight", "hda.definition.removeSection"]
    assert value["library_exists"] is True and value["backup_exists"] is True
    assert value["instance_removed"] is True and value["library_removed"] is True and value["backup_removed"] is True
    assert value["dirty_before"] is True and value["dirty_during"] is True and value["dirty_after_cleanup"] is True
    assert not library.exists()
