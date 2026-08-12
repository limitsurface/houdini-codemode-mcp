---
name: houdini-opencl-sops
description: Guidance for OpenCL SOP geometry work, including attribute bindings, solver patterns, worksets, and native Otis references.
---

# OpenCL in SOP Workflows

Use this guidance for OpenCL SOP geometry kernels. For Gas OpenCL and DOP
microsolvers, read `opencl_dops.md`. Copernicus uses a different signature
and layer model; read `copernicus.md` for COP work.

## Core Guidance

1. Use the established patterns in this guide directly for routine kernels.
   Inspect a relevant shipped kernel when behavior is unfamiliar, the task is
   solver-specific, synchronization is complex, or the documentation is
   unclear.
2. Prefer `#bind` and `@KERNEL` for small geometry kernels. Let `ctx.opencl.sync(node, clear=True)` create binding rows and spare
   parameters in the same Code Mode run.
3. After editing a kernel, run `ctx.opencl.sync`, `ctx.opencl.validate`, and
   inspect `node.errors()` before judging the result.
4. Treat external `.cl` kernels as a separate tier. Heavy solvers often use
   explicit signatures, worksets, local memory, barriers, and reductions that
   are clearer and more controllable outside the `@`-binding layer.
5. Keep RPC inspection serial. Do not issue concurrent HOM/RPyC reads against
   large or unlocked solver HDAs.

## Minimal Geometry Kernel

```c
#bind point &P float3
#bind parm amplitude float val=0.1

@KERNEL
{
    float3 p = @P;
    @P.set(p * (1.0f + @amplitude * sin(p.y * 10.0f)));
}
```

Synchronize and validate with this one complete Code Mode program:

Submit this as one complete `houdini_code_run` program; provide
`root_path` and `opencl_path` in `args`.

```python
root = hou.node(args["root_path"])
opencl = hou.node(args["opencl_path"])
if root is None or opencl is None:
    raise hou.OperationFailed("root_path or opencl_path does not resolve")

before = ctx.opencl.validate(opencl, details=True)
synced = ctx.opencl.sync(opencl, clear=True, details=True)
after = ctx.opencl.validate(opencl, details=True)
result.emit({
    "opencl_nodes": ctx.nodes.find(
        root, type_name="opencl", max_depth=12, max_nodes=50
    ),
    "kernel_parms": ctx.parms.project(
        opencl, ["kernelcode", "kernelfile", "kernelname"], value_mode="full"
    ),
    "connections": ctx.nodes.neighbors(
        opencl, direction="both", depth=1, max_nodes=25
    ),
    "errors": list(opencl.errors()),
    "before": before,
    "sync": synced,
    "after": after,
})
```

For an OpenCL SOP, sync rebuilds the node's binding multiparm and generated
scalar/vector controls. It does not create COP-style visible input/output
signature rows.

## Geometry Bindings

Common forms:

```c
#bind point &P float3
#bind point v float3
#bind point &mass float
#bind prim stiffness float
#bind detail &iteration int
#bind parm damping float val=0.1
```

Binding modifiers:

| Form | Meaning |
| :--- | :--- |
| `&name` | Writable binding |
| `!name` | Write-only; avoids uploading existing values |
| `?name` | Optional binding |
| `val=x` | Default value when supported or missing |
| `input=N` | Read the attribute from SOP input `N` |
| `name=attr` | Bind under an alias while reading attribute `attr` |

Use setters for writable vector values:

```c
@P.set(new_position);
@v.set(new_velocity);
```

Scalar assignment is also common in shipped kernels:

```c
@stiffness = mix(@start_stiffness, @end_stiffness, @time);
```

## Houdini 22 BVH Attribute Queries

