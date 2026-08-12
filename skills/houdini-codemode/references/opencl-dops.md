---
name: houdini-opencl-dops
description: Guidance for Gas OpenCL and GPU microsolvers in DOP networks, including field bindings, parameter synchronization, worksets, and Pyro references.
---

# OpenCL in DOP Workflows

Use this guidance for Gas OpenCL and other GPU microsolvers in DOP networks.
For OpenCL SOP geometry kernels, read `opencl_sops.md`. For Copernicus, read
`copernicus.md`.

## Core Guidance

1. Use the established patterns in this guide directly for routine
   microsolvers. Inspect a relevant shipped node when the operation is
   unfamiliar, solver-specific, synchronization-heavy, or poorly documented.
2. Keep RPC inspection serial. Large DOP networks and unlocked solver HDAs are
   unsafe targets for concurrent HOM/RPyC traversal.
3. After editing a Gas OpenCL kernel, run `ctx.opencl.sync`, `ctx.opencl.validate`,
   and inspect `node.errors()`.
4. Use `@TimeInc` for integration, damping, and decay so behavior remains
   stable across substeps.
5. Keep advection, projection, and other specialized operations in native GPU
   microsolvers when available.

## Gas OpenCL Interface

Gas OpenCL uses a third interface model distinct from COP and SOP OpenCL:

- the binding count is stored in `paramcount`;
- rows use `parameter#Name`, `parameter#Type`, and type-specific fields;
- field bindings refer to named DOP simulation data;
- geometry attributes refer to named Geometry data;
- data-option bindings refer to option values on simulation data.

`ctx.opencl.sync(node, clear=True)` detects the DOP context and rebuilds these
parameter rows from `#bind` directives.

## Minimal Field Kernel

```c
#bind scalarfield &density float
#bind parm gain float val=0.5

@KERNEL
{
    @density *= @gain;
}
```

Synchronize and validate with this one complete Code Mode program:

Submit this as one complete `houdini_code_run` program; provide
`dop_root_path` and `gas_opencl_path` in `args`.

```python
dop_root = hou.node(args["dop_root_path"])
gas_opencl = hou.node(args["gas_opencl_path"])
if dop_root is None or gas_opencl is None:
    raise hou.OperationFailed("dop_root_path or gas_opencl_path does not resolve")

before = ctx.opencl.validate(gas_opencl, details=True)
synced = ctx.opencl.sync(gas_opencl, clear=True, details=True)
after = ctx.opencl.validate(gas_opencl, details=True)
result.emit({
    "opencl_nodes": ctx.nodes.find(
        dop_root, type_name="opencl", max_depth=12, max_nodes=50
    ),
    "kernel_parms": ctx.parms.project(
        gas_opencl, ["kernelcode", "kernelfile", "kernelname"], value_mode="full"
    ),
    "connections": ctx.nodes.neighbors(
        gas_opencl, direction="both", depth=1, max_nodes=25
    ),
    "errors": list(gas_opencl.errors()),
    "before": before,
    "sync": synced,
    "after": after,
})
```

Sync creates a writable Scalar Field row for `density`, a Float row for
`gain`, and a generated `gain` control linked to the row's value.

## Supported Binding Families

The Houdini binding extractor and Code Mode runtime support:

| Binding type | Gas OpenCL row |
| :--- | :--- |
| `int`, `float`, `float3`, `float4` | Constant parameter |
| `ramp` | Sampled ramp |
| `scalarfield` | Scalar Field data |
| `vectorfield` | Vector Field data |
| `matrixfield` | Matrix Field data |
| point/primitive/detail bindings | Geometry attribute |
| `volume` | SOP volume primitive in Geometry data |
| `vdb` | VDB primitive in Geometry data |
| `option` | Option value from DOP simulation data |

Gas OpenCL does not expose a Float Vec2 parameter type. Do not use a `float2`
constant binding unless the target node version explicitly supports it.

## Field Bindings

Fields can be readable, writable, or both:

```c
#bind scalarfield density float
#bind scalarfield &temperature float
#bind vectorfield &vel float3
```

Writable fields are marked stale on the CPU and remain on the GPU until
another solver requests them. Avoid `Flush Attributes` unless an immediate
CPU readback is required.

Enable Force Align when a kernel assumes that bound fields share resolution,
transform, and voxel indexing. Without alignment, the kernel must account for
different grids explicitly.

## Geometry, Volumes, and VDBs

Gas OpenCL can bind attributes from named Geometry DOP data:

```c
#bind point geoP float3 geometry=Geometry name=P
```

It can also bind SOP volumes and VDB primitives stored in Geometry data. The
row may request resolution, voxel size, and transforms between voxel and SOP
space.

Use optional bindings and defaults when simulation data may be absent.
Required missing data prevents the microsolver from running.

