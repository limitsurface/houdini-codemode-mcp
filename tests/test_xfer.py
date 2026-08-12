from __future__ import annotations

import json
from pathlib import Path
import socket
from typing import Any
import uuid

import pytest

from houdini_codemode.controller import Controller
from houdini_codemode.xfer import NodeTransferError, transfer_node


def _ok(value: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "data": {"value": value}, "meta": {}}


class FakeController:
    calls: list[dict[str, Any]] = []
    import_fails = False
    cleanup_fails = False

    def run(self, source, args=None, instance=None, policy=None):
        call = {"source": source, "args": args, "instance": instance, "policy": policy}
        self.calls.append(call)
        if "artifacts.root" in source:
            return _ok({"path": "C:/tmp/hcm", "max_bytes": 64 * 1024 * 1024})
        if "export_node" in source:
            return _ok(
                {
                    "artifact": {
                        "id": args["artifact_name"] + ".hcm-node.json",
                        "path": "C:/tmp/hcm/" + args["artifact_name"] + ".hcm-node.json",
                        "bytes": 512,
                        "sha256": "a" * 64,
                        "schema": "houdini-codemode.node-artifact",
                        "schema_version": 1,
                    },
                    "source": {"node_path": args["node_path"]},
                    "capture": {"children": args["children"]},
                    "summary": {"direct_nodes": 2},
                }
            )
        if "import_node" in source:
            if self.import_fails:
                return {"ok": False, "error": {"message": "destination unavailable"}}
            return _ok(
                {
                    "path": "/obj/restored",
                    "type": "geo",
                    "verified": True,
                    "destination_summary": {"direct_nodes": 2},
                    "error_count": 0,
                    "warning_count": 0,
                }
            )
        if "artifacts.remove" in source:
            if self.cleanup_fails and instance["port"] == 18811:
                return {"ok": False, "error": {"message": "source cleanup unavailable"}}
            return _ok({"removed": instance["port"] == 18811})
        raise AssertionError("unexpected source")


def _factory() -> FakeController:
    return FakeController()


def _endpoints() -> dict[str, dict[str, object]]:
    return {
        "source": {"host": "localhost", "port": 18811},
        "destination": {"host": "127.0.0.1", "port": 18814},
    }


def test_transfer_uses_explicit_distinct_loopback_endpoints_and_cleans_both_views() -> None:
    FakeController.calls = []
    FakeController.import_fails = False
    FakeController.cleanup_fails = False
    endpoints = _endpoints()

    result = transfer_node(
        "/obj/source",
        "/obj",
        source=endpoints["source"],
        destination=endpoints["destination"],
        name="restored",
        controller_factory=_factory,
    )

    assert result["destination"]["path"] == "/obj/restored"
    assert result["destination"]["verified"] is True
    assert result["artifact"]["bytes"] == 512
    assert [call["instance"]["port"] for call in FakeController.calls] == [18811, 18814, 18811, 18814, 18811, 18814]
    _source_root, _destination_root, export_call, import_call, source_cleanup, destination_cleanup = FakeController.calls
    assert export_call["args"]["artifact_name"].startswith("hcm-xfer-")
    assert import_call["args"]["artifact_reference"] == source_cleanup["args"]["artifact_reference"]
    assert source_cleanup["args"] == destination_cleanup["args"]
    assert all(call["policy"]["undo_group"] is True for call in FakeController.calls)
    assert result["cleanup"][0]["result"] == {"removed": True}
    assert result["cleanup"][1]["result"] == {"removed": False}
    assert result["cleanup_complete"] is True
    assert result["cleanup_errors"] == []
    assert result["effects"] == {
        "source_hip_saved": False,
        "destination_hip_saved": False,
    }


def test_transfer_cleans_source_artifact_after_import_failure() -> None:
    FakeController.calls = []
    FakeController.import_fails = True
    FakeController.cleanup_fails = False
    endpoints = _endpoints()

    with pytest.raises(NodeTransferError, match="destination unavailable"):
        transfer_node(
            "/obj/source",
            "/obj",
            source=endpoints["source"],
            destination=endpoints["destination"],
            controller_factory=_factory,
        )

    assert [call["instance"]["port"] for call in FakeController.calls] == [18811, 18814, 18811, 18814, 18811, 18814]


def test_completed_import_is_reported_when_artifact_cleanup_fails() -> None:
    FakeController.calls = []
    FakeController.import_fails = False
    FakeController.cleanup_fails = True
    endpoints = _endpoints()

    result = transfer_node(
        "/obj/source",
        "/obj",
        source=endpoints["source"],
        destination=endpoints["destination"],
        name="restored",
        controller_factory=_factory,
    )

    assert result["destination"]["path"] == "/obj/restored"
    assert result["destination"]["verified"] is True
    assert result["cleanup_complete"] is False
    assert result["cleanup_errors"] == [
        "localhost:18811: Houdini Code Mode transfer artifact cleanup failed: source cleanup unavailable"
    ]
    assert result["cleanup"][0] == {"host": "localhost", "port": 18811}
    assert result["cleanup"][1]["result"] == {"removed": False}
    FakeController.cleanup_fails = False