Houdini 22 adds accelerated spatial queries to readable `float3` geometry
attribute bindings. The two acceleration modes are mutually exclusive. See
the bundled [SideFX OpenCL attribute binding methods](help_prepared/vex/ocl.txt#attribute-binding-methods)
for the authoritative signatures and constraints.

```c
#bind point surfaceP name=P float3 input=1 bvh
#bind point cloudP name=P float3 input=1 pointbvh
#bind point maskedP name=P float3 input=1 pointbvh pointbvhmask=active
```

- `bvh` builds a surface BVH from input triangles. The binding may be a point
  or vertex `float3` attribute.
- `pointbvh` builds one leaf per point and requires a point `float3` attribute.
- `pointbvhmask=<attribute>` is valid only with `pointbvh`. The named integer
  point attribute includes points whose value is nonzero.
- Do not put `bvh` and `pointbvh` on the same binding. Although both node
  toggles can be enabled, SideFX defines the modes as incompatible.
- These modifiers require Houdini 22 or newer. The Code Mode helper rejects them in older
  Houdini sessions before changing the node interface.

Surface BVH methods are `xyzdist`, `xyzdist_max`, `minpos`, `minpos_max`,
`closest_idx`, and `closest_idx_max`. Point BVH methods are `nearpoint`,
`nearpoint_max`, `nearpoints`, `minpos`, and `minpos_max`.

Important return-value details:

- `xyzdist` returns the closest position, not a distance. It writes the BVH
  triangle-list index and barycentric `(u, v, w)` coordinates.
- `closest_idx` returns triangle corner `0`, `1`, or `2`; it does not return a
  Houdini point number.
- `nearpoint` returns a point number and writes Euclidean distance.
- `nearpoints` returns the number of matches and writes point numbers plus
  squared distances, ordered nearest first. Allocate both arrays to size `k`.
- A failed surface `_max` query writes triangle index `-1` and returns zero
  position. A failed point `nearpoint_max` returns `-1` and leaves distance at
  the supplied maximum.

Surface construction does not triangulate. Only primitives that are already
triangles enter the BVH; quads and n-gons are ignored. Its triangle index
matches a Houdini primitive number only when every primitive is a triangle.
Triangulate explicitly when primitive correspondence matters.

A minimal surface projection uses the query position from the first input and
the BVH built from the second input:

```c
#bind point &P float3
#bind point surfaceP name=P float3 input=1 bvh

@KERNEL
{
    float3 projected = @surfaceP.minpos(@P);
    @P.set(projected);
}
```

## Multiple Geometry Inputs

Native Otis kernels use aliases to read matching attributes from other SOP
inputs:

```c
#bind point &P float3
#bind point startP float3 input=1 name=P
#bind point endP float3 input=2 name=P
#bind point ?pintoanimation int val=0
#bind parm time float

@KERNEL
{
    if (!@pintoanimation)
        return;
    @P.set(mix(@startP, @endP, @time));
}
```

This pattern is useful for target animation, state interpolation, rest-shape
updates, and transferring solver controls without a CPU-side attribute copy.

## Optional Attributes

Optional bindings generate `HAS_<name>` compile definitions. Guard optional
reads and writes when no default value is supplied:

```c
#bind prim &?fiberstiffness float
#bind prim ?targetfiberstiffness float input=1 name=fiberstiffness

@KERNEL
{
#if defined(HAS_fiberstiffness) && defined(HAS_targetfiberstiffness)
    @fiberstiffness = @targetfiberstiffness;
#endif
}
```

Use `val=0` when a simple fallback is sufficient and branching is unnecessary.

## Time and Substeps

Simulation kernels must remain stable when substep counts change. Use
`@TimeInc` for integration:

```c
@v.set(@v + @gravity * @TimeInc);
@P.set(@P + @v * @TimeInc);
```

For a frame-based damping control, convert to a per-timestep multiplier:

```c
float scale = 1.0f - clamp(@damping, 0.0f, 1.0f);
float subscale = pow(scale, 24.0f * @TimeInc);
@v.set(@v * subscale);
```

For percentage decay per second:

```c
float decay = pow(1.0f - rate, @TimeInc);
value *= decay;
```

Avoid applying a fixed damping or decay factor once per substep; that changes
the result when the solver's substep count changes.

## Solver State Patterns

Small OpenCL SOPs are effective orchestration stages around a heavier solve:

- copy current positions to previous-iteration state;
- build inertial targets from position, velocity, gravity, and timestep;
- update velocity from current and previous position;
- interpolate target attributes between time samples;
- initialize or update detail-state scalars;
- apply relaxation or acceleration after a constraint solve;
- damp velocity after integration.

Detail attributes can hold solver-wide state such as iteration counters and
relaxation coefficients. These kernels must still guard `get_global_id(0)`
against the bound length when using explicit OpenCL signatures.

## Worksets and Heavy Solvers

The Otis VBD solve uses an external kernel with worksets, fixed workgroup size,
local memory, barriers, and reduction:

1. Worksets contain independent colored points so updates can occur without
   conflicting writes.
2. A workgroup processes one point.
3. Threads accumulate force and Hessian contributions from incident
   primitives and contacts.
4. Values are reduced in local memory with
   `barrier(CLK_LOCAL_MEM_FENCE)`.
5. Thread zero solves and writes the position update.

This is the appropriate model when each output element depends on a variable
number of constraints. It is substantially more complex than a normal
one-thread-per-point `@KERNEL`.

Always bounds-check explicit kernels because global sizes may be rounded up:

```c
int idx = get_global_id(0);
if (idx >= P_length)
    return;
```

Use barriers only when all relevant work-items follow compatible control flow.
Returning before a barrier from only part of a workgroup can deadlock or
produce undefined behavior.

## Relaxation and Iterative Solves

The Otis solver separates iteration state and relaxation into small kernels:

- update a detail `omega` value from the iteration count;
- copy current `P` to a previous-iteration attribute;
- apply relaxed displacement unless the point is pinned or marked for
  fallback;
- preserve the last iteration for the next update.

Separating these stages keeps dependencies explicit and avoids unsafe
read-after-write assumptions inside a single parallel dispatch.

## Native Reference Nodes

The installed nodes and files are useful references when a task needs a
solver-specific or advanced pattern.

### Otis Solver SOP

Create or inspect an `otissolver` SOP, then use the bounded `ctx.nodes.find` call in the Code Mode program below with the Otis node as `root_path`.

| Node | Pattern |
| :--- | :--- |
| `forward_step` | Position/velocity integration, inertial targets, gravity, `@TimeInc` |
| `update_velocity` | Velocity reconstruction from current and previous position |
| `damp_velocity` | Substep-invariant damping |
| `interpolate_hard_pins` | Multi-input point bindings, optional pin mask |
| `interpolate_soft_pins` | Target interpolation for soft constraints |
| `interpolate_rest_shape` | Time interpolation of rest attributes |
| `interpolate_stiffness` | Primitive bindings and guarded optional attributes |
| `copy_P_from_target` | Conditional attribute transfer from input geometry |
| `copy_p_to_previter` | Explicit state copy between iterations |
| `update_omega1` | Detail-state update using external kernel |
| `apply_omega1` | Iterative relaxation/acceleration |
| `energy_solve1` | Worksets, graph coloring, local reduction, constraint solve |

Heavy Otis kernels are installed under Houdini's OpenCL include tree. In
Houdini 21.0, `sim/vbd_energy.cl` is a key reference for VBD energy assembly,
collision terms, local-memory reduction, and relaxation.

## Live Inspection Workflow

Use the same one complete Code Mode program for serial inspection, parameter
projection, interface synchronization, validation, connection inspection, and
node errors. When the node does not use a code snippet, inspect its returned
`kernelfile` and `kernelname`, then open the installed `.cl` file.

Submit this as one complete `houdini_code_run` program; provide
`root_path` and `opencl_path` in `args`.

```python
root = hou.node(args["root_path"])
opencl = hou.node(args["opencl_path"])
if root is None or opencl is None:
    raise hou.OperationFailed("root_path or opencl_path does not resolve")

before = ctx.opencl.validate(opencl, details=True)
synced = ctx.opencl.sync(opencl, clear=True, details=True)
after = ctx.opencl.validate(opencl, details=True)
result.emit({
    "opencl_nodes": ctx.nodes.find(
        root, type_name="opencl", max_depth=12, max_nodes=50
    ),
    "kernel_parms": ctx.parms.project(
        opencl, ["kernelcode", "kernelfile", "kernelname"], value_mode="full"
    ),
    "connections": ctx.nodes.neighbors(
        opencl, direction="both", depth=1, max_nodes=25
    ),
    "errors": list(opencl.errors()),
    "before": before,
    "sync": synced,
    "after": after,
})
```

## Common Failure Modes

- Treating SOP attribute bindings as COP signature ports.
- Syncing only scalar bindings on an OpenCL SOP; SOPs need all attribute,
  volume, VDB, and scalar binding rows.
- Assuming `kernelcode` contains code when the node uses an external
  `kernelfile`.
- Reading and writing neighboring elements in one dispatch without coloring,
  double buffering, atomics, or another race-avoidance strategy.
- Forgetting `@TimeInc`, making damping or decay depend on substeps.
- Using optional attributes without `HAS_` guards or defaults.
- Omitting length checks in explicit kernels.
- Using a barrier in divergent control flow.
- Enabling `Finish Kernels` everywhere, which can serialize the GPU pipeline;
  enable it while debugging and only where synchronization is required.
- Concurrent RPC/HOM inspection of large unlocked solver networks.

## References

- `help_prepared/nodes/sop/opencl.txt`
- `help_prepared/vex/ocl.txt`
- `copernicus.md` for Copernicus-specific bindings and coordinates
- Installed OpenCL files under `$HFS/houdini/ocl/`
