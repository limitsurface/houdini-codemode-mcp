"""Build the embedded, bounded context-extension discovery service."""

from __future__ import annotations

import json

from .capabilities import CAPABILITIES


_REGISTRY_JSON = json.dumps(CAPABILITIES, ensure_ascii=False, separators=(",", ":"))

HELP_SOURCE = "_HCM_HELP_REGISTRY = " + _REGISTRY_JSON + r'''


def _hcm_help_limit(value):
    return _hcm_helper_int(value, "max_items", 50, 1, 100)


class _HCMHelpService:
    """Bounded, read-only discovery for Code Mode context extensions."""

    def list(self, query=None, max_items=50):
        maximum = _hcm_help_limit(max_items)
        if query is not None and (not isinstance(query, str) or not query.strip()):
            raise TypeError("query must be a non-empty string or None")
        needle = query.strip().lower() if query is not None else None
        rows = []
        total = 0
        for service in _HCM_HELP_REGISTRY:
            haystack = service["name"] + " " + service["purpose"]
            if needle is not None:
                haystack += " " + " ".join(
                    method[0] + " " + method[2] for method in service["methods"]
                )
                if needle not in haystack.lower():
                    continue
            total += 1
            if len(rows) < maximum:
                rows.append(
                    {
                        "name": service["name"],
                        "purpose": service["purpose"],
                        "method_count": len(service["methods"]),
                    }
                )
        return {
            "schema": "houdini-codemode.ctx-capabilities/v1",
            "protocol_version": _HCM_PROTOCOL_VERSION,
            "runtime_version": _HCM_RUNTIME_VERSION,
            "globals": ["hou", "ctx", "args", "result"],
            "services": rows,
            "count": len(rows),
            "total": total,
            "limit": maximum,
            "truncated": total > len(rows),
            "hint": "Use ctx.help.get('ctx.service') or ctx.help.get('ctx.service.method') for signatures.",
        }

    def get(self, name):
        if not isinstance(name, str) or not name.strip():
            raise TypeError("name must be a non-empty string")
        requested = name.strip()
        parts = requested.split(".")
        service_name = ".".join(parts[:2]) if len(parts) >= 2 else requested
        method_name = parts[2] if len(parts) == 3 else None
        if len(parts) > 3:
            raise ValueError("Capability names use ctx.service or ctx.service.method")
        for service in _HCM_HELP_REGISTRY:
            if service["name"] != service_name:
                continue
            methods = [
                {"signature": method[0], "effect": method[1], "summary": method[2]}
                for method in service["methods"]
                if method_name is None or method[0].split("(", 1)[0] == method_name
            ]
            if method_name is not None and not methods:
                raise ValueError("Unknown context capability: " + requested)
            return {
                "name": service["name"] if method_name is None else requested,
                "service": service["name"],
                "purpose": service["purpose"],
                "methods": methods,
                "trusted": True,
                "sandboxed": False,
            }
        raise ValueError("Unknown context service: " + service_name)

    __call__ = get
'''
