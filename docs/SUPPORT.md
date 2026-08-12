# Support Matrix

Last updated: 2026-08-12.

| Surface | Version | Evidence | Status |
| --- | --- | --- | --- |
| External controller | CPython 3.12 on Windows | 94 collected: 93 passed, 1 optional skipped; CLI, MCP in-memory/stdio, package build | Supported development target |
| Houdini runtime | Houdini 22.0.368, embedded Python 3.11 | Live main-thread, inspection, mutation, artifact, Cop file effects, HDA planning/reference, and cleanup tests | Supported live target |
| MCP | Specification 2026-07-28 through Python SDK v2 | In-memory and spawned stdio client tests; exactly one tool | Supported local transport |
| Houdini server | Loopback hrpyc on ports 18811–18814 | Default-port live suite and Code Mode-owned shelf bootstrap | Supported local deployment |
| Additional Houdini versions | Unverified | None yet | Not claimed |
| macOS/Linux | Unverified | Unit behavior runs without the Windows mutex, but no live Houdini evidence | Not claimed |
| Headless hython | Unverified | Main-thread/shelf assumptions differ | Not claimed |
| Multiple Houdini instances | Optional test via `HOUDINI_CODEMODE_SECOND_PORT` | Test is present; second live instance has not been supplied | Not yet evidenced |

The embedded runtime is plain Python 3.11-compatible source delivered over
RPyC. The external wheel is not installed into Houdini. Every additional
Houdini/Python combination must pass the runtime and live integration suite
before it is added as supported.

To exercise two instances, start a second Code Mode shelf server on a distinct
port and run:

```powershell
$env:HOUDINI_CODEMODE_SECOND_PORT = "18812"
uv run pytest tests/test_live_integration.py -k distinct_ports
```

The test runs bounded programs concurrently and verifies that distinct endpoint
mutexes do not serialize unrelated Houdini processes.
