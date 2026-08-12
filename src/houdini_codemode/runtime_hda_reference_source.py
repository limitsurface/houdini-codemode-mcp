"""Read-only, bounded auditing of HDA parameter references in Houdini."""

from __future__ import annotations


HDA_REFERENCE_SOURCE = r'''
import re as _hcm_hda_ref_re


_HCM_HDA_REF_CHANNEL_PATTERN = _hcm_hda_ref_re.compile(
    r"\bch(?:s|f|i|v|p|raw)?\s*\(\s*['\"]([^'\"]+)['\"]"
)
_HCM_HDA_REF_TOKENS_PER_PARM = 100
_HCM_HDA_REF_TEXT_PER_PARM = 65536


def _hcm_hda_ref_positive(value, name, ceiling):
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(name + " must be an integer")
    if value <= 0:
        raise ValueError(name + " must be positive")
    return min(value, ceiling)


def _hcm_hda_ref_error_text(exc):
    try:
        text = str(exc)
    except BaseException:
        text = exc.__class__.__name__
    return text[:512]


def _hcm_hda_ref_within(path, root):
    root = root.rstrip("/") or "/"
    return path == root or (root != "/" and path.startswith(root + "/"))


def _hcm_hda_ref_node_path(parm_path):
    head, separator, _tail = parm_path.rpartition("/")
    return head if separator else ""


def _hcm_hda_ref_resolve_token(parm, source_node, token):
    if token.startswith("/"):
        target = _hcm_hou.parm(token)
    elif "/" not in token:
        target = source_node.parm(token)
    else:
        node_token, _separator, parm_name = token.rpartition("/")
        target_node = source_node.node(node_token)
        target = target_node.parm(parm_name) if target_node is not None else None
    return target


def _hcm_hda_ref_expression_text(parm, add_error, node_path, parm_path):
    is_expression = getattr(parm, "isExpression", None)
    if callable(is_expression):
        try:
            if not is_expression():
                return None
        except BaseException as exc:
            add_error("parm_is_expression", exc, node_path, parm_path)
            return None
    expression = getattr(parm, "expression", None)
    if not callable(expression):
        return None
    try:
        return expression()
    except BaseException:
        # expression() normally raises for a non-expression parameter.
        return None


def _hcm_hda_ref_raw_text(parm, add_error, node_path, parm_path):
    for name in ("rawValue", "unexpandedString"):
        method = getattr(parm, name, None)
        if not callable(method):
            continue
        try:
            value = method()
        except BaseException as exc:
            add_error("parm_" + name, exc, node_path, parm_path)
            continue
        return value if isinstance(value, str) else None
    return None


class _HCMHdaReferenceService:
    """Inspect HDA parameter dependencies without changing the scene."""

    def audit(
        self,
        node,
        descendants=False,
        max_nodes=1000,
        max_parms=10000,
        max_results=1000,
        max_errors=100,
    ):
        if not isinstance(descendants, bool):
            raise TypeError("descendants must be a boolean")
        node_limit = _hcm_hda_ref_positive(max_nodes, "max_nodes", 10000)
        parm_limit = _hcm_hda_ref_positive(max_parms, "max_parms", 100000)
        result_limit = _hcm_hda_ref_positive(max_results, "max_results", 10000)
        error_limit = _hcm_hda_ref_positive(max_errors, "max_errors", 1000)
        resolved = _hcm_hou.node(node) if isinstance(node, str) else node
        if resolved is None:
            raise ValueError("Node not found: " + str(node))
        try:
            root_path = str(resolved.path())
            definition = resolved.type().definition()
        except BaseException as exc:
            raise ValueError("Unable to inspect HDA node: " + _hcm_hda_ref_error_text(exc))
        if definition is None:
            raise ValueError("Node is not an HDA instance: " + root_path)

        rows = []
        errors = []
        state = {
            "nodes_scanned": 0,
            "parms_scanned": 0,
            "reference_count": 0,
            "error_count": 0,
            "node_limit": False,
            "parm_limit": False,
            "result_limit": False,
            "errors_truncated": False,
            "reference_text_truncated": False,
            "reference_token_truncated": False,
        }

        def add_error(stage, exc, node_path=None, parm_path=None):
            state["error_count"] += 1
            if len(errors) >= error_limit:
                state["errors_truncated"] = True
                return
            row = {"stage": stage, "error": _hcm_hda_ref_error_text(exc)}
            if node_path is not None:
                row["node_path"] = node_path
            if parm_path is not None:
                row["parm_path"] = parm_path
            errors.append(row)

        pending = [resolved]
        while pending:
            if state["nodes_scanned"] >= node_limit:
                state["node_limit"] = True
                break
            current = pending.pop()
            try:
                current_path = str(current.path())
            except BaseException as exc:
                add_error("node_path", exc)
                continue
            state["nodes_scanned"] += 1
            try:
                parms = current.parms()
            except BaseException as exc:
                add_error("node_parms", exc, node_path=current_path)
                parms = ()
            for parm in parms:
                if state["parms_scanned"] >= parm_limit:
                    state["parm_limit"] = True
                    break
                state["parms_scanned"] += 1
                try:
                    source_path = str(parm.path())
                except BaseException as exc:
                    add_error("parm_path", exc, node_path=current_path)
                    continue
                targets = []
                hom_references = False
                for owner in (parm, getattr(parm, "tuple", lambda: None)()):
                    method = getattr(owner, "references", None) if owner is not None else None
                    if not callable(method):
                        continue
                    hom_references = True
                    try:
                        targets.extend((target, "hom", None) for target in method())
                    except BaseException as exc:
                        add_error("parm_references", exc, current_path, source_path)
                if not hom_references:
                    expression = _hcm_hda_ref_expression_text(
                        parm, add_error, current_path, source_path
                    )
                    raw = _hcm_hda_ref_raw_text(
                        parm, add_error, current_path, source_path
                    )
                    tokens = set()
                    for text, kind in ((expression, "expression"), (raw, "raw")):
                        if not isinstance(text, str):
                            continue
                        if len(text) > _HCM_HDA_REF_TEXT_PER_PARM:
                            state["reference_text_truncated"] = True
                            text = text[:_HCM_HDA_REF_TEXT_PER_PARM]
                        for match in _HCM_HDA_REF_CHANNEL_PATTERN.finditer(text):
                            token = match.group(1)
                            if token in tokens:
                                continue
                            tokens.add(token)
                            if len(tokens) > _HCM_HDA_REF_TOKENS_PER_PARM:
                                state["reference_token_truncated"] = True
                                break
                            try:
                                target = _hcm_hda_ref_resolve_token(
                                    parm, current, token
                                )
                            except BaseException as exc:
                                add_error(
                                    "reference_resolve", exc, current_path, source_path
                                )
                                continue
                            if target is not None:
                                targets.append((target, kind, token))
                seen_targets = set()
                for target, source, token in targets:
                    try:
                        target_path = str(target.path())
                    except BaseException as exc:
                        add_error("target_path", exc, current_path, source_path)
                        continue
                    if target_path in seen_targets:
                        continue
                    seen_targets.add(target_path)
                    state["reference_count"] += 1
                    if _hcm_hda_ref_within(_hcm_hda_ref_node_path(target_path), root_path):
                        continue
                    if len(rows) >= result_limit:
                        state["result_limit"] = True
                        break
                    rows.append(
                        {
                            "source_node": current_path,
                            "source_parm": source_path,
                            "target_node": _hcm_hda_ref_node_path(target_path),
                            "target_parm": target_path,
                            "source": source,
                            "token": token,
                        }
                    )
                if state["result_limit"]:
                    break
            if state["parm_limit"] or state["result_limit"]:
                break
            if descendants:
                try:
                    children = current.children()
                except BaseException as exc:
                    add_error("node_children", exc, node_path=current_path)
                    children = ()
                # Reverse preserves Houdini's child ordering while using a stack.
                pending.extend(reversed(tuple(children)))

        truncated = (
            state["node_limit"]
            or state["parm_limit"]
            or state["result_limit"]
            or state["reference_text_truncated"]
            or state["reference_token_truncated"]
        )
        return {
            "root": root_path,
            "descendants": descendants,
            "count": len(rows),
            "items": rows,
            "errors": errors,
            "meta": {
                "nodes_scanned": state["nodes_scanned"],
                "parms_scanned": state["parms_scanned"],
                "reference_count": state["reference_count"],
                "error_count": state["error_count"],
                "limits": {
                    "max_nodes": node_limit,
                    "max_parms": parm_limit,
                    "max_results": result_limit,
                    "max_errors": error_limit,
                },
                "truncated": truncated,
                "node_limit_reached": state["node_limit"],
                "parm_limit_reached": state["parm_limit"],
                "result_limit_reached": state["result_limit"],
                "errors_truncated": state["errors_truncated"],
                "reference_text_truncated": state["reference_text_truncated"],
                "reference_token_truncated": state["reference_token_truncated"],
            },
        }
'''
