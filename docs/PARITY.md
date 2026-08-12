# CLI Parity and Deliberate Differences

Last verified: 2026-08-12 against `houdini-cli` `v0.3.2` and Houdini
22.0.368.

Code Mode does not define parity as reproducing every CLI flag with a `ctx`
method. Raw `hou` is the complete API surface; `ctx` exists for bounded reads,
compound invariants, artifact boundaries, and explicit helper-owned effects.

The current result is API-level parity for ordinary HOM work and strong
semantic parity for the highest-value compound CLI families. It is not yet
feature parity for HDA lifecycle/package operations, shelf/recipe management,
or every file-producing command.

| CLI family | Code Mode surface | Status |
| --- | --- | --- |
| `ping`, `session`, `eval` | `doctor`, structured `run`, `ctx.session`, raw `hou` | Superseded by the versioned one-program contract. |
| `node`, `parm`, `nodetype` | raw `hou`; bounded `ctx.nodes` and `ctx.parms` | Semantic parity for bounded discovery, neighbours, network summaries, tuple-collapsed parm listing, and caller-ordered projection. Thin lifecycle/wiring/setters are intentionally not mirrored. |
| `attrib` | `ctx.geometry.summary`, `attributes`, `get` | Bounded count, topology, definition, and value-sampling parity. |
| `cop info`, `cop sample`, image file effects | `ctx.cop.info`, `sample`; `ctx.cop_files.export_image`, `import_image` | Bounded layer/signature/camera metadata and pixel sampling parity. Raw EXR export and File COP import are audited, byte-capped, transactional where writing, and live-tested. |
| `lop stage-summary` | `ctx.lop.summary` | Bounded USD traversal, counts, type histogram, paths, composition, cook metadata, and active render context parity. |
| `opencl validate`, `opencl sync` | `ctx.opencl.validate`, `sync` | Behavioural parity across SOP, COP, and DOP for binding rows, generated controls, COP signatures, named connection restoration, value preservation, invalid-input disconnection, details, and mutation events. |
| `python` binding workflows | `ctx.python.inspect`, `validate`, `sync` | Python SOP and Python COP `#bind` interface parity, including dry-run/bindings-only/prune/value-preservation options where applicable. |
| `wrangle` spare sync | `ctx.wrangle.sync`, `clear` | Spare-parameter synchronization parity. Wrangle creation/configuration is ordinary raw HOM. |
| `xfer` | `ctx.artifacts.export_node`, `inspect`, `import_node`, `list`, `remove` | Node/network artifact round trip is implemented with `.asData` kept on disk and only a bounded manifest returned. Narrow value/parm/input inverses are selected only when the captured root scope permits them; full artifacts correctly retain `setFromData`. |
| `hda` | `ctx.hda.inspect`, `definitions`, `libraries`, `references`, `validate`, `plan_promotion`, `plan_update`; raw `hou` | Bounded discovery, H22-compatible external-reference auditing, strict/optional reference validation, fresh-instance/frame-cook/interface validation, and no-effect validation/promotion/update plans are implemented. Package/update apply, section mutation, tools, and promotion/library mutation remain. |
| `shelf`, `recipe`, structured `help` | raw `hou`, host-side prepared help, Code Mode skill | Not mirrored. These are either thin HOM surfaces, host knowledge, or external-effect workflows that need a separate design. |

## What “one tool” changes

The old CLI remains useful for deterministic shell operations and debugging.
Code Mode wins when several dependent reads and mutations can be composed into
one main-thread Houdini program and only the final bounded projection crosses
the process boundary.

The intended model-facing surface remains exactly one MCP tool. Adding a `ctx`
service does not add another model tool; it extends the library available
inside the program.

## Remaining parity gate

Before claiming full compound parity, the project still needs:

- HDA package/update and parameter-template promotion mutation (both now have
  no-effect planning foundations);
- additional explicit durable-output workflows where raw HOM is not sufficient policy;
- a support matrix beyond the currently tested Houdini 22.0.368/Python 3.11
  runtime;
- a multiple-live-instance test (real competing local processes against one
  endpoint are already proven serialized).
