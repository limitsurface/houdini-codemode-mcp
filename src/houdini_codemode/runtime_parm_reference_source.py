"""Houdini-side bounded parameter dependency inspection source."""

from __future__ import annotations


PARM_REFERENCE_SOURCE = r'''
import re as _hcm_parm_ref_re


_HCM_PARM_REF_CHANNEL_PATTERN = _hcm_parm_ref_re.compile(
    r"\bch(?:s|f|i|v|p|raw)?\s*\(\s*['\"]([^'\"]+)['\"]"
)
_HCM_PARM_REF_TEXT_LIMIT = 65536
_HCM_PARM_REF_TOKENS_PER_PARM = 100


def _hcm_parm_ref_positive(value, name, ceiling):
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(name + " must be an integer")
    if value <= 0:
        raise ValueError(name + " must be positive")
    return min(value, ceiling)


def _hcm_parm_ref_error_text(exc):
    try:
        text = str(exc)
    except BaseException:
        text = exc.__class__.__name__
    return text[:512]


def _hcm_parm_ref_node_path(parm_path):
    head, separator, _tail = parm_path.rpartition("/")
    return head if separator else ""


def _hcm_parm_ref_within(node_path, root_path):
    root = root_path.rstrip("/") or "/"
    return node_path == root or (root != "/" and node_path.startswith(root + "/"))


def _hcm_parm_ref_resolve_node(value):
    if isinstance(value, str):
        value = _hcm_hou.node(value)
    if value is None:
        raise ValueError("Node not found: " + str(value))
    return value


def _hcm_parm_ref_resolve_token(source_node, token):
    if token.startswith("/"):
        return _hcm_hou.parm(token)
    if "/" not in token:
        return source_node.parm(token)
    node_token, _separator, parm_name = token.rpartition("/")
    target_node = source_node.node(node_token)
    return target_node.parm(parm_name) if target_node is not None else None


def _hcm_parm_ref_texts(parm, add_error, node_path, parm_path, state):
    rows = []
    is_expression = getattr(parm, "isExpression", None)
    if callable(is_expression):
        try:
            expression_enabled = bool(is_expression())
        except BaseException as exc:
            add_error("parm_is_expression", exc, node_path, parm_path)
            expression_enabled = False
        if expression_enabled:
            try:
                expression = parm.expression()
                if isinstance(expression, str):
                    rows.append((expression, "expression"))
            except BaseException as exc:
                add_error("parm_expression", exc, node_path, parm_path)
    elif callable(getattr(parm, "expression", None)):
        try:
            expression = parm.expression()
            if isinstance(expression, str):
                rows.append((expression, "expression"))
        except BaseException:
            pass
    for name in ("rawValue", "unexpandedString"):
        method = getattr(parm, name, None)
        if not callable(method):
            continue
        try:
            raw = method()
        except BaseException as exc:
            add_error("parm_" + name, exc, node_path, parm_path)
            continue
        if isinstance(raw, str):
            rows.append((raw, "raw"))
        break
    result = []
    for text, kind in rows:
        if len(text) > _HCM_PARM_REF_TEXT_LIMIT:
            state["reference_text_truncated"] = True
            text = text[:_HCM_PARM_REF_TEXT_LIMIT]
        result.append((text, kind))
    return result


def _hcm_parm_ref_classification(target_path, token, scope_root):
    if target_path is None:
        return "unresolved"
    target_node = _hcm_parm_ref_node_path(target_path)
    if not _hcm_parm_ref_within(target_node, scope_root):
        return "external"
    if isinstance(token, str) and token.startswith("/"):
        return "absolute_internal"
    return "internal"


class _HCMParmReferenceService:
    """Read-only, capped parameter-reference traversal for arbitrary nodes."""

    def references(
        self,
        node,
        descendants=False,
        external_to=None,
        max_nodes=1000,
        max_parms=10000,
        max_results=1000,
        max_errors=100,
    ):
        if not isinstance(descendants, bool):
            raise TypeError("descendants must be a boolean")
        node_limit = _hcm_parm_ref_positive(max_nodes, "max_nodes", 10000)
        parm_limit = _hcm_parm_ref_positive(max_parms, "max_parms", 100000)
        result_limit = _hcm_parm_ref_positive(max_results, "max_results", 10000)
        error_limit = _hcm_parm_ref_positive(max_errors, "max_errors", 1000)
        root = _hcm_parm_ref_resolve_node(node)
        try:
            root_path = str(root.path())
        except BaseException as exc:
            raise ValueError("Unable to read root node path: " + _hcm_parm_ref_error_text(exc))
        if external_to is None:
            scope_root = root_path
        else:
            scope = _hcm_parm_ref_resolve_node(external_to)
            try:
                scope_root = str(scope.path())
            except BaseException as exc:
                raise ValueError("Unable to read external_to path: " + _hcm_parm_ref_error_text(exc))

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
            item = {"stage": stage, "error": _hcm_parm_ref_error_text(exc)}
            if node_path is not None:
                item["node_path"] = node_path
            if parm_path is not None:
                item["parm_path"] = parm_path
            errors.append(item)

        pending = [root]
        seen_nodes = set()
        seen_rows = set()
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
            if current_path in seen_nodes:
                continue
            seen_nodes.add(current_path)
            state["nodes_scanned"] += 1
            try:
                parms = tuple(current.parms())
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
                candidates = []
                hom_candidates = []
                direct = getattr(parm, "getReferencedParm", None)
                if callable(direct):
                    try:
                        target = direct()
                    except BaseException as exc:
                        add_error("parm_get_referenced", exc, current_path, source_path)
                    else:
                        if target is not None:
                            try:
                                direct_path = str(target.path())
                            except BaseException as exc:
                                add_error("target_path", exc, current_path, source_path)
                            else:
                                # Houdini's getReferencedParm() returns the
                                # parameter itself when it has no channel ref.
                                if direct_path != source_path:
                                    hom_candidates.append((target, "direct", None))
                for owner in (parm, getattr(parm, "tuple", lambda: None)()):
                    method = getattr(owner, "references", None) if owner is not None else None
                    if not callable(method):
                        continue
                    try:
                        hom_candidates.extend((target, "hom", None) for target in method())
                    except BaseException as exc:
                        add_error("parm_references", exc, current_path, source_path)
                token_seen = set()
                for text, kind in _hcm_parm_ref_texts(
                    parm, add_error, current_path, source_path, state
                ):
                    for match in _HCM_PARM_REF_CHANNEL_PATTERN.finditer(text):
                        token = match.group(1)
                        if token in token_seen:
                            continue
                        token_seen.add(token)
                        if len(token_seen) > _HCM_PARM_REF_TOKENS_PER_PARM:
                            state["reference_token_truncated"] = True
                            break
                        try:
                            target = _hcm_parm_ref_resolve_token(current, token)
                        except BaseException as exc:
                            add_error("reference_resolve", exc, current_path, source_path)
                            target = None
                        candidates.append((target, kind, token))
                # Parsed tokens retain their spelling, which is needed to flag an
                # absolute path that happens to resolve inside the audit scope.
                candidates.extend(hom_candidates)
                target_seen = set()
                for target, source, token in candidates:
                    try:
                        target_path = str(target.path()) if target is not None else None
                    except BaseException as exc:
                        add_error("target_path", exc, current_path, source_path)
                        continue
                    target_key = target_path if target_path is not None else "unresolved:" + str(token)
                    if target_key in target_seen:
                        continue
                    target_seen.add(target_key)
                    classification = _hcm_parm_ref_classification(
                        target_path, token, scope_root
                    )
                    row_key = (source_path, target_path, token, classification)
                    if row_key in seen_rows:
                        continue
                    seen_rows.add(row_key)
                    state["reference_count"] += 1
                    if len(rows) >= result_limit:
                        state["result_limit"] = True
                        break
                    rows.append(
                        {
                            "source_node": current_path,
                            "source_parm": source_path,
                            "target_node": (
                                _hcm_parm_ref_node_path(target_path)
                                if target_path is not None
                                else None
                            ),
                            "target_parm": target_path,
                            "classification": classification,
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
                    children = tuple(current.children())
                except BaseException as exc:
                    add_error("node_children", exc, node_path=current_path)
                    children = ()
                pending.extend(reversed(children))

        truncated = (
            state["node_limit"]
            or state["parm_limit"]
            or state["result_limit"]
            or state["reference_text_truncated"]
            or state["reference_token_truncated"]
        )
        return {
            "root": root_path,
            "external_to": scope_root if external_to is not None else None,
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
