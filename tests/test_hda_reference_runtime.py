from __future__ import annotations

from types import SimpleNamespace

import pytest

from houdini_codemode.runtime_hda_reference_source import HDA_REFERENCE_SOURCE


class FakeType:
    def __init__(self, definition):
        self._definition = definition

    def definition(self):
        return self._definition


class FakeParm:
    def __init__(self, node, name, targets=(), failure=None):
        self._node = node
        self._name = name
        self._targets = targets
        self._failure = failure

    def path(self):
        return self._node.path() + "/" + self._name

    def references(self):
        if self._failure:
            raise self._failure
        return self._targets


class FakeH22Parm:
    """A Houdini 22-style parm: no references() API."""

    def __init__(self, node, name, raw=None, expression=None):
        self._node = node
        self._name = name
        self._raw = raw
        self._expression = expression

    def path(self):
        return self._node.path() + "/" + self._name

    def isExpression(self):
        return self._expression is not None

    def expression(self):
        if self._expression is None:
            raise RuntimeError("not an expression")
        return self._expression

    def rawValue(self):
        return self._raw


class FakeNode:
    def __init__(self, path, definition=object(), parms=(), children=()):
        self._path = path
        self._type = FakeType(definition)
        self._parms = list(parms)
        self._children = list(children)
        self._nodes = {}

    def path(self):
        return self._path

    def type(self):
        return self._type

    def parms(self):
        return tuple(self._parms)

    def children(self):
        return tuple(self._children)

    def parm(self, name):
        return next((parm for parm in self._parms if parm.path().endswith("/" + name)), None)

    def node(self, path):
        return self._nodes.get(path)


def _service(root):
    def find_parm(path):
        pending = [root]
        while pending:
            current = pending.pop()
            for parm in current.parms():
                if parm.path() == path:
                    return parm
            pending.extend(current.children())
        return None

    namespace = {"_hcm_hou": SimpleNamespace(
        node=lambda value: root if value == root.path() else None,
        parm=find_parm,
    )}
    exec(HDA_REFERENCE_SOURCE, namespace)
    return namespace["_HCMHdaReferenceService"]()


def test_audit_reports_only_external_references_and_can_include_descendants() -> None:
    root = FakeNode("/obj/asset")
    inside = FakeNode("/obj/asset/control")
    outside = FakeNode("/obj/outside")
    root._parms = [FakeParm(root, "local", (FakeParm(inside, "gain"),))]
    child = FakeNode("/obj/asset/child")
    child._parms = [FakeParm(child, "drive", (FakeParm(outside, "amount"),))]
    root._children = [child]
    service = _service(root)

    direct = service.audit("/obj/asset")
    recursive = service.audit("/obj/asset", descendants=True)

    assert direct["count"] == 0
    assert recursive["count"] == 1
    assert recursive["items"] == [{
        "source_node": "/obj/asset/child",
        "source_parm": "/obj/asset/child/drive",
        "target_node": "/obj/outside",
        "target_parm": "/obj/outside/amount",
        "source": "hom",
        "token": None,
    }]


def test_audit_enforces_parm_and_result_limits() -> None:
    root = FakeNode("/obj/asset")
    outside = FakeNode("/obj/outside")
    root._parms = [
        FakeParm(root, "one", (FakeParm(outside, "one"),)),
        FakeParm(root, "two", (FakeParm(outside, "two"),)),
    ]
    service = _service(root)

    parms_limited = service.audit(root, max_parms=1)
    results_limited = service.audit(root, max_results=1)

    assert parms_limited["count"] == 1
    assert parms_limited["meta"]["parm_limit_reached"] is True
    assert results_limited["count"] == 1
    assert results_limited["meta"]["result_limit_reached"] is True
    assert results_limited["meta"]["truncated"] is True


def test_audit_enforces_node_limit_before_descendant_work() -> None:
    root = FakeNode("/obj/asset")
    outside = FakeNode("/obj/outside")
    child = FakeNode("/obj/asset/child")
    child._parms = [FakeParm(child, "drive", (FakeParm(outside, "amount"),))]
    root._children = [child]

    result = _service(root).audit(root, descendants=True, max_nodes=1)

    assert result["count"] == 0
    assert result["meta"]["nodes_scanned"] == 1
    assert result["meta"]["node_limit_reached"] is True


def test_h22_fallback_resolves_expression_and_raw_channel_tokens() -> None:
    root = FakeNode("/obj/asset")
    child = FakeNode("/obj/asset/child")
    outside = FakeNode("/obj/outside")
    external = FakeH22Parm(outside, "amount")
    outside._parms = [external]
    root._children = [outside, child]
    child._nodes["../../outside"] = outside
    child._parms = [
        FakeH22Parm(child, "expr", expression='ch("/obj/outside/amount")'),
        FakeH22Parm(child, "raw", raw='ch("../../outside/amount")'),
        FakeH22Parm(child, "plain", raw="1"),
    ]

    result = _service(root).audit(root, descendants=True)

    assert result["count"] == 2
    assert {row["source"] for row in result["items"]} == {"expression", "raw"}
    assert {row["token"] for row in result["items"]} == {
        "/obj/outside/amount", "../../outside/amount"
    }
    assert result["errors"] == []


def test_audit_reports_inaccessible_references_without_failing_scan() -> None:
    root = FakeNode("/obj/asset")
    outside = FakeNode("/obj/outside")
    root._parms = [
        FakeParm(root, "blocked", failure=PermissionError("locked reference")),
        FakeParm(root, "valid", (FakeParm(outside, "amount"),)),
    ]

    result = _service(root).audit(root)

    assert result["count"] == 1
    assert result["meta"]["error_count"] == 1
    assert result["errors"] == [{
        "stage": "parm_references",
        "error": "locked reference",
        "node_path": "/obj/asset",
        "parm_path": "/obj/asset/blocked",
    }]


def test_audit_rejects_non_hda_nodes() -> None:
    node = FakeNode("/obj/plain", definition=None)

    with pytest.raises(ValueError, match="not an HDA instance"):
        _service(node).audit(node)
