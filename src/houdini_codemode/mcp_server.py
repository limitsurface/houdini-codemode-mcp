"""One-tool MCP adapter for Houdini Code Mode."""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer

from . import __version__
from .capabilities import capability_names
from .controller import Controller


_SERVICE_NAMES = ", ".join(capability_names())


mcp = MCPServer(
    "houdini-codemode",
    version=__version__,
    instructions=(
        "Use houdini_code_run as the model-facing Houdini action instead of GUI "
        "clicks or legacy houdini-cli eval unless the user explicitly asks for them. "
        "Submit one self-contained program that composes dependent discovery, edits, "
        "and verification; avoid repeated tiny calls. Fresh globals are hou, ctx, "
        "args, and result. Put request data in args and call result.emit(value) at "
        "most once with compact plain data. Raw hou is the complete HOM API. Discover "
        "extensions with ctx.capabilities() and ctx.help('ctx.service.method'); current "
        "services are " + _SERVICE_NAMES + ". Prefer bounded projections, then "
        "artifacts, and never emit broad .asData payloads. Code is trusted and "
        "unsandboxed; never save the HIP implicitly. If meta.completion is unknown, "
        "do not retry mutations until completion is independently known. Clients "
        "that support skills should load the bundled houdini-codemode skill for "
        "Copernicus, VEX, OpenCL, and scene-construction guidance."
    ),
)


@mcp.tool()
def houdini_code_run(
    source: str,
    args: dict[str, Any] | None = None,
    instance: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one bounded program in live Houdini and return its structured envelope.

    The submitted source receives fresh globals named hou, ctx, args, and result.
    Put request values in args, compose dependent work in this one call, and use
    result.emit(value) at most once. Raw hou is the complete HOM API. Discover
    exact bounded extension signatures with ctx.capabilities() and
    ctx.help('ctx.service.method'). Prefer summaries and projections, then
    artifacts; never return broad .asData payloads. Code is trusted and
    unsandboxed. Do not save the HIP implicitly. A local wait timeout does not
    prove Houdini stopped; inspect meta.completion before retrying mutations.
    """
    return Controller().run(source, args=args, instance=instance, policy=policy)


def main() -> None:
    """Run the local MCP server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
