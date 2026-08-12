# Houdini Code Mode Architecture

Status: viability proved; Phases 2 and 4 are substantially complete, Phase 3 is
complete except multi-instance evidence, and HDA/external-effect work remains.

Last revised: 2026-08-12.

Reference implementation surveyed:

- `D:/vibe_code/00_houdini_projects/houdini_CLI` at `v0.3.2`.

Research inputs:

- [MCP specification 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28)
- [Sessionless MCP](https://modelcontextprotocol.io/seps/2567-sessionless-mcp)
- [pi-rlm](https://github.com/shift-labs-ai/pi-rlm)
- [Prime Agent](https://github.com/PrimeIntellect-ai/prime-agent)
- [pi](https://github.com/earendil-works/pi)

The project adopts the one-programmable-tool boundary demonstrated by Code Mode
and RLM-style agent runtimes. It does not embed an LLM provider, recursive
agents, conversation state, or a persistent notebook runtime in Houdini.

## 1. Decision

Houdini Code Mode is a standalone product and repository. It complements the
existing CLI and leaves that repository stable while the new execution contract
is proved.

Its primary model-facing interface is exactly one MCP tool:

```text
houdini_code_run(source, args?, instance?, policy?)
```

A small local CLI exposes the same executor for development, diagnosis, shell
use, and integration testing:

```text
houdini-codemode check --file task.py
houdini-codemode run --file task.py
houdini-codemode run --input -
houdini-codemode doctor
```

The architectural shorthand is:

> Stateless at the request boundary; stateful in the Houdini scene.

Every call is a complete, self-contained program. The current HIP, nodes,
parameters, installed definitions, and other Houdini-owned data are the durable
application state. Arbitrary user Python globals and live HOM objects do not
persist implicitly between calls.

## 2. Why this is not `houdini-cli eval`

The existing CLI's eval command is a useful text-oriented escape hatch. Code
Mode needs a different contract:

- structured JSON arguments separate from source;
- one structured result independent of stdout and stderr;
- bounded normalization of HOM values;
- source, log, item, nesting, string, and response limits;
- execution identity and runtime/protocol versioning;
- per-Houdini serialization and busy reporting;
- explicit main-thread dispatch;
- honest timeout and cancellation semantics;
- undo grouping and mutation reporting;
- a stable extension namespace for compound Houdini workflows.

Adding these semantics to eval would create a new protocol while risking a
stable CLI surface. Code Mode therefore owns its own protocol and adapters.

## 3. Product principles

### 3.1 One tool does not mean one capability

The model sees one stable tool schema. Inside the submitted program it can use:

```python
hou       # The complete raw Houdini Object Model.
ctx       # Bounded projections and meaningful Houdini workflow extensions.
args      # JSON input, localized before execution.
result    # The single structured result collector.
```

Raw `hou` supplies API completeness. `ctx` grows only when it adds semantic
value, such as bounded traversal, compact projection, validation, mutation
events, or a tested multi-call invariant.

### 3.2 Fresh execution globals

Every run receives a new globals dictionary. The implementation may cache a
versioned runtime module in Houdini, but it does not cache the user's namespace.

This avoids stale live-object references, dependencies on calls no longer
present in model context, dishonest HOM snapshot semantics, and split-brain
state between a notebook process and the Houdini scene.

If durable scratch data is needed later, it must use explicit JSON/artifact
storage or an opaque application handle with a documented lifetime.

### 3.3 Provider-neutral infrastructure

Houdini Code Mode does not own model choice, recursion, subagents, prompts,
conversation compaction, or billing. Agent hosts already provide those. Multiple
hosts may call the same server, but runs targeting one Houdini instance are
serialized.

### 3.4 Trusted local execution

This is not a security sandbox. Submitted source runs with the permissions of
the Houdini process and can modify scenes, files, libraries, processes, and the
network. Initial deployment is local, supervised, and trusted.

The MCP server begins on stdio. Arbitrary Houdini execution must not be exposed
through unauthenticated HTTP.

## 4. Interfaces

### 4.1 MCP

The single tool accepts:

```json
{
  "source": "result.emit(hou.applicationVersionString())",
  "args": {},
  "instance": {"host": "localhost", "port": 18811},
  "policy": {
    "wait_timeout_seconds": 60,
    "undo_group": true,
    "label": "Houdini Code Mode"
  }
}
```

`instance` and `policy` are optional and bounded. They are request data, not
MCP session state. MCP 2026-07-28 requests are self-contained; older MCP clients
may be supported by the SDK compatibility layer without changing the executor.
The trusted-local release accepts loopback hosts only; arbitrary remote RPyC
targets are outside its trust boundary.

No separate MCP ping, capabilities, examples, node, parameter, OpenCL, or HDA
tools are added. MCP discovery describes the one tool. Health checks remain an
operator CLI concern.

Exact extension discovery stays inside that tool: `ctx.capabilities()` returns
a bounded static service catalogue and `ctx.help("ctx.service.method")` returns
the registered signature, summary, and effect category. One declarative host
registry generates the embedded data, and tests compare it with every public
runtime service/method. This keeps generic MCP clients independently usable
without inflating the tool schema or assuming they can load a Codex skill.

Clients that support skills should use the bundled Code Mode skill for
judgment-heavy behavior and progressive-disclosure references. The skill owns
one-program composition, version-matched Houdini help, native/VEX/OpenCL/Python
selection, Copernicus coordinate rules, solver/HDA cautions, cleanup, and
recovery—not the machine-readable method inventory.

### 4.2 Local CLI

`check` performs local parsing and compilation without contacting Houdini.

`run` reads source from an inline value, UTF-8 file, or stdin; parses JSON args;
invokes the same controller used by MCP; and writes one JSON document to stdout.
Diagnostics go to stderr.

`doctor` verifies dependencies, endpoint reachability, Houdini identity,
runtime installation, and main-thread dispatch with a read-only program.

### 4.3 Result envelope

A completed success resembles:

```json
{
  "ok": true,
  "data": {
    "value": {},
    "emitted": true,
    "logs": {
      "stdout": "",
      "stderr": "",
      "stdout_truncated": false,
      "stderr_truncated": false
    }
  },
  "meta": {
    "run_id": "...",
    "completion": "complete",
    "duration_ms": 12,
    "protocol_version": "0.1",
    "runtime_version": "0.1",
    "execution_model": "trusted-local-main-thread",
    "thread": "MainThread",
    "truncations": [],
    "mutation": {"events": [], "direct_hom_tracking": "best_effort"},
    "houdini": {"version": "22.0.368", "hip_file": "..."}
  }
}
```

Failures use a stable structured error:

```json
{
  "ok": false,
  "error": {
    "category": "validation|connection|busy|compile|execution|result|timeout|internal",
    "type": "...",
    "message": "..."
  },
  "meta": {"completion": "complete|unknown|not_started"}
}
```

Unexpected Python exceptions must be caught inside Houdini and converted before
crossing RPyC. User stdout and stderr never carry protocol framing.

## 5. Runtime architecture

```text
Agent host                         Operator / tests
    |                                   |
    | MCP stdio                         | CLI
    v                                   v
+------------------+             +------------------+
| one MCP adapter  |             | small CLI adapter|
+---------+--------+             +---------+--------+
          |                                |
          +---------------+----------------+
                          v
                +--------------------+
                | controller/protocol|
                +---------+----------+
                          |
                          | one request JSON
                          v
                +---------------------+
                | RPyC + endpoint gate|
                +---------+-----------+
                          |
                          v
                +---------------------+
                | Houdini bootstrap   |
                | process run lock    |
                | main-thread dispatch|
                +---------+-----------+
                          |
              +-----------+------------+
              | fresh globals           |
              | hou, ctx, args, result  |
              | bounded logs/normalizer |
              +-----------+-------------+
                          |
                          | one response JSON
                          v
                bounded structured envelope
```

### 5.1 Controller

The controller is independent of CLI and MCP. It validates and size-checks
source, verifies JSON input, compiles locally, clamps limits, creates a run ID,
opens one gated RPyC connection, installs or version-checks the runtime, sends
one request JSON value, invokes one remote function, obtains only one response
JSON string, enforces a final response ceiling, and parses the envelope.

The controller does not import private `houdini_cli.*` modules.

### 5.2 Runtime delivery

The controller sends a versioned runtime source artifact and publishes its
executor in `hou.session`. Subsequent connections compare both source hash and
runtime version and reinstall only on mismatch. Restarting Houdini simply makes
the next request install again.

The runtime source remains a separately tested embedded-Python artifact; the
external controller wheel is not installed in Houdini. Current live evidence is
Houdini 22.0.368/Python 3.11. Additional supported versions require their own
runtime and live-test matrix entries.

### 5.3 Admission and main-thread execution

The shelf hrpyc server is threaded. A live probe on Houdini 22.0.368 confirmed:

```text
ordinary hrpyc call: worker thread
hdefereval dispatch: MainThread
```

The Houdini runtime therefore acquires a process-wide non-blocking run lock on
the worker, then dispatches the complete program through
`hdefereval.executeInMainThreadWithResult`. If already on the main thread, it
executes directly.

Only one Code Mode program may target a Houdini process at a time. A competing
request returns `busy`; it does not queue invisibly inside Houdini.

### 5.4 Timeout and cancellation truthfulness

An RPyC wait timeout does not preempt Python already executing in Houdini. A
timeout response therefore uses `completion: unknown`.

The Houdini-side run lock remains held until actual completion, so later Code
Mode calls cannot overlap. The external transport also runs the admitted RPyC
request on a background waiter. If the caller stops waiting, that waiter keeps
the connection and the shared Windows endpoint mutex until remote completion or
connection failure. This prevents a normal Code Mode or legacy CLI process from
being admitted locally merely because the first caller timed out.

The retained gate is coordination, not cancellation or proof of completion. It
cannot coordinate clients on another machine, and it disappears if the Code
Mode process itself exits. After `completion: unknown`, do not retry mutations
until completion is independently known or Houdini is restarted. Cooperative
cancellation can be implemented in bounded `ctx` loops; arbitrary synchronous
Python/HOM is not safely preemptible.

If code wedges the Houdini main thread permanently, Houdini—not Codex—must be
restarted. A Codex restart does not repair a wedged Houdini interpreter.

## 6. Context control

### 6.1 Filter in Houdini

Traversal, filtering, aggregation, and projection happen before localization.
The local process should receive only response JSON, never an RPyC graph of live
HOM objects.

```python
rows = ctx.nodes.find("/obj", name="sim", max_depth=3, max_nodes=50)
result.emit(rows)
```

### 6.2 Result normalization

`result.emit(value)` recursively supports JSON scalars, bounded strings,
bounded lists/tuples, bounded string-keyed dictionaries, and registered compact
HOM summaries. Initial summaries cover nodes, parameters, and node types.

Unknown objects, cycles, non-finite floats, and non-string dictionary keys are
rejected. The runtime never falls back to unrestricted `repr()`.

Limits include source bytes, per-log bytes, nesting depth, items per container,
total visited items, string bytes, result JSON bytes, and response JSON bytes.
Truncation is explicit in `meta.truncations`, including a value path and reason.

### 6.3 One result, separate logs

`result.emit()` may be called at most once. No emission is valid and returns
`null` with `emitted: false`. A second call is an execution error.

stdout and stderr are capped debugging channels. They are never parsed as the
primary result.

### 6.4 Artifacts

Large or lossless node/network state is written through `ctx.artifacts`. The
configured/default root is contained, writes are atomic and byte-capped, and
the response contains only a manifest with schema/runtime/Houdini versions,
hash, size, and item counts. Raw `.asData` remains in the artifact file. Reads,
writes, node creation, cleanup, and artifact removal are reported as exact
helper-owned effects.

## 7. Helper boundary

`ctx` is not a mirror of HOM or the old CLI.

Implemented extensions:

- bounded node find, neighbours, summaries, and error aggregation;
- bounded parameter discovery and projection;
- attribute/geometry summaries and sampling;
- Copernicus image/layer metadata and sampling;
- bounded LOP/USD-stage summaries;
- OpenCL binding validation and synchronization;
- Python COP/SOP `#bind` validation and synchronization;
- wrangle spare-parameter synchronization;
- bounded, audited artifact export.
- bounded HDA instance/definition/library discovery plus dry-run and
  fresh-instance/frame-cook/external-reference validation;
- H22-compatible external-reference auditing and no-effect parameter promotion
  and package/update planning;
- transactional, byte-capped Copernicus image export/import;
- bounded in-runtime extension discovery from a static registry.

Later extensions:

- HDA parameter-promotion and package/update mutation;
- additional policy-rich durable-output effects.

Do not add helpers merely for basic node lifecycle/wiring, ordinary parameter
operations, frame or selection reads, simple HDA calls, or broad HOM discovery.
Generated code uses raw `hou` for those.

OpenCL validation and synchronization, Python binding workflows, wrangle spare
synchronization, geometry/Copernicus/LOP summaries, and bounded HDA validation
are implemented. HDA packaging remains later because it mixes external file and
library effects with definition mutation.

## 8. Mutations, undo, and saving

`ctx` helpers record exact events they own. Direct HOM mutations remain
best-effort and are labelled as such. The runtime may report inexpensive signals
such as HIP dirty state before and after, but it does not scan an entire large
scene to imply complete accounting.

Mutating runs may use `hou.undos.group(label)`. This groups undo history; it is
not rollback-on-exception and must not be described as a transaction.

File writes, library operations, cooking, external processes, and HIP saves may
not be undoable. The HIP is never saved implicitly.

## 9. Relationship with `houdini-cli`

The repositories remain independent initially:

- no imports from private `houdini_cli.*` modules;
- no editable path dependency between repositories;
- no command-for-command port;
- no immediate refactor of the stable CLI.

The minimal Windows endpoint gate and RPyC lifecycle are reimplemented with
clear provenance. The gate intentionally uses the existing mutex namespace so
the two local clients serialize their connections in normal operation.

Domain logic is ported selectively with its behavioural tests. If both products
later need to co-own the same implementation, extract a small, published,
versioned shared package.

## 10. Repository layout

```text
houdini_codemode/
    .gitignore
    pyproject.toml
    README.md
    docs/
        ARCHITECTURE.md
        CHECKLIST.md
        PARITY.md
        SUPPORT.md
    shelf_script/
        start_houdini_codemode_server.py
    skills/houdini-codemode/
        SKILL.md
        agents/openai.yaml
        scripts/prepare_houdini_help.py
        references/
            copernicus.md
            copernicus-kernel-reference-index.md
            opencl-sops.md
            opencl-dops.md
            recipes.md
    src/houdini_codemode/
        __init__.py
        cli.py
        controller.py
        protocol.py
        runtime_source.py
        runtime_artifact_source.py
        runtime_cop_source.py
        runtime_cop_file_source.py
        runtime_geometry_source.py
        runtime_hda_source.py
        runtime_hda_reference_source.py
        runtime_hda_promotion_source.py
        runtime_hda_update_source.py
        runtime_help_source.py
        runtime_lop_source.py
        runtime_opencl_source.py
        runtime_python_source.py
        runtime_wrangle_source.py
        mcp_server.py
        transport/
            __init__.py
            gate.py
            rpyc.py
    tests/
        test_cli.py
        test_controller.py
        test_protocol.py
        test_runtime.py
        test_mcp.py
        test_live_integration.py
    .tmp/                  # ignored research clones; never packaged
```

## 11. Delivery phases

### Phase 0: independent baseline

- initialize this standalone repository;
- move architecture and checklist into `docs/`;
- ignore research clones;
- record the CLI reference baseline and keep it unchanged.

### Phase 1: end-to-end viability

- define request, policy, response, and version contracts;
- implement local syntax checking and input limits;
- implement the RPyC connection lifecycle and shared endpoint gate;
- implement the bounded Houdini runtime and fresh globals;
- dispatch on Houdini's main thread under a process run lock;
- expose CLI `check`, `run`, and `doctor`;
- expose one MCP stdio tool over the same controller;
- unit-test both adapters and the runtime contract;
- prove bounded read and isolated mutate/verify/cleanup flows live.

Success criterion: one self-contained program composes several HOM calls inside
Houdini and returns one compact, netref-free result through both adapters. Logs,
errors, and oversized data remain bounded.

### Phase 2: inspection foundation

- harden node/parm/type serializers;
- port bounded node find, neighbours, and network summaries;
- port bounded parm projection;
- add golden response fixtures and large-scene tests.

### Phase 3: operational hardening

- ship a Code Mode-owned Houdini shelf/server bootstrap and installation path;
- improve unknown-completion recovery;
- add exact helper mutation events;
- validate undo behaviour across supported Houdini contexts;
- add explicit artifact policy;
- test multiple endpoints and competing callers;
- version/hash-cache the Houdini runtime.

### Phase 4: compound extensions

- OpenCL validate and sync;
- Python `#bind` validate/sync;
- wrangle spare synchronization;
- geometry, Copernicus, and LOP summaries.

### Phase 5: HDA and external effects

- bounded read-only HDA instance/definition/library inspection;
- bounded HDA validation and no-effect validation plans;
- generic and HDA-scoped external-reference auditing plus promotion planning;
- no-effect package/update planning;
- transactional Copernicus image file effects;
- narrowly scoped staged HDA package copy to an unloaded external library;
- isolated parameter-template promotion with explicit owned-library consent and
  a pre-synchronization content checkpoint;
- broad HDA create/update, section/tool, and multi-instance workflows remain;
- mutation dry-run plans and explicit library event reporting.

### Phase 6: sharing decision

After multiple behaviours are genuinely co-owned, decide whether to publish a
small shared core and adapt the legacy CLI. Preserve both products' contracts.

## 12. Testing strategy

Unit and fake-HOM tests cover validation, compilation, normalization, Unicode
byte limits, cycles, duplicate emissions, structured exceptions, busy admission,
gate lifetime, connection failures, timeouts, and adapter parity.

MCP tests call the server in memory and assert that exactly one tool is exposed
and that its structured response equals a direct controller call.

Live tests report Houdini/thread metadata, prove truncation and structured
errors, and create/connect/inspect/delete isolated unique networks. They cover
bounded node/parm inspection and `.asData` timing, artifact round trips,
Python and wrangle binding synchronization, OpenCL sync across SOP/COP/DOP,
geometry/Copernicus/LOP/HDA summaries, HDA reference auditing, Copernicus image
export/import, undo grouping without rollback, and both MCP adapters. They set
and verify display/render flags where applicable, clean up in `finally`, and
never save the HIP.

Live mutation tests may mark the open HIP dirty even when all temporary nodes are
removed. Test output and handoff notes must state that clearly.

## 13. Viability gates and open questions

The project is viable only if Phase 1 demonstrates reliable whole-program
main-thread execution, one bounded netref-free response, serialization that
survives disconnect/timeout, adapter parity, and safe isolated cleanup.

Open questions after the implemented foundations:

1. Which Houdini/Python versions join 22.0.368/Python 3.11 in the support matrix?
2. What output ceilings work best during production dogfooding?
3. Which inexpensive direct-HOM mutation signals add value without broad scans?
4. Which external-effect operations need confirmation above the trusted-local executor?
5. When does a shared package become cheaper than behavioural porting?
6. Which planned HDA mutation should be admitted first: package/update or
   parameter promotion?
7. How should completion be surfaced after an initial caller has already
   received `completion: unknown`?

## 14. Current milestone and next target

On 2026-08-12 the project collected 94 automated tests: 93 passed and one
optional distinct-port test skipped. The passing set includes live tests
against Houdini 22.0.368 on the default port. The same transport-neutral
controller serves the CLI, an in-memory MCP 2026-07-28 client, and a spawned MCP
stdio process while exposing exactly one model-facing tool.

The milestone now includes:

- full-program `MainThread` dispatch, fresh globals, JSON args, bounded logs and
  results, structured failures, and no implicit HIP save;
- cached runtime installation, dual local/Houdini admission, and background
  endpoint-gate retention after a caller timeout;
- bounded node, parm, geometry, Copernicus, USD-stage, and HDA inspection;
- dry-run and fresh-instance/frame-cook HDA validation with frame/temp cleanup;
- HDA external-reference audit/validation and promotion planning;
- manifest-only `.asData` node/network artifacts with a live round trip and
  focused narrow-inverse payload coverage;
- transactional Copernicus raw image export/import with live file/temp cleanup;
- a packaged Code Mode skill, version-matched help preparation script, migrated
  Copernicus/VEX/OpenCL guidance, and bounded runtime capability discovery;
- OpenCL validate/sync across SOP, COP, and DOP, Python SOP/COP binding sync,
  and VEX wrangle spare sync;
- exact helper-owned mutation/effect events and live proof that undo grouping is
  history organization rather than rollback.

The open HIP was already dirty and remains dirty. The full live cleanup audit
found no `codemode_*` nodes under `/obj`, `/img`, or `/stage` and no Code Mode
artifacts. The on-disk HIP was never saved.

The next coherent slice is a deliberate choice of the first admitted HDA
definition mutation now that promotion and package/update both have no-effect
plans with explicit library risks.
Support-matrix and multiple-live-instance testing can proceed independently.
Two real local controller processes have been proven to serialize against the
same live endpoint; distinct-port behavior still needs a second Houdini instance.
