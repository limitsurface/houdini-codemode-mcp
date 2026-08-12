# Copernicus OpenCL Example Index

This index identifies useful native Copernicus nodes and reusable patterns found by inspecting their shipped OpenCL kernels. Inspect the installed node for authoritative current code.

## Inspect Live Code

Use one read-only `houdini_code_run` program instead. Provide `root_path`
in `args`; it returns a bounded list of candidate OpenCL nodes and their
snippet/file parameters.

```python
root = hou.node(args["root_path"])
if root is None:
    raise hou.OperationFailed("root_path does not resolve")

found = ctx.nodes.find(
    root, type_name="opencl", max_depth=5, max_nodes=25
)
kernels = []
path_index = found["nodes"]["cols"].index("p")
for row in found["nodes"]["rows"]:
    node = hou.node(row[path_index])
    if node is not None:
        kernels.append({
            "node": ctx.nodes.summary(node),
            "parms": ctx.parms.project(
                node, ["kernelcode", "kernelfile", "kernelname"], value_mode="full"
            ),
        })
result.emit({"discovery": found, "kernels": kernels})
```

## NOISE

| Node | Use | Reusable kernel references | Imports |
| :--- | :--- | :--- | :--- |
| **bubblenoise** | Generates bubble noise. | multi-pass/iterative loop; procedural noise composition; shared post-processing pipeline | None |
| **cloudnoise3d** | Generates a billowy cloud noise. | multi-pass/iterative loop; procedural noise composition; shared post-processing pipeline | None |
| **crystalnoise** | Generates a sharp and angular Worley noise type. | shared post-processing pipeline | `postprocessing.h` |
| **crystalnoise3d** | Generates a sharp and angular Worley noise type from 3D locations. | shared post-processing pipeline | `postprocessing.h` |
| **denoisetvd** | Removes white noise from an image. | bounded neighborhood sampling; multi-pass/iterative loop | None |
| **fractalnoise** | Generates fractal noise. | `_fbm_noisewrap_perlin*() family`; `_fbm_noisewrap_worleyA*() family`; `_fbm_worley_F2F1_2()`; `CALLFUNC macro`; polar/trigonometric remapping; procedural noise composition | `postprocessing.h`, `random.h`, `mtlx_noise_internal.h`, `alligator.h`, `gxnoise.h`, `mtlx_noise.h` |
| **fractalnoise3d** | Generates fractal noise from 3D locations. | `_fbm_noisewrap_gxnoise*() family`; `_fbm_noisewrap_perlin*() family`; `_fbm_noisewrap_worleyA*() family`; `CALLFUNC macro`; procedural noise composition; shared post-processing pipeline | `postprocessing.h`, `random.h`, `gxnoise.h`, `mtlx_noise_internal.h`, `alligator.h`, `mtlx_noise.h` |
| **phasornoise** | Generates phasor noise, which resembles a wave pattern. | `rot2d()`; `maptoUnit()`; `maptoPi()`; multi-pass/iterative loop; polar/trigonometric remapping; shared post-processing pipeline | `random.h`, `postprocessing.h` |
| **worleynoise** | Generates Worley noise. | `metric_dist()`; multi-pass/iterative loop; procedural noise composition; shared post-processing pipeline | `postprocessing.h`, `mtlx_noise_internal.h`, `mtlx_noise.h` |
| **worleynoise3d** | Generates Worley noise from 3D locations. | `metric_dist()`; `vop_bias()`; `vop_gain()`; multi-pass/iterative loop; procedural noise composition; shared post-processing pipeline | `postprocessing.h`, `mtlx_noise_internal.h`, `mtlx_noise.h` |

## COLOR

| Node | Use | Reusable kernel references | Imports |
| :--- | :--- | :--- | :--- |
| **colorcorrect** | Adjusts colors in the image. | `applyGamma()`; `gaussianBlend()`; masked safe mixing | None |
| **contrast** | Applies contrast to a layer. | masked safe mixing | None |
| **gamma** | Applies gamma correction to a layer. | masked safe mixing | None |
| **tonemap** | Applies a filmic tone mapping curve to compress a high dynamic range input into a displayable range. | `aces_filmic()`; masked safe mixing | None |

