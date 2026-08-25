# Houdini Code Mode MCP

Houdini Code Mode gives agents one MCP tool for working in a live Houdini
session. Each call runs a self-contained Python program with the full Houdini
Python API, focused `ctx` extensions for compound workflows, and a prepared
skill with practical guidance and searchable, version-matched Houdini help.

Submitted code runs locally with the permissions of the Houdini process. Code
Mode never saves the HIP file implicitly.

## Install

Requires Python 3.11 or newer and a local Houdini installation.

### 1. Install the MCP server

Install the server with `pipx`:

```powershell
python -m pip install --user pipx
python -m pipx ensurepath
python -m pipx install git+https://github.com/limitsurface/houdini-codemode.git
```

Then add `houdini-codemode-mcp` as a stdio MCP server in your MCP harness. A
typical server entry is:

```json
{
  "command": "houdini-codemode-mcp"
}
```

### 2. Add the Houdini shelf script

Create a Python shelf tool in Houdini and paste in
[`shelf_script/start_houdini_codemode_server.py`](shelf_script/start_houdini_codemode_server.py).
Run the shelf tool and choose a port. The server binds only to `127.0.0.1` and
is intended for trusted local use.

The Houdini-side runtime is installed on the first request and reused until its
source or version changes. Restarting Houdini is fine; the next request installs
the runtime again.

### 3. Install the skill and prepare Houdini help

Copy [`skills/houdini-codemode`](skills/houdini-codemode) into the skill
directory used by your agent harness.

The skill includes its help-preparation script, but not SideFX's generated help
corpus. Locate the help directory in your Houdini installation and run:

```powershell
python <installed-skill>\scripts\prepare_houdini_help.py `
  --source "C:\Program Files\Side Effects Software\Houdini xx.x.xxx\houdini\help"
```

This creates `<installed-skill>\references\help_prepared\`, giving the agent a
searchable reference matched to the installed Houdini version. It does not
modify the Houdini installation.

## Extension highlights

### Copernicus and OpenCL

Copernicus-focused OpenCL extensions remove much of the binding and testing
friction around custom COP kernels. They provide binding synchronization,
validation, image import/export, and guidance for Houdini's coordinate,
sampling, and layer conventions.

### HDA packaging

HDA tooling supports efficient, guarded asset packaging: inspect and validate
definitions, audit references, plan promotion, create or copy libraries, build
interfaces and tools, preserve text sections, and update explicitly owned
assets without implicitly saving the scene.

### Bounded inspection and artifacts

Focused summaries make nodes, parameters, geometry, Copernicus networks, LOPs,
and HDAs practical to inspect without flooding the model context. When a
workflow needs lossless node or network state, bounded artifacts keep the large
payload on disk and return a compact manifest instead.

## Using Code Mode

The MCP surface contains one tool: `houdini_code_run`. Every run receives fresh
`hou`, `ctx`, `args`, and `result` globals. Use raw `hou` for the complete HOM
API and `ctx` for focused extensions.

Discover the available extension surface inside a run:

```python
result.emit(ctx.capabilities())
```

Extension help includes the exact signature, effect category, and summary:

```python
result.emit(ctx.help("ctx.opencl.sync"))
```

Call `result.emit(value)` at most once. Prefer a summary, then a bounded
projection, then an artifact reference.

## Houdini CLI

Houdini Code Mode MCP is the successor to
[Houdini CLI](https://github.com/limitsurface/houdini-cli). The CLI remains
available for command-oriented Houdini workflows.
