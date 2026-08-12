from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid

from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
import pytest

from houdini_codemode.controller import Controller
from houdini_codemode.mcp_server import mcp


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


def test_live_read_limits_errors_and_isolated_mutation_cleanup() -> None:
    controller = Controller()
    doctor = controller.doctor()
    assert doctor["ok"] is True
    assert doctor["data"]["value"]["thread"] == "MainThread"
    assert doctor["meta"]["execution_model"] == "trusted-local-main-thread"

    hip_path = Path(doctor["data"]["value"]["hip_file"])
    mtime_before = hip_path.stat().st_mtime_ns if hip_path.is_file() else None

    read = controller.run(
        "node = hou.node(args['path'])\n"
        "result.emit({'label': args['label'], 'node': node})",
        args={"path": "/obj", "label": "live-read"},
    )
    assert read["ok"] is True
    assert read["data"]["value"]["label"] == "live-read"
    assert read["data"]["value"]["node"]["path"] == "/obj"
    assert read["data"]["value"]["node"]["kind"] == "hou.Node"

    bounded = controller.run(
        "print('é' * 100, end='')\nresult.emit(list(range(20)))",
        policy={"max_log_bytes": 9, "max_container_items": 3},
    )
    assert bounded["ok"] is True
    assert len(bounded["data"]["logs"]["stdout"].encode("utf-8")) <= 9
    assert bounded["data"]["logs"]["stdout_truncated"] is True
    assert bounded["data"]["value"] == [0, 1, 2]
    assert {item["reason"] for item in bounded["meta"]["truncations"]} == {
        "max_container_items",
        "max_log_bytes",
    }

    failure = controller.run("raise ValueError('live structured failure')")
    assert failure["ok"] is False
    assert failure["error"]["category"] == "execution"
    assert failure["error"]["type"] == "ValueError"
    assert failure["meta"]["completion"] == "complete"

    token = uuid.uuid4().hex[:10]
    name = f"codemode_live_{token}"
    path = f"/obj/{name}"
    cleanup_source = (
        "node = hou.node(args['path'])\n"
        "if node is not None:\n"
        "    node.destroy()\n"
        "result.emit(hou.node(args['path']) is None)"
    )
    mutation_source = """
parent = hou.node('/obj')
existing = parent.node(args['name'])
if existing is not None:
    existing.destroy()
root = parent.createNode('geo', args['name'])
try:
    box = root.createNode('box', 'box1')
    out = root.createNode('null', 'OUT')
    out.setInput(0, box)
    out.setDisplayFlag(True)
    out.setRenderFlag(True)
    root.layoutChildren()
    result.emit({
        'root': ctx.nodes.summary(root),
        'output': ctx.nodes.summary(out),
        'display': out.isDisplayFlagSet(),
        'render': out.isRenderFlagSet(),
        'input_path': out.input(0).path(),
        'exists_during_run': hou.node(args['path']) is not None,
    })
finally:
    current = hou.node(args['path'])
    if current is not None:
        current.destroy()
"""
    try:
        mutation = controller.run(
            mutation_source,
            args={"name": name, "path": path},
            policy={"label": "Houdini Code Mode live viability"},
        )
        assert mutation["ok"] is True
        value = mutation["data"]["value"]
        assert value["root"]["path"] == path
        assert value["output"]["path"] == f"{path}/OUT"
        assert value["display"] is True
        assert value["render"] is True
        assert value["input_path"] == f"{path}/box1"
        assert value["exists_during_run"] is True
    finally:
        cleanup = controller.run(cleanup_source, args={"path": path})
        assert cleanup["ok"] is True
        assert cleanup["data"]["value"] is True

    verify = controller.run(
        "result.emit(hou.node(args['path']) is None)",
        args={"path": path},
    )
    assert verify["ok"] is True
    assert verify["data"]["value"] is True
    if mtime_before is not None:
        assert hip_path.stat().st_mtime_ns == mtime_before


