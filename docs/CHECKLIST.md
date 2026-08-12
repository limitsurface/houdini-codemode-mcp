# Houdini Code Mode Checklist

Last updated: 2026-08-12.

Check an item only after its relevant tests or live evidence pass.

## Phase 0 — standalone baseline

- [x] Confirm `houdini_CLI` is clean on its recorded `v0.3.2` baseline.
- [x] Choose a standalone repository from inception.
- [x] Initialize Git with `main` as the initial branch.
- [x] Move the architecture plan to `docs/ARCHITECTURE.md` and update it.
- [x] Ignore `.tmp/` research clones and standard Python artifacts.
- [x] Add package metadata, README, and dependency lock.
- [x] Establish the initial unit-test baseline.
- [x] Treat Houdini's `.asData` family as an internal projection/artifact primitive,
      not a model-facing mirror API.
- [x] Adopt the output policy: summary, then bounded projection, then artifact;
      never return full serialized state by default.

## Phase 1 — viability slice

### Protocol and controller

- [x] Define versioned request, instance, policy, response, and error contracts.
- [x] Enforce source size and local syntax checks.
- [x] Validate JSON args and clamp policy limits to hard ceilings.
- [x] Generate and propagate one run ID.
- [x] Return `completion: unknown` rather than claiming timeout cancellation.
- [x] Enforce a final local response byte ceiling.

### Transport

- [x] Reimplement the scoped RPyC lifecycle without importing `houdini_cli`.
- [x] Preserve the CLI's Windows endpoint mutex namespace for interoperability.
- [x] Hold the local gate for the complete connection lifetime.
- [x] Convert connection, queue, and RPyC timeout failures into protocol errors.
- [x] Send one request JSON string and obtain one response JSON string.

### Houdini runtime

- [x] Install a versioned runtime source artifact over RPyC.
- [x] Acquire a non-blocking process-wide Houdini run lock.
- [x] Dispatch the whole program through Houdini's main thread.
- [x] Create fresh `hou`, `ctx`, `args`, and `result` globals for every run.
- [x] Capture stdout and stderr with Unicode-aware byte caps.
- [x] Permit at most one `result.emit()` call.
- [x] Normalize JSON values plus compact node/parm/type summaries.
- [x] Reject cycles, unknown objects, non-finite floats, and invalid dict keys.
- [x] Enforce nesting, container, total-item, string, result, and response limits.
- [x] Return structured compile, execution, result, busy, and internal errors.
- [x] Report runtime/protocol/Houdini versions and execution thread.
- [x] Report direct-HOM mutation visibility honestly and never save implicitly.

### Adapters

- [x] Implement `houdini-codemode check`.
- [x] Implement `houdini-codemode run` for inline, file, and stdin source.
- [x] Implement a read-only `houdini-codemode doctor`.
- [x] Implement one MCP stdio tool: `houdini_code_run`.
- [x] Prove the MCP adapter delegates to the same controller as the CLI.
- [x] Assert that MCP exposes no second model-facing tool.

### Automated evidence

- [x] Unit-test request validation and syntax checking.
- [x] Unit-test bounded Unicode logs and result normalization.
- [x] Unit-test duplicate emission and structured errors.
- [x] Unit-test busy admission and transport/gate lifetimes.
- [x] Unit-test controller behaviour with a fake RPyC connection.
- [x] Test the MCP server in memory through the official v2 client.
- [x] Run all non-live tests successfully.

### Live evidence on default port

- [x] Confirm hrpyc worker-thread execution can dispatch to `MainThread`.
- [x] Run a read-only program using JSON args and return a compact node summary.
- [x] Prove oversized logs/collections are bounded with explicit truncation.
- [x] Prove a raised exception returns a structured error, not an RPyC failure.
- [x] Create, connect, inspect, and delete an isolated unique node network.
- [x] Set and verify display/render flags on the intended output node.
- [x] Confirm all temporary nodes are removed in `finally`.
- [x] Confirm the live test never saves the HIP.

### Phase 1 stopping condition

- [x] CLI and MCP both exercise one transport-neutral executor.
- [x] Live results contain no HOM/RPyC netrefs.
- [x] Main-thread, limits, errors, and cleanup are evidenced by tests.
- [x] Record remaining timeout/cancellation risks in the architecture and handoff.
- [x] Mark the viability milestone in `docs/ARCHITECTURE.md`.

## Phase 2 — bounded inspection foundation

- [x] Port the CLI's bounded `valueAsData()` parm projections, ramp summaries,
      and explicit truncation metadata into Code Mode-owned runtime helpers.
- [x] Harden node, parm, and node-type serializers against the current
      Houdini 22.0.368/Python 3.11 support target.
- [ ] Add serializer/live-runtime coverage for every additional supported
      Houdini/Python version before claiming a broader support matrix.
- [x] Preserve caller ordering and distinguish missing, inaccessible, errored, and
      truncated values in projected results.
- [x] Add regression fixtures for component-parm tuple behaviour and
      `parmsAsData()` returning `None` without helper reliance on that broad call.
- [x] Add a focused `setValueFromData()` payload-shape regression before using it
      as a narrow artifact restore primitive.
- [x] Filter and normalize `.asData` values inside Houdini before transport; do
      not automatically traverse or emit a complete raw payload.
- [x] Expose semantic bounded inspection helpers rather than one-to-one
      `asData`, `parmsAsData`, or `setFromData` wrappers on `ctx`.
- [x] Port bounded node find and directional neighbours.
- [x] Port network summaries and caller-ordered parm projection.
- [x] Add compact table/truncation helpers.
- [x] Add bounded in-runtime `ctx.capabilities()` / `ctx.help(...)` discovery
      from one static registry, with completeness tests against public services.
