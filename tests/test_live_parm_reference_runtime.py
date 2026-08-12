from __future__ import annotations

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


def test_live_parameter_reference_audit_classifies_scoped_channel_references() -> None:
    token = uuid.uuid4().hex[:10]
    root_name = "codemode_parm_refs_" + token
    external_name = "codemode_parm_refs_external_" + token
    root_path = "/obj/" + root_name
    external_path = "/obj/" + external_name
    source = r'''
parent = hou.node('/obj')
root = parent.createNode('subnet', args['root_name'])
external = parent.createNode('null', args['external_name'])
try:
    control = root.createNode('null', 'control')
    driver = root.createNode('null', 'driver')
    control.parm('tx').set(1.0)
    control.parm('ty').set(2.0)
    external.parm('tx').set(3.0)
    driver.parm('tx').setExpression('ch("../control/tx")')
    driver.parm('ty').setExpression('ch("' + args['root_path'] + '/control/ty")')
    driver.parm('tz').setExpression('ch("' + args['external_path'] + '/tx")')
    audit = ctx.parm_references.references(
        root,
        descendants=True,
        external_to=root,
        max_nodes=20,
        max_parms=10000,
        max_results=1000,
    )
    result.emit({
        'root': audit['root'],
        'external_to': audit['external_to'],
        'items': [
            item for item in audit['items']
            if item['source_parm'] in (
                driver.path() + '/tx', driver.path() + '/ty', driver.path() + '/tz'
            )
        ],
        'errors': audit['errors'],
    })
finally:
    root.destroy()
    external.destroy()
'''

    response = Controller().run(
        source,
        args={
            "root_name": root_name,
            "external_name": external_name,
            "root_path": root_path,
            "external_path": external_path,
        },
        policy={"label": "Houdini Code Mode parameter-reference audit proof"},
    )

    assert response["ok"] is True
    value = response["data"]["value"]
    assert value["root"] == root_path
    assert value["external_to"] == root_path
    assert value["errors"] == []
    assert {item["classification"] for item in value["items"]} == {
        "internal", "absolute_internal", "external"
    }
    assert {item["target_parm"] for item in value["items"]} == {
        root_path + "/control/tx",
        root_path + "/control/ty",
        external_path + "/tx",
    }