## FILTER

| Node | Use | Reusable kernel references | Imports |
| :--- | :--- | :--- | :--- |
| **convolve3** | Convolves a layer by a 3x3 kernel. | `_doscale()`; `_baseopval()`; `_doop()`; integer-index buffer access; pixel-footprint-aware scaling; masked safe mixing | None |
| **edgedetect** | Detects edges in the input image. | integer-index buffer access; multi-pass/iterative loop; polar/trigonometric remapping | None |
| **edgedetectcontour** | Detects varying-width silhouette lines. | `gaussian_weight()`; integer-index buffer access; multi-pass/iterative loop | None |
| **edgedetectdepth** | Detects varying-width self-occluding silhouettes. | `gaussian_weight()`; integer-index buffer access; multi-pass/iterative loop | None |
| **edgedetectnormal** | Detects varying-width crease-lines. | `gaussian_weight()`; integer-index buffer access; multi-pass/iterative loop | None |
| **feather** | Smooths out sharp changes in contrast. | integer-index buffer access; explicit indexed output writes; multi-pass/iterative loop | None |
| **sharpen** | Sharpens an input layer to increase the definition of its edges. | `__threshold()`; masked safe mixing | None |

## TRANSFORM

| Node | Use | Reusable kernel references | Imports |
| :--- | :--- | :--- | :--- |
| **bend** | Curves images using handles or a captured region. | captured-region coordinate deformation | None |
| **mirror** | Mirrors an image based on an arbitrary number of planes. | point-attribute driven processing | None |
| **spacetransform** | Transforms positions and UV values between spaces. | `Q macro` | None |
| **swirl** | Twists an image layer into a spiral shape. | `getBound()`; `modTile()`; `rot2d()`; point-attribute driven processing; multi-pass/iterative loop; polar/trigonometric remapping | None |
| **uvxform** | Transforms the values of a UV layer in 2d space. | `_dorotate()`; polar/trigonometric remapping | `random.h` |

## SDF

| Node | Use | Reusable kernel references | Imports |
| :--- | :--- | :--- | :--- |
| **idtosdf** | Computes a Signed Distance Field from changes in ID values. | bounded neighborhood sampling; multi-pass/iterative loop; pixel-footprint-aware scaling | None |
| **monotosdf** | Computes a signed distance field from an iso-level of a mono layer. | bounded neighborhood sampling; multi-pass/iterative loop; pixel-footprint-aware scaling | None |
| **sdfadjust** | Modifies the values for a Mono SDF layer. | SDF offset and range adjustment | None |
| **sdfblend** | Combines two Mono SDF layers. | SDF boolean and smooth blending | None |
| **sdfshape** | Builds a 2D signed distance field of a selected shape. | analytic 2D SDF primitives | None |
| **sdftomono** | Converts an SDF field to a Mono image layer. | `_domirror()`; `_dowrap()`; pixel-footprint-aware scaling | None |
| **sdftorgb** | Converts an SDF field to an RGB color layer. | pixel-footprint-aware scaling | None |

## UTILITY