- [x] Add large-scene performance and response-size fixtures comparing focused
      direct reads, bounded projections, and broad `.asData` extraction.
- [x] Add and validate a Code Mode skill using version-matched prepared Houdini help.
- [x] Add and live-test a bounded generic parameter-reference audit using direct
      HOM references plus `ch*()` expression/raw fallback, with internal,
      external, absolute-internal, and unresolved classification.

## Phase 3 — operational hardening

- [x] Ship a Code Mode-owned Houdini shelf/server bootstrap and install guide.
- [x] Version/hash-cache the runtime in Houdini.
- [x] Retain the endpoint gate on a background waiter after local wait timeout.
- [x] Add exact helper-owned mutation events.
- [x] Validate undo grouping live and prove it is not rollback on exception.
- [x] Define artifact roots, byte limits, lifecycle, and manifest metadata,
      including schema/runtime/Houdini versions, hash, size, and item counts.
- [x] Require large or lossless `.asData` payloads to remain in artifacts; return
      only a bounded manifest/reference through the execution response.
- [x] Unit-test competing callers, local/Houdini admission, and retained gate lifetime.
- [x] Prove two real local Code Mode processes serialize against one live endpoint.
- [x] Test two live Houdini 22.0.368 instances on distinct configured ports
      (18811 and 18814) and prove endpoint isolation.
- [x] Document recovery from `completion: unknown` and a wedged main thread.

## Phase 4 — compound extensions

- [x] Port OpenCL validation with focused behavioural tests.
- [x] Port and live-test OpenCL synchronization across SOP, COP, and DOP contexts.
- [x] Replace broad OpenCL `parmsAsData()` reads with focused Houdini-side reads
      or compact projections where they are sufficient.
- [x] Port and live-test Python COP/SOP `#bind` validation and synchronization.
- [x] Port and live-test wrangle spare-parameter synchronization.
- [x] Add and live-test geometry, Copernicus, and LOP bounded summaries.
- [x] Add and live-test transactional Copernicus raw image export/import with
      byte caps, explicit file effects, and temporary-helper cleanup.

## Phase 5 — transfer, HDA, and external effects

- [x] Add artifact-oriented node/network snapshot and transfer workflows using
      `.asData` only after the target scope has been narrowed explicitly.
- [x] Restore with the smallest applicable inverse method (`setValueFromData`,
      `setParmsFromData`, or `setInputsFromData`) before considering broad
      `setFromData()` reconciliation; retain broad reconciliation when the
      artifact also captures flags, position, inputs, or other root state.
- [x] Prove a snapshot/restore round trip on an isolated network in Houdini
      22.0.368 and report every file/scene side effect explicitly.
- [x] Add and live-prove host-orchestrated `houdini-codemode xfer copy` from
      `localhost:18811` to `localhost:18814`: explicit distinct loopback
      ports, unique bounded artifact, restore under an explicit parent/name,
      cleanup from both endpoint views, and no HIP save.
- [ ] Repeat artifact round trips across every additional supported Houdini version.
- [x] Add and live-test bounded read-only HDA definition/library/instance inspection.
- [x] Add and live-test bounded HDA validation with a no-effect dry-run plan.
- [x] Add and live-test bounded HDA external-reference auditing and integrate it
      with optional/strict validation.
- [x] Add and live-test a no-effect package/update planner that reports
      filesystem/library preconditions, external references, ordered future
      effects, and rollback limits without changing the definition or library.
- [x] Add and live-test `ctx.hda.package_copy`: stage one definition into an
      explicit external destination library and atomically publish it without
      installing that destination or saving the HIP.
- [x] Add bounded plain-text `ctx.hda_sections` read/plan/set/delete for one
      explicitly owned sole-instance HDA library, with consent, backup, and
      no-HIP-save reporting.
- [x] Add structured SOP/COP `ctx.hda_tools` inspection and one Tools.shelf
      set/remove workflow; opaque shelf XML is not exposed as a general API.
- [x] Add bounded declarative `ctx.hda_interface` authoring plus explicit
      supported tuple defaults-from-current, each restricted to an owned
      sole-instance library with backup/no-HIP-save reporting.
- [x] Add and live-test `ctx.hda_update.update_owned` for one sole unlocked
      instance, with verified backup, bounded text section/tool preservation,
      optional whole-interface copy, match, and validation.
- [x] Add bounded `ctx.recipes` metadata discovery and script-suppressed node
      and parameter preset application.
- [x] Add and live-test narrow `ctx.hda_create.create_owned` for a new external
      library from an explicit non-HDA source, reporting unavoidable install
      and node-type conversion effects.
- [ ] Add broad HDA install/uninstall lifecycle. Raw HOM remains the surface for
      general loaded-library management.
- [x] Add and test a no-effect parameter-template promotion planner.
- [x] Add and live-test durable isolated `ctx.hda.apply_promotion`, requiring
      `allow_library_write=True`, an exact explicitly owned external library,
      and a sole verified instance before it writes the definition/library.
- [ ] Add broad parameter-template/interface mutation: folders, ramps,
      callbacks, and multiparms remain outside the narrow declarative schema.
- [ ] Add recipe authoring and tool/decoration recipe application. Existing
      preset application suppresses recipe scripts by design.
- [x] Report artifact file and restored-scene side effects explicitly.
- [x] Report package-copy and promotion library/scene mutation events, before/
      after file manifests, install state, and `hip_saved=False` explicitly.

## Phase 6 — sharing decision

- [ ] Review real dual-owned behaviours after dogfooding.
- [ ] If justified, extract a published and versioned shared core.
- [ ] Never introduce private cross-repository imports or editable path coupling.
- [ ] Preserve the existing CLI contract and test suite during any extraction.