def test_live_bounded_inspection_parity_and_data_method_costs() -> None:
    token = uuid.uuid4().hex[:10]
    name = f"codemode_inspect_{token}"
    path = f"/obj/{name}"
    source = """
import time

parent = hou.node('/obj')
existing = parent.node(args['name'])
if existing is not None:
    existing.destroy()
root = parent.createNode('geo', args['name'])
try:
    box = root.createNode('box', 'box1')
    transform = root.createNode('xform', 'transform1')
    output = root.createNode('null', 'OUT')
    transform.setInput(0, box)
    output.setInput(0, transform)
    output.setDisplayFlag(True)
    output.setRenderFlag(True)
    transform.parmTuple('t').set((1.0, 2.0, 3.0))

    start = time.perf_counter()
    direct_value = transform.parmTuple('t')[0].valueAsData()
    direct_ms = (time.perf_counter() - start) * 1000.0

    start = time.perf_counter()
    projection = ctx.parms.project(transform, ['t', 'missing'], value_mode='summary')
    projection_ms = (time.perf_counter() - start) * 1000.0

    start = time.perf_counter()
    broad = transform.parmsAsData(brief=False)
    broad_ms = (time.perf_counter() - start) * 1000.0

    result.emit({
        'find': ctx.nodes.find(root, type_name='null'),
        'neighbors': ctx.nodes.neighbors(output, direction='upstream', depth=2),
        'summary': ctx.nodes.network_summary(root, include_boundaries=True),
        'parms': ctx.parms.list(transform, name='t', max_parms=5),
        'projection': projection,
        'data_methods': {
            'direct_type': type(direct_value).__name__,
            'direct_ms': direct_ms,
            'projection_ms': projection_ms,
            'parms_as_data_ms': broad_ms,
            'parms_as_data_is_none': broad is None,
        },
    })
finally:
    current = hou.node(args['path'])
    if current is not None:
        current.destroy()
"""

    response = Controller().run(source, args={"name": name, "path": path})

    assert response["ok"] is True
    value = response["data"]["value"]
    assert value["find"]["nodes"]["rows"][0][0] == "OUT"
    assert [row[1] for row in value["neighbors"]["nodes"]["rows"]] == [
        "OUT",
        "transform1",
        "box1",
    ]
    assert value["neighbors"]["edges"]["rows"] == [[1, 0, 0, 0], [2, 0, 1, 0]]
    assert value["summary"]["counts"]["nodes"] == 3
    assert value["summary"]["boundaries"]["entry_nodes"]["rows"] == [["box1", "box"]]
    assert value["summary"]["boundaries"]["terminal_nodes"]["rows"] == [["OUT", "null"]]
    assert value["projection"]["items"][0]["status"] == "ok"
    assert value["projection"]["items"][0]["v"]["kind"] == "sequence"
    assert value["projection"]["items"][1] == {"p": "missing", "status": "missing"}
    assert value["parms"]["rows"][0][0] == "t"
    assert all(timing >= 0 for key, timing in value["data_methods"].items() if key.endswith("_ms"))

    verify = Controller().run(
        "result.emit(hou.node(args['path']) is None)",
        args={"path": path},
    )
    assert verify["ok"] is True
    assert verify["data"]["value"] is True


def test_live_undo_group_is_labeled_but_not_rollback_on_error() -> None:
    token = uuid.uuid4().hex[:10]
    name = f"codemode_undo_{token}"
    path = f"/obj/{name}"
    label = f"Houdini Code Mode undo proof {token}"

    response = Controller().run(
        "hou.node('/obj').createNode('null', args['name'])\n"
        "raise RuntimeError('prove undo grouping is not rollback')",
        args={"name": name},
        policy={"label": label, "undo_group": True},
    )

    assert response["ok"] is False
    assert response["error"]["type"] == "RuntimeError"
    inspect = Controller().run(
        "result.emit({'exists': hou.node(args['path']) is not None, "
        "'undo_labels': list(hou.undos.undoLabels())[:100]})",
        args={"path": path},
    )
    assert inspect["ok"] is True
    assert inspect["data"]["value"]["exists"] is True
    assert label in inspect["data"]["value"]["undo_labels"]

    cleanup = Controller().run(
        "node = hou.node(args['path'])\n"
        "if node is not None:\n"
        "    node.destroy()\n"
        "result.emit(hou.node(args['path']) is None)",
        args={"path": path},
        policy={"label": "Houdini Code Mode undo proof cleanup"},
    )
    assert cleanup["ok"] is True
    assert cleanup["data"]["value"] is True