@pytest.mark.parametrize(
    ("source", "destination", "message"),
    [
        ({"host": "localhost"}, {"host": "localhost", "port": 18814}, "source.port"),
        ({"host": "localhost", "port": 18811}, {"host": "localhost", "port": 18811}, "distinct"),
        ({"host": "example.test", "port": 18811}, {"host": "localhost", "port": 18814}, "loopback"),
    ],
)
def test_transfer_rejects_unsafe_or_ambiguous_endpoints(source, destination, message) -> None:
    with pytest.raises(NodeTransferError, match=message):
        transfer_node("/obj/source", "/obj", source=source, destination=destination)


def _live_endpoint_available(port: int) -> bool:
    try:
        with socket.create_connection(("localhost", port), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.mark.live
@pytest.mark.skipif(
    not (_live_endpoint_available(18811) and _live_endpoint_available(18814)),
    reason="Live Houdini hrpyc endpoints 18811 and 18814 are required",
)
def test_live_transfer_between_18811_and_18814_cleans_artifact_and_nodes() -> None:
    controller = Controller()
    token = uuid.uuid4().hex[:10]
    source_name = f"codemode_xfer_source_{token}"
    destination_name = f"codemode_xfer_destination_{token}"
    source_path = f"/obj/{source_name}"
    destination_path = f"/obj/{destination_name}"

    def run(port: int, source: str, args: dict[str, Any]) -> dict[str, Any]:
        response = controller.run(
            source,
            args=args,
            instance={"host": "localhost", "port": port},
            policy={"label": "Houdini Code Mode cross-session transfer proof"},
        )
        assert response["ok"] is True, json.dumps(response, sort_keys=True)
        return response["data"]["value"]

    def remove(port: int, path: str) -> bool:
        return run(
            port,
            "node = hou.node(args['path'])\n"
            "if node is not None:\n"
            "    node.destroy()\n"
            "result.emit(hou.node(args['path']) is None)",
            {"path": path},
        )

    hips = {
        port: run(port, "result.emit(hou.hipFile.path())", {}) for port in (18811, 18814)
    }
    mtimes_before = {
        port: Path(path).stat().st_mtime_ns if Path(path).is_file() else None
        for port, path in hips.items()
    }
    transfer: dict[str, Any] | None = None
    try:
        run(
            18811,
            """root = hou.node('/obj').createNode('geo', args['name'])
box = root.createNode('box', 'box1')
box.parmTuple('size').set((1.25, 2.5, 3.75))
output = root.createNode('null', 'OUT')
output.setInput(0, box)
output.setDisplayFlag(True)
output.setRenderFlag(True)
root.layoutChildren()
result.emit(root.path())""",
            {"name": source_name},
        )
        transfer = transfer_node(
            source_path,
            "/obj",
            source={"host": "localhost", "port": 18811},
            destination={"host": "localhost", "port": 18814},
            name=destination_name,
            children=True,
        )
        destination = run(
            18814,
            """root = hou.node(args['path'])
output = root.node('OUT')
box = root.node('box1')
result.emit({
    'children': sorted(node.name() for node in root.children()),
    'wiring': output.input(0).path(),
    'size': list(box.parmTuple('size').eval()),
    'display': output.isDisplayFlagSet(),
    'render': output.isRenderFlagSet(),
})""",
            {"path": destination_path},
        )
        assert transfer["destination"]["verified"] is True
        assert destination == {
            "children": ["OUT", "box1"],
            "wiring": f"{destination_path}/box1",
            "size": [1.25, 2.5, 3.75],
            "display": True,
            "render": True,
        }
        assert transfer["cleanup"][0]["result"]["removed"] is True
        assert transfer["cleanup"][1]["result"]["already_absent"] is True
        assert transfer["cleanup_complete"] is True
        assert transfer["cleanup_errors"] == []
        assert transfer["effects"] == {
            "source_hip_saved": False,
            "destination_hip_saved": False,
        }
    finally:
        # ``transfer_node`` intentionally leaves a successful destination node;
        # this live proof owns and removes only its throwaway test nodes.
        assert remove(18811, source_path) is True
        assert remove(18814, destination_path) is True

    assert transfer is not None
    artifact_id = transfer["artifact"]["id"]
    for port in (18811, 18814):
        artifacts = run(port, "result.emit(ctx.artifacts.list(max_items=1000))", {})
        assert artifact_id not in {row[0] for row in artifacts["rows"]}
    mtimes_after = {
        port: Path(path).stat().st_mtime_ns if Path(path).is_file() else None
        for port, path in hips.items()
    }
    assert mtimes_after == mtimes_before
