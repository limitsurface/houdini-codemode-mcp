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


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not _server_available(), reason="Live Houdini hrpyc server not available on localhost:18811"),
]


def test_live_owned_plain_section_is_durable_and_cleans_up(tmp_path: Path) -> None:
    """Use one disposable definition/instance; do not save the artist HIP."""

    controller = Controller()
    dirty = controller.run("result.emit(hou.hipFile.hasUnsavedChanges())")
    assert dirty["ok"] is True
    if not dirty["data"]["value"]:
        pytest.skip("Live HDA mutation test requires an already-dirty HIP to preserve its dirty state without saving")

    token = uuid.uuid4().hex[:12]
    asset_name = "codemode_sections_" + token
    asset_type = "codemode::sections_{}::1.0".format(token)
    instance_path = "/obj/" + asset_name
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
    asset = root.createDigitalAsset(
        name=args["asset_type"], hda_file_name=args["library"],
        description=args["asset_name"], save_as_embedded=False,
        ignore_external_references=True, change_node_type=True,
        create_backup=False, install_path=args["library"],
    )
    service = ctx.hda_sections
    plan = service.plan(asset, "Readme", "set", "plain text", args["library"])
    applied = service.apply(
        asset, "Readme", "set", "plain text", args["library"],
        allow_library_write=True, create_backup=True,
    )
    backup_path = applied["library"]["backup"]["path"]
    read = service.read(asset, "Readme", args["library"])
    fresh = parent.createNode(args["asset_type"], args["asset_name"] + "_fresh")
    fresh_contents = fresh.type().definition().sections()["Readme"].contents()
    fresh_path = fresh.path()
    fresh.destroy()
    out.update({
        "plan": plan, "applied": applied, "read": read,
        "fresh_contents": fresh_contents, "fresh_removed": hou.node(fresh_path) is None,
        "library_exists": os.path.isfile(args["library"]),
        "backup_exists": os.path.isfile(backup_path),
        "dirty_during": hou.hipFile.hasUnsavedChanges(),
    })
finally:
    if asset is not None:
        try:
            asset.destroy()
        except Exception:
            pass
    try:
        hou.hda.uninstallFile(args["library"])
    except Exception:
        pass
    for candidate in glob.glob(args["library"] + "*"):
        if os.path.isfile(candidate):
            try:
                os.remove(candidate)
            except OSError:
                pass
    if backup_path and os.path.isfile(backup_path):
        try:
            os.remove(backup_path)
        except OSError:
            pass
    out["instance_removed"] = hou.node(args["instance_path"]) is None
    out["library_removed"] = not os.path.exists(args["library"])
    out["backup_removed"] = not backup_path or not os.path.exists(backup_path)
    out["dirty_after_cleanup"] = hou.hipFile.hasUnsavedChanges()
result.emit(out)
'''
    response = controller.run(
        source,
        args={"asset_name": asset_name, "asset_type": asset_type, "library": str(library), "instance_path": instance_path},
        policy={"label": "Houdini Code Mode owned HDA plain section proof"},
    )
    assert response["ok"] is True, response.get("error")
    value = response["data"]["value"]
    assert value["plan"]["ok"] is True
    assert value["read"]["section"]["contents"] == "plain text"
    assert value["fresh_contents"] == "plain text"
    assert value["fresh_removed"] is True
    assert value["applied"]["library"]["before"]["sha256"] != value["applied"]["library"]["after"]["sha256"]
    assert [event["kind"] for event in value["applied"]["events"]] == ["hda.sections.preflight", "hda.sections.backup", "hda.definition.addSection"]
    assert value["library_exists"] is True and value["backup_exists"] is True
    assert value["instance_removed"] is True and value["library_removed"] is True and value["backup_removed"] is True
    assert value["dirty_before"] is True and value["dirty_during"] is True and value["dirty_after_cleanup"] is True
    assert not library.exists()
