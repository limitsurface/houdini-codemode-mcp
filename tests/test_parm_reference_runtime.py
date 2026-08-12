from __future__ import annotations

from types import SimpleNamespace

from houdini_codemode.runtime_parm_reference_source import PARM_REFERENCE_SOURCE


class FakeParm:
    def __init__(
        self, node, name, *, direct=None, refs=(), raw=None, expression=None, error=None
    ):
        self._node = node
        self._name = name
        self._direct = direct
        self._refs = refs
        self._raw = raw
        self._expression = expression
        self._error = error

    def path(self):
        return self._node.path() + "/" + self._name

    def getReferencedParm(self):
        if self._error:
            raise self._error
        return self._direct

    def references(self):
        return self._refs

    def isExpression(self):
        return self._expression is not None

    def expression(self):
        if self._expression is None:
            raise RuntimeError("not an expression")
        return self._expression

    def rawValue(self):
        return self._raw


class FakeFallbackParm:
    """Houdini 22-like parm that has no direct/reference convenience APIs."""

    def __init__(self, node, name, *, raw=None, expression=None):
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
    def __init__(self, path, parms=(), children=()):
        self._path = path
        self._parms = list(parms)
        self._children = list(children)
        self._relative = {}

    def path(self):
        return self._path

    def parms(self):
        return tuple(self._parms)

    def children(self):
        return tuple(self._children)

    def parm(self, name):
        return next((item for item in self._parms if item.path().endswith("/" + name)), None)

    def node(self, token):
        return self._relative.get(token)


def _service(root):
    def find_node(path):
        pending = [root]
        while pending:
            current = pending.pop()
            if current.path() == path:
                return current
            pending.extend(current.children())
        return None

    def find_parm(path):
        pending = [root]
        while pending:
            current = pending.pop()
            for parm in current.parms():
                if parm.path() == path:
                    return parm
            pending.extend(current.children())
        return None

    namespace = {"_hcm_hou": SimpleNamespace(node=find_node, parm=find_parm)}
    exec(PARM_REFERENCE_SOURCE, namespace)
    return namespace["_HCMParmReferenceService"]()


def test_references_uses_direct_reference_and_deduplicates_hom_target():
    root = FakeNode("/obj/root")
    target_node = FakeNode("/obj/root/control")
    target = FakeParm(target_node, "gain")
    plain = FakeParm(root, "plain")
    plain._direct = plain
    root._parms = [FakeParm(root, "drive", direct=target, refs=(target,)), plain]

    result = _service(root).references(root)

    assert result["count"] == 1
    assert result["items"] == [{
        "source_node": "/obj/root",
        "source_parm": "/obj/root/drive",
        "target_node": "/obj/root/control",
        "target_parm": "/obj/root/control/gain",
        "classification": "internal",
        "source": "direct",
        "token": None,
    }]


def test_references_falls_back_to_expression_and_marks_external_and_absolute_internal():
    root = FakeNode("/obj/root")
    child = FakeNode("/obj/root/child")
    inside = FakeNode("/obj/root/control")
    outside = FakeNode("/obj/outside")
    inside_target = FakeFallbackParm(inside, "gain")
    outside_target = FakeFallbackParm(outside, "gain")
    inside._parms = [inside_target]
    outside._parms = [outside_target]
    root._children = [child, inside, outside]
    child._relative["../control"] = inside
    child._parms = [
        FakeFallbackParm(child, "relative", raw='ch("../control/gain")'),
        FakeFallbackParm(child, "absolute", expression='ch("/obj/root/control/gain")'),
        FakeFallbackParm(child, "external", expression='ch("/obj/outside/gain")'),
    ]

    result = _service(root).references(root, descendants=True, external_to="/obj/root")

    assert [item["classification"] for item in result["items"]] == [
        "internal", "absolute_internal", "external"
    ]
    assert [item["source"] for item in result["items"]] == [
        "raw", "expression", "expression"
    ]


def test_references_reports_unresolved_tokens_and_recurses_children():
    root = FakeNode("/obj/root")
    child = FakeNode("/obj/root/child")
    root._children = [child]
    child._parms = [FakeFallbackParm(child, "drive", raw='ch("../missing/value")')]

    result = _service(root).references(root, descendants=True)

    assert result["count"] == 1
    assert result["items"][0]["classification"] == "unresolved"
    assert result["items"][0]["target_parm"] is None
    assert result["items"][0]["token"] == "../missing/value"
    assert result["meta"]["nodes_scanned"] == 2


def test_references_enforces_node_parm_result_and_error_caps():
    root = FakeNode("/obj/root")
    child = FakeNode("/obj/root/child")
    outside = FakeNode("/obj/outside")
    root._children = [child, outside]
    target_one = FakeParm(outside, "one")
    target_two = FakeParm(outside, "two")
    root._parms = [
        FakeParm(root, "broken", error=PermissionError("locked")),
        FakeParm(root, "one", direct=target_one),
        FakeParm(root, "two", direct=target_two),
    ]
    child._parms = [FakeParm(child, "three", direct=target_one)]
    service = _service(root)

    node_limited = service.references(root, descendants=True, max_nodes=1)
    assert node_limited["meta"]["node_limit_reached"] is True
    assert node_limited["meta"]["nodes_scanned"] == 1

    parm_limited = service.references(root, max_parms=1)
    assert parm_limited["meta"]["parm_limit_reached"] is True
    assert parm_limited["meta"]["error_count"] == 1

    result_limited = service.references(root, max_results=1, max_errors=1)
    assert result_limited["count"] == 1
    assert result_limited["meta"]["result_limit_reached"] is True
    assert result_limited["errors"] == [{
        "stage": "parm_get_referenced",
        "error": "locked",
        "node_path": "/obj/root",
        "parm_path": "/obj/root/broken",
    }]