def test_live_artifact_round_trip_is_bounded_and_cleans_up() -> None:
    token = uuid.uuid4().hex[:10]
    source_name = f"codemode_artifact_source_{token}"
    restored_name = f"codemode_artifact_restored_{token}"
    artifact_name = f"codemode-artifact-{token}"
    source_path = f"/obj/{source_name}"
    restored_path = f"/obj/{restored_name}"
    source = """
parent = hou.node('/obj')
artifact = None
for path in (args['source_path'], args['restored_path']):
    existing = hou.node(path)
    if existing is not None:
        existing.destroy()
try:
    root = parent.createNode('geo', args['source_name'])
    box = root.createNode('box', 'box1')
    output = root.createNode('null', 'OUT')
    output.setInput(0, box)
    box.parmTuple('size').set((1.25, 2.5, 3.75))
    output.setDisplayFlag(True)
    output.setRenderFlag(True)
    root.layoutChildren()

    artifact = ctx.artifacts.export_node(
        root,
        name=args['artifact_name'],
        children=True,
    )
    restored = ctx.artifacts.import_node(
        artifact,
        parent,
        name=args['restored_name'],
    )
    restored_root = hou.node(restored['path'])
    restored_output = restored_root.node('OUT')
    result.emit({
        'artifact': artifact['artifact'],
        'capture': artifact['capture'],
        'source_summary': artifact['summary'],
        'restored': restored,
        'size': ctx.parms.project(restored_root.node('box1'), ['size']),
        'wiring': restored_output.input(0).path(),
        'display': restored_output.isDisplayFlagSet(),
        'render': restored_output.isRenderFlagSet(),
    })
finally:
    for path in (args['source_path'], args['restored_path']):
        current = hou.node(path)
        if current is not None:
            current.destroy()
    if artifact is not None:
        try:
            ctx.artifacts.remove(artifact)
        except Exception:
            pass
"""

    response = Controller().run(
        source,
        args={
            "source_name": source_name,
            "restored_name": restored_name,
            "artifact_name": artifact_name,
            "source_path": source_path,
            "restored_path": restored_path,
        },
        policy={"label": "Houdini Code Mode artifact round trip"},
    )

    assert response["ok"] is True
    value = response["data"]["value"]
    assert value["artifact"]["bytes"] > 0
    assert len(value["artifact"]["sha256"]) == 64
    assert value["capture"]["children"] is True
    assert value["restored"]["verified"] is True
    assert value["size"]["items"][0]["status"] == "ok"
    assert value["wiring"] == f"{restored_path}/box1"
    assert value["display"] is True
    assert value["render"] is True
    kinds = [event["kind"] for event in response["meta"]["mutation"]["events"]]
    assert kinds == [
        "artifact.write",
        "artifact.read",
        "node.create_from_artifact",
        "artifact.remove",
    ]

    verify = Controller().run(
        "result.emit({path: hou.node(path) is None for path in args['paths']})",
        args={"paths": [source_path, restored_path]},
    )
    assert verify["ok"] is True
    assert all(verify["data"]["value"].values())


def test_live_scalar_value_inverse_payload_and_broad_artifact_fallback() -> None:
    token = uuid.uuid4().hex[:10]
    source_name = f"codemode_artifact_scalar_source_{token}"
    restored_name = f"codemode_artifact_scalar_restored_{token}"
    artifact_name = f"codemode-artifact-scalar-{token}"
    source = r'''
parent = hou.node('/obj')
artifact = None
created = []
try:
    root = parent.createNode('geo', args['source_name'])
    created.append(root)
    source_parm = root.parm('shop_materialpath')
    source_parm.set('/mat/codemode_probe')
    value_data = source_parm.asData()
    source_parm.set('')
    source_parm.setValueFromData(value_data)
    artifact = ctx.artifacts.export_node(
        root,
        name=args['artifact_name'],
        children=False,
    )
    restored = ctx.artifacts.import_node(
        artifact,
        parent,
        name=args['restored_name'],
    )
    restored_node = hou.node(restored['path'])
    created.append(restored_node)
    result.emit({
        'inverse_methods': restored['inverse_methods'],
        'payload_type': type(value_data).__name__,
        'source_value': source_parm.eval(),
        'value': restored_node.parm('shop_materialpath').eval(),
    })
finally:
    for node in reversed(created):
        if node is not None:
            try:
                node.destroy()
            except Exception:
                pass
    if artifact is not None:
        try:
            ctx.artifacts.remove(artifact)
        except Exception:
            pass
'''

    response = Controller().run(
        source,
        args={
            "source_name": source_name,
            "restored_name": restored_name,
            "artifact_name": artifact_name,
        },
        policy={"label": "Houdini Code Mode scalar asData inverse proof"},
    )

    assert response["ok"] is True
    assert response["data"]["value"] == {
        "inverse_methods": ["setFromData"],
        "payload_type": "str",
        "source_value": "/mat/codemode_probe",
        "value": "/mat/codemode_probe",
    }


