# Houdini Code Mode

Houdini Code Mode executes one self-contained Python/HOM program inside a live,
trusted local Houdini session and returns one bounded structured result.

The model-facing surface is one MCP tool, `houdini_code_run`. A small CLI uses
the same controller for development and diagnosis.

The initial viability, bounded inspection foundation, operational runtime, and
first compound extensions are implemented. See:

- [Architecture](docs/ARCHITECTURE.md)
- [Implementation checklist](docs/CHECKLIST.md)
- [CLI parity and deliberate differences](docs/PARITY.md)
- [Support matrix](docs/SUPPORT.md)

## Houdini setup

Create a Python shelf tool in Houdini and paste in
[`shelf_script/start_houdini_codemode_server.py`](shelf_script/start_houdini_codemode_server.py).
Run it and choose a port. The supplied server binds only to `127.0.0.1`; the
initial product is intentionally local and trusted rather than a network
execution service.

The controller installs its Houdini-side runtime on the first request and then
reuses it while its source hash and runtime version match. Restarting Houdini
simply causes the next request to install the runtime again.

## Development

```powershell
uv sync
uv run pytest
```

With Houdini's hrpyc server running on the default port:

```powershell
uv run houdini-codemode doctor
uv run houdini-codemode run --code "result.emit(hou.applicationVersionString())"
uv run pytest -m live
```

Run the local stdio MCP server with:

```powershell
uv run houdini-codemode-mcp
```

Submitted source is trusted and unsandboxed. It has the permissions of the
Houdini process. The runtime never saves the HIP implicitly. A wait timeout does
not cancel remote Python; a background waiter retains the shared endpoint gate
until Houdini returns, and `meta.completion` remains `unknown` to the caller.

## Program context

Each run receives fresh `hou`, `ctx`, `args`, and `result` globals. Raw `hou`
provides the full Houdini API. Current semantic extensions include:

- bounded node, parameter, geometry, Copernicus, LOP, and HDA inspection plus
  dry-run/fresh-instance/reference HDA validation plus promotion and
  package/update planning;
- OpenCL validation and synchronization across SOP, COP, and DOP;
- Python SOP/COP binding and VEX wrangle spare-parameter synchronization;
- bounded, manifest-only `.asData` node/network artifacts;
- audited, transactional Copernicus image file import/export.

Call `result.emit(value)` at most once. Prefer summary, then bounded projection,
then an artifact reference; do not emit broad raw `.asData` payloads.

Discover the current extension surface inside a run instead of guessing:

```python
result.emit(ctx.capabilities())
```

Use `ctx.help("ctx.opencl.sync")` for an exact signature, effect category, and
summary. Clients that support Codex-style skills should install the bundled
`skills/houdini-codemode` skill for scene-construction, Copernicus, VEX,
OpenCL, and version-matched local Houdini documentation guidance. The MCP tool
remains independently usable when a client does not support skills.

## Version-matched Houdini help

The skill ships the help-preparation script but not SideFX's generated help
corpus. Locate the raw help directory for the installed Houdini version (for
example `C:\Program Files\Side Effects Software\Houdini 22.0.368\houdini\help`)
and run:

```powershell
python <installed-skill>\scripts\prepare_houdini_help.py `
  --source "<houdini-install>\houdini\help"
```

This creates `<installed-skill>\references\help_prepared\` locally. It is
generated installation data and is intentionally excluded from this repo and
distribution.