In Houdini 22 and newer, readable geometry attribute rows also support the
same mutually exclusive BVH modes as OpenCL SOPs. See the bundled
[SideFX OpenCL attribute binding methods](help_prepared/vex/ocl.txt#attribute-binding-methods)
for the authoritative query signatures and binding constraints.

```c
#bind point collisionP name=P float3 geometry=Geometry bvh
#bind point particlesP name=P float3 geometry=Geometry pointbvh
#bind point activeP name=P float3 geometry=Geometry pointbvh pointbvhmask=active
```

Use `bvh` for triangle-surface proximity and `pointbvh` for point-cloud
queries. Surface bindings require a point or vertex `float3`; point BVHs
require a point `float3`. A point mask names an integer point attribute and is
valid only with `pointbvh`. Mask values written by an earlier GPU kernel are
flushed before BVH construction, including inside a compile block. Surface
BVHs ignore primitives that are not already triangles.

## Data Options

The Gas OpenCL parameter schema supports option values from named simulation
data, including integer and float tuples. The `#bind option` type is recognized
by Houdini's extractor.

The exact directive modifiers for selecting a non-default DOP data name are
not documented clearly in the prepared help. Inspect a native node or the
generated binding dictionary before relying on guessed syntax.

## Time and Substeps

Gas Substep may invoke a microsolver with a timestep smaller than the frame
timestep. Enable Include Timestep and use `@TimeInc`.

Use Gas Substep or solver-specific iteration parameters when a Gas OpenCL
microsolver must run repeatedly.

Percentage decay:

```c
float decay = pow(1.0f - clamp(@rate, 0.0f, 1.0f), @TimeInc);
@density *= decay;
```

Fixed subtraction per second:

```c
@density -= @rate * @TimeInc;
```

Half-life:

```c
@density *= pow(0.5f, @TimeInc / max(@halflife, 1e-6f));
```

## Compile-Time Features

Native Gas OpenCL nodes use kernel options to remove disabled features:

```c
#ifdef USECONTROL
    control = fit(@control, @controlmin, @controlmax, 0.0f, 1.0f);
#endif
```

Compile definitions are useful for optional controls, goal values, bounds,
and operation modes. Avoid option strings that vary every timestep because
they can force repeated kernel compilation.

## Worksets

Gas OpenCL supports worksets stored as integer-array detail attributes on
named Geometry data:

- Worksets Begin contains offsets.
- Worksets Length contains dispatch lengths.
- Each nonzero workset is invoked separately by default.

Single-workgroup modes can batch small worksets and define
`SINGLE_WORKGROUP`, `SINGLE_WORKGROUP_SPANS`, or
`SINGLE_WORKGROUP_ALWAYS`. The kernel must synchronize correctly, usually
with `barrier(CLK_MEM_GLOBAL_FENCE)`.

Validate all workset offsets and lengths before dereferencing bound arrays.
Never let only part of a workgroup return before a barrier.

## Minimal Pyro Reference

The Pyro Solver SOP contains a DOP network. Minimal mode is a reduced graph,
not one monolithic OpenCL kernel.

| Node | Pattern |
| :--- | :--- |
| `dopnet1/minimal_source` | GPU VDB source merge |
| `pyro_solver/solver/substep_minimal` | Reduced solver composition |
| `solver/advect_fields_cl` | GPU scalar-field advection |
| `solver/advect_vel_cl` | GPU velocity advection |
| `solver/project_minimal` | Multigrid non-divergent projection |
| `pyro_solver/gasopencl1` | Small field clamp kernel |
| `gasdissipate_density/gasopencl_scalar` | Decay, ramps, compile switches |
| `solver/gasdissipate_temperature/gasopencl_scalar` | Temperature decay |

The minimal graph combines sourcing, advection, forces, dissipation,
divergence handling, and pressure projection inside a substep solver.

## Inspection Workflow

Use the following one complete Code Mode program for serial discovery,
parameter projection, interface synchronization, validation, connection
inspection, and error collection. If Use Code Snippet is disabled, inspect the
returned `kernelfile` and `kernelname`.

Submit this as one complete `houdini_code_run` program; provide
`dop_root_path` and `gas_opencl_path` in `args`.

```python
dop_root = hou.node(args["dop_root_path"])
gas_opencl = hou.node(args["gas_opencl_path"])
if dop_root is None or gas_opencl is None:
    raise hou.OperationFailed("dop_root_path or gas_opencl_path does not resolve")

before = ctx.opencl.validate(gas_opencl, details=True)
synced = ctx.opencl.sync(gas_opencl, clear=True, details=True)
after = ctx.opencl.validate(gas_opencl, details=True)
result.emit({
    "opencl_nodes": ctx.nodes.find(
        dop_root, type_name="opencl", max_depth=12, max_nodes=50
    ),
    "kernel_parms": ctx.parms.project(
        gas_opencl, ["kernelcode", "kernelfile", "kernelname"], value_mode="full"
    ),
    "connections": ctx.nodes.neighbors(
        gas_opencl, direction="both", depth=1, max_nodes=25
    ),
    "errors": list(gas_opencl.errors()),
    "before": before,
    "sync": synced,
    "after": after,
})
```

## Common Failure Modes

- Treating Gas OpenCL rows as SOP `bindings#` rows or COP signatures.
- Forgetting to bind a field as writable.
- Assuming fields are aligned when Force Align is disabled.
- Applying fixed decay once per substep instead of using `@TimeInc`.
- Forcing CPU readback with Flush Attributes unnecessarily.
- Recompiling every timestep through changing kernel options.
- Omitting global-ID bounds checks in explicit kernels.
- Incorrect barriers in workset kernels.
- Concurrent RPC inspection of large or unlocked solver networks.

## References

- `help_prepared/nodes/dop/gasopencl.txt`
- `help_prepared/vex/ocl.txt`
- Installed OpenCL files under `$HFS/houdini/ocl/`