def test_live_python_sop_binding_sync_and_cleanup() -> None:
    token = uuid.uuid4().hex[:10]
    name = f"codemode_python_{token}"
    path = f"/obj/{name}"
    source = """
parent = hou.node('/obj')
existing = parent.node(args['name'])
if existing is not None:
    existing.destroy()
root = parent.createNode('geo', args['name'])
try:
    node = root.createNode('pythonsnippet', 'python1')
    node.parm('pythoncode').set('''#bind parm amplitude float val=0.25
return hou.Geometry()
''')
    before = ctx.python.validate(node, details=True)
    synced = ctx.python.sync(node, details=True)
    after = ctx.python.validate(node, details=True)
    result.emit({
        'before': before,
        'sync': synced,
        'after': after,
        'amplitude': node.parm('amplitude').eval(),
    })
finally:
    current = hou.node(args['path'])
    if current is not None:
        current.destroy()
"""

    response = Controller().run(
        source,
        args={"name": name, "path": path},
        policy={"label": "Houdini Code Mode Python binding sync"},
    )

    assert response["ok"] is True
    value = response["data"]["value"]
    assert value["before"]["ok"] is False
    assert value["before"]["missing_controls"] == ["amplitude"]
    assert value["sync"]["clean"] is True
    assert value["after"]["ok"] is True
    assert value["after"]["controls"][0]["linked"] is True
    assert value["amplitude"] == 0.25
    assert response["meta"]["mutation"]["events"][0]["kind"] == "python.interface_sync"

    verify = Controller().run(
        "result.emit(hou.node(args['path']) is None)", args={"path": path}
    )
    assert verify["ok"] is True
    assert verify["data"]["value"] is True


def test_live_wrangle_spare_sync_and_cleanup() -> None:
    token = uuid.uuid4().hex[:10]
    name = f"codemode_wrangle_{token}"
    path = f"/obj/{name}"
    source = """
parent = hou.node('/obj')
existing = parent.node(args['name'])
if existing is not None:
    existing.destroy()
root = parent.createNode('geo', args['name'])
try:
    wrangle = root.createNode('attribwrangle', 'wrangle1')
    wrangle.parm('snippet').set('@P *= chf("amplitude");')
    synced = ctx.wrangle.sync(wrangle)
    wrangle.setDisplayFlag(True)
    wrangle.setRenderFlag(True)
    result.emit({
        'sync': synced,
        'amplitude_exists': wrangle.parm('amplitude') is not None,
        'display': wrangle.isDisplayFlagSet(),
        'render': wrangle.isRenderFlagSet(),
    })
finally:
    current = hou.node(args['path'])
    if current is not None:
        current.destroy()
"""

    response = Controller().run(
        source,
        args={"name": name, "path": path},
        policy={"label": "Houdini Code Mode wrangle spare sync"},
    )

    assert response["ok"] is True
    value = response["data"]["value"]
    assert value["sync"]["created"] == ["amplitude"]
    assert value["amplitude_exists"] is True
    assert value["display"] is True
    assert value["render"] is True
    assert response["meta"]["mutation"]["events"][0]["kind"] == "wrangle.spare_parms_sync"

    verify = Controller().run(
        "result.emit(hou.node(args['path']) is None)", args={"path": path}
    )
    assert verify["ok"] is True
    assert verify["data"]["value"] is True