| Node | Use | Reusable kernel references | Imports |
| :--- | :--- | :--- | :--- |
| **bokeh** | Creates a Bokeh effect by expanding each pixel by an aperture shape. | `_circularsegment()`; `_circlebokeh()`; multi-pass/iterative loop; pixel-footprint-aware scaling; masked safe mixing | None |
| **boundrect** | Finds the bounding rectangle of a mask. | integer-index buffer access; atomic accumulation; multi-pass/iterative loop | None |
| **chladni** | Generates interference patterns that represent various vibration modes. | polar/trigonometric remapping | None |
| **chromakey** | Keys an input based on hue, saturation, and luminance ranges. | `expfs()`; `easeIn()`; `easeOut()` | `color.h`, `interpolate.h` |
| **chromaticaberration** | Adds chromatic aberration to your image. | pixel-footprint-aware scaling; masked safe mixing | None |
| **combinenormals** | Blends two normal maps together. | `__unpackNormals()`; `__repackNormals()`; `__whiteoutBlend()`; `OFFSET macro`; masked safe mixing | None |
| **compare** | Creates a mask by comparing two layers. | tolerance-based comparison mask | None |
| **convertdepth** | Converts depth layers between height, depth, and distance. | camera depth/height/distance conversion | None |
| **convertnormal** | Converts normal layers between signed and offset. | signed/offset normal encoding | None |
| **cornerpin** | Pins a layer's corners in a reference layer. | point-attribute driven processing | None |
| **cross** | Performs a cross product of two RGB layers. | per-pixel vector cross product | None |
| **cryptomattedecode** | Decodes a cyrptomatte into coverage and ID. | Cryptomatte ID and coverage unpacking | None |
| **cryptomatteencode** | Encodes a coverage and object hash into a cryptomatte layer. | Cryptomatte ID and coverage packing | None |
| **curvature** | Computes the curvature of a layer. | integer-index buffer access; pixel-footprint-aware scaling | None |
| **defocus** | Defocuses an input layer. | pixel-footprint-aware scaling | None |
| **dilateerode** | Dilates or erodes a layer. | bounded neighborhood sampling; multi-pass/iterative loop; pixel-footprint-aware scaling | None |
| **equalize** | Equalizes colors by stretching or shifting their range. | range normalization and equalization | None |
| **extrapolateboundaries** | Fills empty areas of an image using colors at the edges of non-empty areas. | integer-index buffer access; multi-pass/iterative loop | None |
| **fill** | Fills a layer with a constant value. | integer-index buffer access; masked safe mixing | None |
| **font** | Rasterizes text onto a layer from Type 1, TrueType, and OpenType fonts. | glyph coverage raster compositing | None |
| **heatdistort** | Distorts the input layer to simulate heat around fire and other mirage effects. | masked safe mixing | None |
| **heatdistortbylayer** | Distorts the input layer using another layer to simulate heat around fire and other mirage effects. | masked safe mixing | None |
| **heighttoambientocclusion** | Imagines a sphere for each pixel and determines how occluded that sphere is based on its surroundings. | multi-pass/iterative loop; pixel-footprint-aware scaling; polar/trigonometric remapping | None |
| **heighttonormal** | Converts a height layer to a normal layer. | derivative-to-normal reconstruction | None |
| **heighttoshadow** | Creates shadows using a virtual light source. | `rot3dz()`; `rot3dx()`; `getLayerValue()`; pixel-footprint-aware scaling; polar/trigonometric remapping | None |
| **histogram** | Builds a histogram from a layer. | `_accumbucket()`; atomic accumulation; parallel reduction/ordering | None |
| **hyperbolictile** | Generates hyperbolic polygon tiles for texture patterns. | hyperbolic coordinate tiling | None |
| **idtomask** | Creates a mask from an ID layer based on filtering parameters. | ID filtering to binary mask | None |
| **idtomono** | Converts an ID layer into a mono layer. | ID-to-float conversion | None |
| **kuwaharafilter** | Applies the Kuwahara filter, which creates painterly effects. | `_computeweight()`; pixel-footprint-aware scaling | None |
| **latticedeform** | Applies grid-based deformation to a layer. | bilinear lattice coordinate deformation | None |
| **layerfromcurves** | Render Curves into a Layer. | curve coverage rasterization | None |
| **lensdistort** | Adds radial and tangential distortion to a layer based on OpenCV coefficients. | pixel-footprint-aware scaling | None |
| **light** | Lights a layer given a light direction and normals. | masked safe mixing | None |
| **monotoid** | Converts a mono layer into an ID layer. | float-to-ID conversion | None |
| **monotorgba** | Converts a mono layer into an RGBA layer. | mono/alpha channel packing | None |
| **pixelate** | Increases the size of pixels to pixelate an input layer. | pixel-footprint-aware scaling; masked safe mixing | None |
| **polartouv** | Converts polar coordinate pixels to Cartesian pixels. | polar/trigonometric remapping | None |
| **posmap** | Generates a position map. | `_domirror()`; `_dowrap()` | None |
| **possample** | Samples an input texture by position. | position-driven texture lookup | None |
| **prefixsum** | Computes the prefix sum of a layer. | integer-index buffer access; explicit indexed output writes; multi-pass/iterative loop | None |
| **quantize** | Quantizes input data into discrete steps. | masked safe mixing | None |
| **randommono** | Creates a mono layer with random values. | `sample_discrete()`; point-attribute driven processing; multi-pass/iterative loop | None |
| **randomrgb** | Creates an RGB layer with random colors. | `sample_discrete()`; point-attribute driven processing; integer-index buffer access; multi-pass/iterative loop | None |
| **reactiondiffusion__block__begin** | Start of a Reaction-Diffusion simulation block. | integer-index buffer access; multi-pass/iterative loop; pixel-footprint-aware scaling | None |
| **reactiondiffusion__block__end** | Creates unique patterns by solving the reaction and diffusion of multiple chemicals as described by its inputs and parameters. | reaction-diffusion state writeback | None |
| **rgbatouv** | Splits an RGBA layer into two UV layers. | RGBA channel unpacking | None |
| **rgbtouv** | Splits an RGB layer into UV and mono layers. | RGB channel unpacking | None |
| **sample** | Samples an input layer using a UV layer. | pixel-footprint-aware scaling | None |
| **segmentbyconnectivity** | Segment a layer into connected components. | connected-component label propagation | None |
| **segmentbyvalue** | Segment a mono layer into bands of similar value. | `_dowrap()` | None |
| **slopedir** | Converts a height layer into a direction layer. | VDB sampling/writeback | None |
| **smoothfill** | Smoothly fills a region of a layer. | integer-index buffer access; explicit indexed output writes | None |
| **statistics** | Outputs the average, minimum and maximum values of the input layer | bounded neighborhood sampling | None |
| **statisticsbyid** | Compute statistics for each ID island. | `_float_atomicmax()`; atomic accumulation | None |
| **surfacedither** | Applies a halftone dithering pattern relative to UVs. | UV-aligned halftone thresholding | None |
| **triplanaruv** | Generates UVs in three orthogonal projections. | axis-weighted triplanar projection | None |
| **uvmap** | Generates a UV Map. | `_domirror()`; `_dowrap()` | None |
| **uvmapbyid** | Creates a UV Map for each connected ID island. | atomic accumulation | None |
| **uvtopolar** | Converts Cartesian coordinate pixels to polar coordinate pixels. | polar/trigonometric remapping | None |
| **uvtorgb** | Joins a UV and mono layer into an RGB layer. | UV/mono channel packing | None |
| **uvtorgba** | Joins two UV layers into an RGBA layer. | dual-UV channel packing | None |
| **wipe** | Performs a wipe transition between two images. | pixel-footprint-aware scaling; masked safe mixing | None |
| **zcomp** | Composites two layers by depth. | depth-aware foreground/background compositing | None |

## GEOMETRY

| Node | Use | Reusable kernel references | Imports |
| :--- | :--- | :--- | :--- |
| **bakegeometrytextures** | Generates textures by baking between a low-resolution and high-resolution mesh at interactive speeds. | geometry-driven texture baking | None |
| **curvescatter** | Scatters input stamps along an input curve using randomization controls. | point-attribute driven processing; quaternion orientation; masked safe mixing | `quaternion.h`, `random.h` |
| **shapescatter** | Scatters input stamps across the image using randomization controls. | `random1()`; `xform_is()`; `xform_ts()`; multi-pass/iterative loop; pixel-footprint-aware scaling; polar/trigonometric remapping | `color.h` |

## VDB

| Node | Use | Reusable kernel references | Imports |
| :--- | :--- | :--- | :--- |
| **layerfromvdb** | Sets a layer's values from a VDB. | VDB sampling/writeback | None |
| **rasterizevolume** | Renders a volume viewed through a camera. | `LIGHT_SAMPLE macro`; VDB sampling/writeback | None |
| **vdbfromlayer** | Sets VDB values from the closest values in a layer. | VDB sampling/writeback | None |
| **vdbposmap** | Stores in each voxel that voxel's position. | VDB sampling/writeback | None |
