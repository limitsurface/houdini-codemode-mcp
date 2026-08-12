"""Houdini-side VEX wrangle spare-parameter extension source."""

from __future__ import annotations


WRANGLE_SOURCE = r'''
_HCM_WRANGLE_TYPES = {
    ("Sop", "attribwrangle"),
    ("Lop", "attribwrangle"),
    ("Dop", "geometrywrangle"),
    ("Dop", "popwrangle"),
    ("Dop", "gasfieldwrangle"),
}


def _hcm_wrangle_require(node):
    identity = (node.type().category().name(), node.type().name())
    snippet = node.parm("snippet")
    if identity not in _HCM_WRANGLE_TYPES or snippet is None:
        raise ValueError("Node is not a supported VEX wrangle: " + node.path())
    return snippet


def _hcm_wrangle_spare_names(node):
    rows = []
    for parm in node.spareParms():
        try:
            template_type = parm.parmTemplate().type().name()
        except BaseException:
            template_type = None
        if template_type not in ("Folder", "FolderSet"):
            rows.append(str(parm.name()))
    return rows


class _HCMWrangleService:
    def __init__(self, mutation_events):
        self._mutation_events = mutation_events

    def sync(self, node, clear=False):
        if not isinstance(clear, bool):
            raise TypeError("clear must be a boolean")
        resolved = _hcm_resolve_node(node)
        _hcm_wrangle_require(resolved)
        before = _hcm_wrangle_spare_names(resolved)
        event = {
            "kind": "wrangle.spare_parms_sync",
            "helper": "ctx.wrangle.sync",
            "node_path": resolved.path(),
            "clear": clear,
            "status": "started",
        }
        self._mutation_events.append(event)
        if clear:
            resolved.removeSpareParms()
        module = __import__("vexpressionmenu")
        module.createSpareParmsFromChCalls(resolved, "snippet")
        after = _hcm_wrangle_spare_names(resolved)
        event["status"] = "complete"
        event["created_count"] = len(
            [name for name in after if clear or name not in before]
        )
        return {
            "node_path": resolved.path(),
            "cleared": clear,
            "before": before,
            "after": after,
            "created": [name for name in after if clear or name not in before],
        }

    def clear(self, node):
        resolved = _hcm_resolve_node(node)
        _hcm_wrangle_require(resolved)
        removed = _hcm_wrangle_spare_names(resolved)
        event = {
            "kind": "wrangle.spare_parms_clear",
            "helper": "ctx.wrangle.clear",
            "node_path": resolved.path(),
            "removed_count": len(removed),
        }
        resolved.removeSpareParms()
        self._mutation_events.append(event)
        return {"node_path": resolved.path(), "removed": removed}
'''