def test_live_opencl_sync_across_sop_cop_and_dop_cleanup() -> None:
    token = uuid.uuid4().hex[:10]
    paths = {
        "sop": f"/obj/codemode_opencl_sop_{token}",
        "cop": f"/img/codemode_opencl_cop_{token}",
        "dop": f"/obj/codemode_opencl_dop_{token}",
    }
    source = r'''
sop_root = hou.node('/obj').createNode('geo', args['sop_name'])
cop_root = hou.node('/img').createNode('copnet', args['cop_name'])
dop_root = hou.node('/obj').createNode('dopnet', args['dop_name'])
try:
    sop = sop_root.createNode('opencl', 'opencl1')
    sop.parm('kernelcode').set(
        '#bind point &P float3\n'
        '#bind parm amplitude float val=0.25\n'
        '@KERNEL { @P *= @amplitude; }'
    )
    cop = cop_root.createNode('opencl', 'opencl1')
    cop.parm('kernelcode').set(
        '#bind layer src?\n'
        '#bind layer !&dst\n'
        '#bind parm gain float val=2\n'
        '@KERNEL { }'
    )
    dop = dop_root.createNode('gasopencl', 'gasopencl1')
    dop.parm('kernelcode').set(
        '#bind parm gain float val=0.5\n'
        '@KERNEL { }'
    )
    result.emit({
        'sop': ctx.opencl.sync(sop, clear=True, details=True),
        'sop_value': sop.parm('amplitude').eval(),
        'cop': ctx.opencl.sync(cop, clear=True, details=True),
        'cop_value': cop.parm('gain').eval(),
        'dop': ctx.opencl.sync(dop, clear=True, details=True),
        'dop_value': dop.parm('gain').eval(),
    })
finally:
    dop_root.destroy()
    cop_root.destroy()
    sop_root.destroy()
'''
    response = Controller().run(
        source,
        args={key + "_name": path.rsplit("/", 1)[-1] for key, path in paths.items()},
        policy={"label": "Houdini Code Mode OpenCL interface sync parity"},
    )

    assert response["ok"] is True
    value = response["data"]["value"]
    assert value["sop"]["context"] == "sop"
    assert value["sop"]["sync_required"] is False
    assert value["sop_value"] == pytest.approx(0.25)
    assert value["cop"]["context"] == "cop"
    assert value["cop"]["clean"] is True
    assert value["cop"]["inputs"] == [
        {"name": "src", "type": "floatn", "optional": True}
    ]
    assert value["cop"]["outputs"] == [{"name": "dst", "type": "floatn"}]
    assert value["cop_value"] == pytest.approx(2.0)
    assert value["dop"]["context"] == "dop"
    assert value["dop"]["clean"] is True
    assert value["dop_value"] == pytest.approx(0.5)
    events = response["meta"]["mutation"]["events"]
    assert [event["context"] for event in events] == ["sop", "cop", "dop"]
    assert all(event["status"] == "complete" for event in events)

    verify = Controller().run(
        "result.emit({path: hou.node(path) is None for path in args['paths']})",
        args={"paths": list(paths.values())},
    )
    assert verify["ok"] is True
    assert all(verify["data"]["value"].values())


def test_live_geometry_cop_and_lop_bounded_summaries_cleanup() -> None:
    token = uuid.uuid4().hex[:10]
    geo_path = f"/obj/codemode_domains_{token}"
    cop_path = f"/img/codemode_domains_{token}"
    lop_path = f"/stage/codemode_domains_{token}"
    source = r'''
geo_root = hou.node('/obj').createNode('geo', args['geo_name'])
cop_root = hou.node('/img').createNode('copnet', args['cop_name'])
lop_node = hou.node('/stage').createNode('null', args['lop_name'])
try:
    box = geo_root.createNode('box', 'box1')
    constant = cop_root.createNode('constant', 'constant1')
    geometry = {
        'summary': ctx.geometry.summary(box, topology=True),
        'attributes': ctx.geometry.attributes(box, max_attribs=5),
        'positions': ctx.geometry.get(box, 'P', limit=2),
    }
    cop = {
        'info': ctx.cop.info(constant),
        'sample': ctx.cop.sample(constant, [{'x': 0, 'y': 0}], max_points=1),
    }
    lop = ctx.lop.summary(lop_node, include_paths=True, path_limit=2)
    result.emit({'geometry': geometry, 'cop': cop, 'lop': lop})
finally:
    if lop_node is not None:
        lop_node.destroy()
    if cop_root is not None:
        cop_root.destroy()
    if geo_root is not None:
        geo_root.destroy()
'''
    response = Controller().run(
        source,
        args={
            "geo_name": geo_path.rsplit("/", 1)[-1],
            "cop_name": cop_path.rsplit("/", 1)[-1],
            "lop_name": lop_path.rsplit("/", 1)[-1],
        },
        policy={"label": "Houdini Code Mode bounded domain summary proof"},
    )

    assert response["ok"] is True
    value = response["data"]["value"]
    assert value["geometry"]["summary"]["counts"] == {
        "point": 8,
        "prim": 6,
        "vertex": 24,
    }
    assert value["geometry"]["positions"]["meta"]["truncated"] is True
    assert value["cop"]["info"]["resolution"]["buffer"] == [1024, 1024]
    assert value["cop"]["sample"]["meta"]["returned"] == 1
    assert value["lop"]["counts"]["prims"] >= 1
    assert value["lop"]["meta"]["included_paths"] is True
    assert any(
        event["kind"] == "houdini.cook"
        and event["helper"] == "ctx.lop.summary"
        for event in response["meta"]["mutation"]["events"]
    )

    verify = Controller().run(
        "result.emit({path: hou.node(path) is None for path in args['paths']})",
        args={"paths": [geo_path, cop_path, lop_path]},
    )
    assert verify["ok"] is True
    assert all(verify["data"]["value"].values())


