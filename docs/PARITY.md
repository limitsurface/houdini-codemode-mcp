# CLI Parity and Deliberate Differences

Last verified: 2026-08-12 against `houdini-cli` `v0.3.2` and Houdini
22.0.368.

Code Mode does not define parity as reproducing every CLI flag with a `ctx`
method. Raw `hou` is the complete API surface; `ctx` exists for bounded reads,
compound invariants, artifact boundaries, and explicit helper-owned effects.

The current result is API-level parity for ordinary HOM work and strong
semantic parity for bounded inspection plus selected synchronization families.
It is not yet feature parity for broad HDA install/uninstall lifecycle operations,
full parameter-interface authoring, recipe authoring/tool/decoration apply, or
every file-producing command.

| CLI family | Code Mode surface | Status |
| --- | --- | --- |
| `ping`, `session`, `eval` | `doctor`, structured `run`, `ctx.session`, raw `hou` | Superseded by the versioned one-program contract. |
| `node`, `parm`, `nodetype` | raw `hou`; bounded `ctx.nodes`, `ctx.parms`, and `ctx.parm_references` | Semantic parity for bounded discovery, neighbours, network summaries, tuple-collapsed parm listing, caller-ordered projection, and capped generic dependency audits. `ctx.parm_references.references(...)` uses direct HOM references plus channel-expression/raw fallback and classifies internal, external, absolute-internal, and unresolved targets; it is live-proven on H22.0.368. Thin lifecycle/wiring/setters are intentionally not mirrored. |
| `attrib` | `ctx.geometry.summary`, `attributes`, `get` | Bounded count, topology, definition, and value-sampling parity. |
| `cop info`, `cop sample`, image file effects | `ctx.cop.info`, `sample`; `ctx.cop_files.export_image`, `import_image` | Bounded layer/signature/camera metadata and pixel sampling parity. Raw EXR export and File COP import are audited and byte-capped. Transactional export success, failure cleanup, and existing-target preservation are live-tested. |
| `lop stage-summary` | `ctx.lop.summary` | Bounded USD traversal, counts, type histogram, paths, composition, cook metadata, and active render context parity. |
| `opencl validate`, `opencl sync` | `ctx.opencl.validate`, `sync` | Behavioural parity across SOP, COP, and DOP for binding rows, generated controls, COP signatures, named connection restoration, value preservation, invalid-input disconnection, details, and mutation events. |
| `python` binding workflows | `ctx.python.inspect`, `validate`, `sync` | Python SOP and Python COP `#bind` interface parity, including dry-run/bindings-only/prune/value-preservation options where applicable. |
| `wrangle` spare sync | `ctx.wrangle.sync`, `clear` | Spare-parameter synchronization parity. Wrangle creation/configuration is ordinary raw HOM. |
| `xfer` | `ctx.artifacts.*`; operator CLI `houdini-codemode xfer copy` | Same-session artifact round trip is bounded and manifest-only. `xfer copy` is deliberately host orchestration, not a `ctx` operation: it requires explicit distinct loopback endpoints, preflights their shared artifact root, restores under an explicit parent/name, cleans the artifact, and never saves either HIP. It is live-proven from 18811 to 18814; a successful transfer leaves the destination node and can dirty that unsaved HIP. |
| `hda` | `ctx.hda.*`, `ctx.hda_create`, `ctx.hda_sections`, `ctx.hda_tools`, `ctx.hda_interface`, `ctx.hda_update`; raw `hou` | Guarded workflows include new-library creation from an explicit non-HDA source, package copy, promotion, bounded plain-text sections, structured SOP/COP Tools.shelf, declarative float/int/string/toggle/menu interfaces/defaults, and whole-definition update with bounded text-section preservation. They require explicit consent and report library/scene/install effects without HIP saves. Broad install/uninstall management and general interface parity remain out of scope. |
| `recipe` | `ctx.recipes.list`, `get`, `apply_node_preset`, `apply_parm_preset` | Bounded recipe metadata is discoverable; node and parameter preset application suppresses recipe pre/post scripts. Recipe authoring plus tool/decoration application remain out of scope. |
| `shelf`, structured `help` | raw `hou`, host-side prepared help, Code Mode skill | Not mirrored as broad APIs. Structured SOP/COP HDA tools are the intentional narrow exception. |

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

- broad HDA install/uninstall lifecycle and non-isolated interface workflows;
- folders, ramps, callbacks, and multiparms beyond the bounded declarative
  HDA interface schema;
- recipe authoring and tool/decoration recipe application;
- additional explicit durable-output workflows where raw HOM is not sufficient policy;
- a support matrix beyond the currently tested Houdini 22.0.368/Python 3.11
  runtime;
