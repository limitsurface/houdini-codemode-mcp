---
name: houdini-codemode
description: Work with a live Houdini scene through the one-tool Houdini Code Mode executor using raw HOM plus bounded ctx extensions. Use for scene inspection or mutation, node-network construction, parameters, VEX, OpenCL, Copernicus, DOPs, LOPs/USD, HDAs, artifacts, image file effects, and any task where dependent Houdini work should be composed into one program instead of GUI clicks, legacy CLI eval, or many tiny calls.
---

# Houdini Code Mode

Use `houdini_code_run` as the model-facing Houdini action. If only the human
CLI adapter is available, submit the same complete program with
`houdini-codemode run`; do not fall back to legacy `houdini-cli eval` or manual
GUI interaction unless the user explicitly requires that surface.

The program receives fresh `hou`, `ctx`, `args`, and `result` globals. Put
request data in JSON `args`, never interpolate it into source, and call
`result.emit(value)` at most once.

## Start with discovery

Use raw `hou` for the complete Houdini API and `ctx` for bounded reads,
compound invariants, and audited effects.

When an extension is unfamiliar, discover it inside a read-only run:

```python
result.emit(ctx.capabilities(query="opencl"))
```

Then request its exact registered signature and effect category:

```python
result.emit(ctx.help("ctx.opencl.sync"))
```

Do not guess `ctx` methods. Current service families include `session`,
`nodes`, `parms`, `geometry`, `cop`, `cop_files`, `lop`, `hda`, `opencl`,
`python`, `wrangle`, and `artifacts`.

For unfamiliar or version-sensitive HOM, VEX, node, parameter, recipe, or
OpenCL APIs, search `references/help_prepared/` with `rg`. This generated corpus
must match the running Houdini version. If it is missing, run
`scripts/prepare_houdini_help.py --source <installed-houdini-help>`; the script
ships with the skill, while the generated corpus intentionally does not. Pause
the version-sensitive scene action if the corpus cannot be prepared; continue
without it only when the user explicitly accepts the risk.

## Compose one complete program

1. Inspect the existing scene and narrow the target scope.
2. Perform dependent reads, branching, edits, validation, and verification in
   one run.
3. Emit a compact plain-data result: summary, then bounded projection, then an
   artifact manifest when lossless state is genuinely required.
4. Clean temporary nodes and files in `finally`.

Avoid a chain of one-call-per-node or one-call-per-parm requests. Loops and
branching belong inside Houdini, where HOM objects remain local. Do not emit
HOM objects, full geometry buffers, broad `node.asData()`, or
`parmsAsData()` payloads. Use `ctx.artifacts` for narrowed lossless node/network
state and `ctx.cop_files` for audited image effects.

After creating or rewiring a network, set and verify the intended
display/render/output flag. Do not leave heavy intermediate nodes displayed.
Never save the HIP unless the user explicitly asks.

## Choose the scene implementation

- Prefer native Houdini nodes when they express the operation clearly.
- Prefer VEX for custom geometry processing that can run over points,
  primitives, or vertices. Use Detail Wrangles for genuinely sequential or
  topology-wide coordination, small global work, and prototypes.
- Prefer OpenCL for highly parallel, GPU-resident, or materially large work.
  Keep Copernicus bulk processing on the GPU; do not loop over image elements
  in Python when native COPs or OpenCL fit.
- Use Python for orchestration, metadata, irregular/string-heavy work, external
  libraries, and small workloads—not merely because it is easier to author.
- If a prototype becomes the delivered implementation, assess expected data
  scale and whether a practical parallel alternative exists.

COPs has been superseded by Copernicus. Do not use the legacy COP context unless
the user explicitly requires it.

## Read the relevant guidance

- Before any Copernicus or OpenCL COP task, read
  [references/copernicus.md](references/copernicus.md). For shipped native
  kernel patterns, also read
  [references/copernicus-kernel-reference-index.md](references/copernicus-kernel-reference-index.md).
- Before OpenCL SOP geometry work, read
  [references/opencl-sops.md](references/opencl-sops.md).
- Before Gas OpenCL or DOP GPU microsolver work, read
  [references/opencl-dops.md](references/opencl-dops.md).
- Before recipe discovery, application, creation, or management, read
  [references/recipes.md](references/recipes.md). There is no recipe extension;
  verify the exact raw HOM API in prepared help.

For VEX, establish the execution context and Wrangle run-over mode before
writing code. Treat `references/help_prepared/vex/` as the source of truth:

- verify functions in `vex/functions/<function>.txt`;
- check documented `#context`, `:usage:` signatures, overloads, return type,
  geometry handles, and attribute-class constraints;
- search descriptions/tags with
  `rg -i "<keyword>" references/help_prepared/vex/functions`;
- inspect `vex/contexts/` when globals or writable data are unclear.

Do not infer VEX APIs from C, C++, GLSL, or memory.

For the plain Solver SOP—and before unlocking Vellum, RBD Bullet, Pyro, MPM,
or similar simulation wrappers—inspect the HDA `DiveTarget` and
`EditableNodes` sections. Resolve the declared target relative to the solver
and create custom nodes there. Do not guess its path/capitalization or unlock a
protected asset when an editable dive target exists.

## Mutations, effects, and recovery

- Treat submitted code as trusted and unsandboxed.
- Use no-effect plans before HDA validation/promotion or other broad workflows
  when available.
- Inspect `meta.mutation.events` for helper-owned effects; direct-HOM tracking
  is best effort.
- Treat undo grouping as history organization, not rollback.
- Keep callers serial per Houdini instance. Arbitrary main-thread Python is not
  safely preemptible.
- If `meta.completion` is `unknown`, do not retry mutations and do not use the
  legacy CLI against that instance until completion is independently known or
  Houdini is restarted.
- Use a bounded read-only probe first when a program could wedge Houdini or
  perform broad external effects.