def test_live_cop_image_export_import_effects_and_cleanup() -> None:
    token = uuid.uuid4().hex[:10]
    name = f"codemode_cop_file_{token}"
    path = f"/img/{name}"
    output_path = str(Path(os.environ["TEMP"]) / f"houdini-codemode-{token}.exr")
    source = r'''
import os
parent = hou.node('/img').createNode('copnet', args['name'])
try:
    source_node = parent.createNode('constant', 'constant1')
    exported = ctx.cop_files.export_image(
        source_node,
        args['output_path'],
        overwrite=False,
        max_bytes=1024 * 1024,
    )
    imported = ctx.cop_files.import_image(
        args['output_path'],
        parent,
        name='imported',
        colorspace='raw',
    )
    result.emit({
        'exported': exported,
        'imported': imported,
        'file_exists': os.path.isfile(args['output_path']),
        'helper_removed': parent.node('_hcm_export_image') is None,
    })
finally:
    parent.destroy()
    if os.path.isfile(args['output_path']):
        os.remove(args['output_path'])
'''

    response = Controller().run(
        source,
        args={"name": name, "output_path": output_path},
        policy={"label": "Houdini Code Mode COP image file proof"},
    )

    assert response["ok"] is True
    value = response["data"]["value"]
    assert value["file_exists"] is True
    assert value["helper_removed"] is True
    assert value["exported"]["file"]["bytes"] > 0
    assert value["exported"]["mode"] == "raw"
    assert value["imported"]["colorspace"] == "raw"
    assert [
        event["kind"] for event in response["meta"]["mutation"]["events"]
    ] == ["cop.image_export", "cop.image_import"]
    assert not Path(output_path).exists()

    verify = Controller().run(
        "result.emit(hou.node(args['path']) is None)", args={"path": path}
    )
    assert verify["ok"] is True
    assert verify["data"]["value"] is True


def test_live_cop_export_limit_preserves_existing_file_and_cleans_temp() -> None:
    token = uuid.uuid4().hex[:10]
    name = f"codemode_cop_file_failure_{token}"
    path = f"/img/{name}"
    output_path = str(Path(os.environ["TEMP"]) / f"houdini-codemode-{token}.exr")
    source = r'''
import glob
import os
parent = hou.node('/img').createNode('copnet', args['name'])
sentinel = b'preserve-existing-target'
with open(args['output_path'], 'wb') as stream:
    stream.write(sentinel)
try:
    source_node = parent.createNode('constant', 'constant1')
    error_type = None
    error_message = None
    try:
        ctx.cop_files.export_image(
            source_node,
            args['output_path'],
            overwrite=True,
            max_bytes=1,
        )
    except Exception as exc:
        error_type = exc.__class__.__name__
        error_message = str(exc)
    with open(args['output_path'], 'rb') as stream:
        preserved = stream.read() == sentinel
    temp_pattern = os.path.join(
        os.path.dirname(args['output_path']),
        '.hcm-cop-*' + os.path.splitext(args['output_path'])[1],
    )
    result.emit({
        'error_type': error_type,
        'error_message': error_message,
        'preserved': preserved,
        'temp_files': glob.glob(temp_pattern),
        'helper_removed': parent.node('_hcm_export_image') is None,
    })
finally:
    parent.destroy()
    if os.path.isfile(args['output_path']):
        os.remove(args['output_path'])
'''

    response = Controller().run(
        source,
        args={"name": name, "output_path": output_path},
        policy={"label": "Houdini Code Mode COP failed export preservation proof"},
    )

    assert response["ok"] is True
    value = response["data"]["value"]
    assert value["error_type"] == "ValueError"
    assert "1-byte limit" in value["error_message"]
    assert value["preserved"] is True
    assert value["temp_files"] == []
    assert value["helper_removed"] is True
    assert response["meta"]["mutation"]["events"] == []
    assert not Path(output_path).exists()

    verify = Controller().run(
        "result.emit(hou.node(args['path']) is None)", args={"path": path}
    )
    assert verify["ok"] is True
    assert verify["data"]["value"] is True


def test_live_hda_discovery_and_instance_inspection_cleanup() -> None:
    token = uuid.uuid4().hex[:10]
    name = f"codemode_hda_{token}"
    path = f"/obj/{name}"
    controller_name = f"codemode_hda_controller_{token}"
    controller_path = f"/obj/{controller_name}"
    source = r'''
import os
node = hou.node('/obj').createNode('alembicarchive', args['name'])
controller = hou.node('/obj').createNode('null', args['controller_name'])
original_frame = hou.frame()
try:
    node.parm('tx').setExpression(
        'ch("{}/tx")'.format(args['controller_path'])
    )
    definition_path = node.type().definition().libraryFilePath()
    update_before = {
        'dirty': hou.hipFile.hasUnsavedChanges(),
        'mtime': os.path.getmtime(definition_path),
        'size': os.path.getsize(definition_path),
    }
    update_plan = ctx.hda.plan_update(
        node,
        contents=False,
        interface=True,
        reference_audit=True,
        max_items=100,
    )
    update_after = {
        'dirty': hou.hipFile.hasUnsavedChanges(),
        'mtime': os.path.getmtime(definition_path),
        'size': os.path.getsize(definition_path),
    }
    result.emit({
        'original_frame': original_frame,
        'instance': ctx.hda.inspect(
            node,
            parms=True,
            sections=True,
            tools=True,
            max_items=10,
        ),
        'definitions': ctx.hda.definitions(
            type_name='alembicarchive',
            max_items=3,
            max_scan=5000,
        ),
        'libraries': ctx.hda.libraries(
            definition='alembicarchive',
            max_items=3,
            max_types=10,
            max_scan=5000,
        ),
        'references': ctx.hda.references(
            node,
            descendants=True,
            max_results=10,
        ),
        'reference_validation': ctx.hda.validate(
            node,
            external_references=True,
            max_items=100,
        ),
        'update_plan': update_plan,
        'update_unchanged': update_before == update_after,
        'validation_plan': ctx.hda.validate(
            node,
            fresh=True,
            frames=[original_frame + 0.25],
            dry_run=True,
        ),
        'validation': ctx.hda.validate(
            node,
            fresh=True,
            frames=[original_frame + 0.25],
            max_items=100,
        ),
        'frame_restored': hou.frame() == original_frame,
    })
finally:
    node.destroy()
    controller.destroy()
'''
    response = Controller().run(
        source,
        args={
            "name": name,
            "controller_name": controller_name,
            "controller_path": controller_path,
        },
        policy={"label": "Houdini Code Mode bounded HDA inspection proof"},
    )

    assert response["ok"] is True
    value = response["data"]["value"]
    assert value["instance"]["definition"]["type_name"] == "alembicarchive"
    assert value["instance"]["definition"]["sections"]["count"] >= 1
    assert value["instance"]["parms"]["truncated"] is True
    assert value["definitions"]["count"] >= 1
    assert all(
        "alembicarchive" in item["type_name"]
        for item in value["definitions"]["definitions"]
    )
    assert value["libraries"]["count"] >= 1
    assert value["references"]["count"] == 1
    assert value["references"]["items"][0]["target_parm"] == (
        controller_path + "/tx"
    )
    assert value["references"]["errors"] == []
    assert value["reference_validation"]["ok"] is False
    assert value["reference_validation"]["external_references"]["count"] == 1
    assert value["update_plan"]["dry_run"] is True
    assert value["update_plan"]["expected_effects"]["current_call"] == {
        "installs_library": False,
        "mutates_definition": False,
        "mutates_instance": False,
        "saves_hip": False,
        "writes_library": False,
    }
    assert value["update_unchanged"] is True
    assert value["validation_plan"]["dry_run"] is True
    assert value["validation_plan"]["effects"]["library_writes"] is False
    assert value["validation"]["ok"] is True
    assert value["validation"]["frames"][0]["frame"] == pytest.approx(
        value["original_frame"] + 0.25
    )
    assert value["frame_restored"] is True
    events = response["meta"]["mutation"]["events"]
    assert [event["kind"] for event in events] == [
        "hda.validation",
        "hda.validation",
        "node.create_temporary",
        "node.destroy_temporary",
    ]
    assert events[1]["frame_restored"] is True

    verify = Controller().run(
        "result.emit({path: hou.node(path) is None for path in args['paths']})",
        args={"paths": [path, controller_path]},
    )
    assert verify["ok"] is True
    assert all(verify["data"]["value"].values())


def test_live_competing_local_processes_serialize_on_endpoint_gate() -> None:
    base = [sys.executable, "-m", "houdini_codemode.cli", "run", "--code"]
    first = subprocess.Popen(
        base
        + [
            "import time\n"
            "started = time.time()\n"
            "time.sleep(0.75)\n"
            "result.emit({'name': 'first', 'started': started, 'ended': time.time()})"
        ],
        cwd=Path.cwd(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    time.sleep(0.15)
    second_started = time.perf_counter()
    second = subprocess.Popen(
        base
        + [
            "import time\n"
            "result.emit({'name': 'second', 'started': time.time(), 'ended': time.time()})"
        ],
        cwd=Path.cwd(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    first_stdout, first_stderr = first.communicate(timeout=15)
    second_stdout, second_stderr = second.communicate(timeout=15)
    second_elapsed = time.perf_counter() - second_started

    assert first.returncode == 0, first_stderr
    assert second.returncode == 0, second_stderr
    first_response = json.loads(first_stdout)
    second_response = json.loads(second_stdout)
    assert first_response["ok"] is True
    assert second_response["ok"] is True
    first_value = first_response["data"]["value"]
    second_value = second_response["data"]["value"]
    assert first_value["name"] == "first"
    assert second_value["name"] == "second"
    assert second_value["started"] >= first_value["ended"]
    assert second_elapsed >= 0.5


def test_live_distinct_ports_can_execute_independently() -> None:
    raw_second_port = os.environ.get("HOUDINI_CODEMODE_SECOND_PORT")
    if not raw_second_port:
        pytest.skip("Set HOUDINI_CODEMODE_SECOND_PORT for a second live Houdini instance")
    second_port = int(raw_second_port)
    if not _server_available(port=second_port):
        pytest.skip(f"Second Houdini is not available on localhost:{second_port}")

    base = [sys.executable, "-m", "houdini_codemode.cli", "run", "--code"]
    source = (
        "import time\n"
        "started = time.time()\n"
        "time.sleep(0.75)\n"
        "result.emit({'started': started, 'ended': time.time(), "
        "'version': hou.applicationVersionString()})"
    )
    started = time.perf_counter()
    first = subprocess.Popen(
        base + [source, "--port", "18811"],
        cwd=Path.cwd(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    second = subprocess.Popen(
        base + [source, "--port", str(second_port)],
        cwd=Path.cwd(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    first_stdout, first_stderr = first.communicate(timeout=15)
    second_stdout, second_stderr = second.communicate(timeout=15)
    elapsed = time.perf_counter() - started

    assert first.returncode == 0, first_stderr
    assert second.returncode == 0, second_stderr
    assert json.loads(first_stdout)["ok"] is True
    assert json.loads(second_stdout)["ok"] is True
    assert elapsed < 1.4


def test_live_mcp_uses_the_same_executor() -> None:
    async def exercise():
        async with Client(mcp) as client:
            listed = await client.list_tools()
            assert [tool.name for tool in listed.tools] == ["houdini_code_run"]
            return await client.call_tool(
                "houdini_code_run",
                {
                    "source": (
                        "result.emit({'version': hou.applicationVersionString(), "
                        "'thread': ctx.session.info()['thread']})"
                    )
                },
            )

    response = asyncio.run(exercise())

    assert response.is_error is False
    assert response.structured_content["ok"] is True
    assert response.structured_content["data"]["value"]["thread"] == "MainThread"
    assert response.structured_content["data"]["value"]["version"]


def test_live_mcp_stdio_process() -> None:
    async def exercise():
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "houdini_codemode.mcp_server"],
            cwd=Path.cwd(),
        )
        async with Client(stdio_client(server)) as client:
            listed = await client.list_tools()
            result = await client.call_tool(
                "houdini_code_run",
                {
                    "source": (
                        "result.emit({'version': hou.applicationVersionString(), "
                        "'thread': ctx.session.info()['thread']})"
                    )
                },
            )
            return client.protocol_version, listed, result

    protocol_version, listed, response = asyncio.run(exercise())

    assert protocol_version == "2026-07-28"
    assert [tool.name for tool in listed.tools] == ["houdini_code_run"]
    assert response.is_error is False
    assert response.structured_content["ok"] is True
    assert response.structured_content["data"]["value"]["thread"] == "MainThread"
