"""Static, transport-neutral registry for Houdini-side context extensions."""

from __future__ import annotations

from typing import Any


CAPABILITIES: tuple[dict[str, Any], ...] = (
    {
        "name": "ctx.session",
        "purpose": "Read compact session, HIP, version, frame, and selection metadata.",
        "methods": (("info()", "read", "Compact current-session metadata."),),
    },
    {
        "name": "ctx.nodes",
        "purpose": "Bounded node discovery, graph traversal, and compact summaries.",
        "methods": (
            ("summary(node)", "read", "Compact one-node summary."),
            ("list(root, max_depth=1, max_nodes=50, count_only=False)", "read", "Bounded descendants."),
            ("find(root, type_name=None, category=None, name=None, max_depth=1, max_nodes=50, count_only=False)", "read", "Filtered bounded discovery."),
            ("neighbors(node, direction='both', depth=1, max_nodes=50)", "read", "Directional graph neighborhood."),
            ("network_summary(root, max_depth=1, max_nodes=10000, top_types=20, include_boundaries=False, boundary_limit=50)", "read", "Compact network counts, types, and optional boundaries."),
        ),
    },
    {
        "name": "ctx.parms",
        "purpose": "Bounded parameter listing, filtering, and caller-ordered projection.",
        "methods": (
            ("list(node, name=None, parm_type=None, non_default=False, value_mode='summary', max_parms=100, max_items=10)", "read", "Bounded parameter rows."),
            ("find(node, name, parm_type=None, non_default=False, value_mode='summary', max_parms=100, max_items=10)", "read", "Bounded parameter search on one node."),
            ("project(node, names, value_mode='summary', max_items=10)", "read", "Project an explicit ordered parameter set."),
        ),
    },
    {
        "name": "ctx.parm_references",
        "purpose": "Bounded read-only parameter dependency traversal and classification.",
        "methods": (
            ("references(node, descendants=False, external_to=None, max_nodes=1000, max_parms=10000, max_results=1000, max_errors=100)", "read", "Classify direct and channel-expression parameter dependencies."),
        ),
    },
    {
        "name": "ctx.geometry",
        "purpose": "Bounded cooked-geometry summaries and attribute samples.",
        "methods": (
            ("summary(node, topology=False, max_prims=100000, max_histogram=20)", "read/cook", "Counts and optional topology histograms."),
            ("attributes(node, attrib_class=None, max_attribs=100)", "read/cook", "Attribute definitions."),
            ("get(node, name, attrib_class='point', element=None, limit=10)", "read/cook", "Bounded attribute values."),
        ),
    },
    {
        "name": "ctx.cop",
        "purpose": "Bounded Copernicus output metadata and pixel sampling.",
        "methods": (
            ("info(node, output=None)", "read/cook", "Layer/output metadata."),
            ("sample(node, points, output=None, max_points=64)", "read/cook", "Bounded point samples."),
        ),
    },
    {
        "name": "ctx.cop_files",
        "purpose": "Audited Copernicus image import/export with explicit file effects.",
        "methods": (
            ("export_image(node, output_path, mode='raw', output=None, overwrite=False, max_bytes=536870912, display=None, view=None)", "file-write", "Transactional raw/view image export."),
            ("import_image(image_path, parent, name=None, colorspace='ocio', set_display=False, max_bytes=536870912)", "scene-mutation/file-read", "Create a File COP from a bounded input file."),
        ),
    },
    {
        "name": "ctx.viewport",
        "purpose": "Audited Scene Viewer capture without changing pane state.",
        "methods": (
            ("capture(output_path, pane_name=None, index=None, frame=None, width=512, height=512, overwrite=False, max_bytes=67108864)", "file-write", "Capture one bounded Scene Viewer PNG."),
        ),
    },
    {
        "name": "ctx.lop",
        "purpose": "Bounded USD-stage summaries with traversal and path limits.",
        "methods": (("summary(node, output=0, max_depth=None, max_prims=10000, top_types=20, include_paths=False, path_limit=20)", "read/cook", "USD counts, types, paths, and render context."),),
    },
    {
        "name": "ctx.hda",
        "purpose": "Bounded HDA inspection, validation, references, and dry-run planning.",
        "methods": (
            ("inspect(node, parms=False, sections=False, tools=False, max_items=100, max_depth=12)", "read", "Instance and definition metadata."),
            ("definitions(namespace=None, type_name=None, version=None, max_items=100, max_scan=10000)", "read", "Installed definition discovery."),
            ("libraries(definition=None, max_items=100, max_types=100, max_scan=10000)", "read", "Loaded library discovery."),
            ("references(node, descendants=True, max_nodes=1000, max_parms=10000, max_results=1000, max_errors=100)", "read", "External channel-reference audit."),
            ("validate(node, fresh=False, cook=False, frames=None, strict=False, external_references=False, dry_run=False, max_items=1000)", "read/cook/temp-mutation", "Interface/cook/reference validation."),
            ("plan_promotion(node, internal_parms, destination_names=None, folder=None, max_items=25)", "read", "No-effect parameter promotion plan."),
            ("plan_update(node, mode='update', library=None, type_name=None, label=None, contents=True, interface=False, preserve_sections=True, preserve_tools=True, reference_audit=True, overwrite=False, match_current=False, create_backup=True, max_items=100)", "read", "No-effect HDA definition update/copy plan."),
            ("apply_promotion(node, internal_parms, destination_names, folder=None, max_items=25, allow_library_write=False, owned_library=None, create_backup=True)", "library-write/scene-mutation", "Promote internal parameters into one explicitly owned isolated HDA definition."),
            ("package_copy(node, destination_library, type_name=None, label=None, overwrite=False, backup=False, max_items=100)", "file-write", "Stage and atomically publish one HDA definition without installing it."),
        ),
    },
    {
        "name": "ctx.opencl",
        "purpose": "Compound OpenCL binding validation and synchronization for SOP/COP/DOP.",
        "methods": (
            ("validate(node, details=False, cook=True)", "read/cook", "Validate kernel bindings and generated interface."),
            ("sync(node, clear=False, bindings_only=False, preserve_values=True, disconnect_invalid=False, details=False)", "scene-mutation", "Rebuild binding/interface rows."),
        ),
    },
    {
        "name": "ctx.hda_sections",
        "purpose": "Plan, read, set, or delete bounded plain-text sections in one explicitly owned HDA library.",
        "methods": (
            ("plan(node, name, action='set', contents=None, owned_library=None, max_content_bytes=262144)", "read", "Preflight an owned-library plain-section mutation."),
            ("read(node, name, owned_library=None, max_content_bytes=262144)", "read", "Read one bounded plain-text section."),
            ("apply(node, name, action='set', contents=None, owned_library=None, allow_library_write=False, create_backup=True, max_content_bytes=262144)", "library-write", "Set or delete one non-managed section with explicit consent."),
        ),
    },
    {
        "name": "ctx.hda_create",
        "purpose": "Create one new externally stored HDA from an explicit non-HDA source node.",
        "methods": (
            ("plan(node, type_name, label, destination_library, min_inputs=0, max_inputs=0)", "read", "Preflight a new non-overwriting HDA library and source conversion."),
            ("create_owned(node, type_name, label, destination_library, min_inputs=0, max_inputs=0, allow_library_write=False)", "library-write/scene-mutation/install", "Create, install, and re-resolve one new HDA definition with explicit consent."),
        ),
    },
    {
        "name": "ctx.hda_interface",
        "purpose": "Plan and author a bounded declarative parameter interface in one explicitly owned HDA definition.",
        "methods": (
            ("plan(node, items, owned_library=None, conflict_policy='error', max_items=25, max_depth=1)", "read", "Validate supported float/int/string/toggle/menu templates and conflicts."),
            ("apply(node, items, owned_library=None, conflict_policy='error', allow_library_write=False, create_backup=True, max_items=25, max_depth=1)", "library-write/scene-mutation", "Checkpoint contents, author the interface, and synchronize the sole instance."),
            ("plan_defaults_from_current(node, names, owned_library=None, max_items=25, max_components=4)", "read", "Plan explicit supported tuple defaults from current values."),
            ("set_defaults_from_current(node, names, owned_library=None, allow_library_write=False, create_backup=True, max_items=25, max_components=4)", "library-write/scene-mutation", "Checkpoint and persist explicit current tuple values as defaults."),
        ),
    },
    {
        "name": "ctx.hda_tools",
        "purpose": "Inspect or manage one structured SOP/COP Tools.shelf registration.",
        "methods": (
            ("inspect(node, max_items=100)", "read", "Inspect bounded tool names without returning opaque XML."),
            ("plan(node, action='set', submenu=None, context=None, owned_library=None)", "read", "Preflight a structured Tools.shelf set/remove."),
            ("set(node, submenu, context, owned_library=None, allow_library_write=False, create_backup=True)", "library-write", "Generate and set one SOP/COP tab-menu tool."),
            ("remove(node, owned_library=None, allow_library_write=False, create_backup=True)", "library-write", "Remove Tools.shelf with explicit consent."),
        ),
    },
    {
        "name": "ctx.hda_update",
        "purpose": "Guarded whole-definition update for one sole unlocked instance in an explicitly owned library.",
        "methods": (
            ("update_owned(node, owned_library, allow_library_write=False, contents=True, interface=False, preserve_sections=True, preserve_tools=True, create_backup=True, match_current=False, validate=True, validation_cook=False, max_sections=100, max_section_bytes=1048576, max_total_section_bytes=8388608, max_library_bytes=536870912)", "library-write/scene-mutation", "Checkpoint contents, optionally copy the whole interface, preserve bounded text sections, and validate."),
        ),
    },
    {
        "name": "ctx.python",
        "purpose": "Python SOP/COP #bind inspection, validation, and interface synchronization.",
        "methods": (
            ("inspect(node, details=False)", "read", "Parse binding declarations and interface state."),
            ("validate(node, details=False)", "read", "Validate generated controls and links."),
            ("sync(node, dry_run=False, bindings_only=False, prune_generated=False, preserve_values=True, details=False)", "scene-mutation", "Synchronize generated controls."),
        ),
    },
    {
        "name": "ctx.wrangle",
        "purpose": "Synchronize or clear supported VEX wrangle spare parameters.",
        "methods": (
            ("sync(node, clear=False)", "scene-mutation", "Create/update spare controls referenced by VEX."),
            ("clear(node)", "scene-mutation", "Remove generated spare controls."),
        ),
    },
    {
        "name": "ctx.artifacts",
        "purpose": "Keep broad/lossless node .asData payloads in bounded disk artifacts.",
        "methods": (
            ("root()", "read", "Artifact root metadata."),
            ("export_node(node, name=None, children=False, all_parms=False, editables=False, overwrite=False, max_bytes=67108864)", "file-write", "Write a manifest-backed node/network artifact."),
            ("import_node(artifact, parent, name=None, unique=False, max_bytes=67108864)", "scene-mutation/file-read", "Restore an artifact into a network."),
            ("inspect(artifact, max_bytes=67108864)", "file-read", "Read bounded artifact metadata."),
            ("list(max_items=50)", "file-read", "List bounded artifact manifests."),
            ("remove(artifact)", "file-delete", "Delete one artifact."),
        ),
    },
    {
        "name": "ctx.recipes",
        "purpose": "Bounded recipe metadata plus script-suppressed node/parameter preset application.",
        "methods": (
            ("list(category=None, visible_only=False, max_items=100, max_scan=1000, max_recipe_bytes=262144, max_errors=100)", "read", "Discover bounded recipe metadata without script bodies."),
            ("get(recipe_key, max_recipe_bytes=262144)", "read", "Inspect one bounded recipe summary."),
            ("apply_node_preset(recipe_key, node, max_items=100)", "scene-mutation", "Apply only preset parms with scripts and structural surfaces disabled."),
            ("apply_parm_preset(recipe_key, parm, multiparm_operation='', multiparm_start_index=0)", "scene-mutation", "Apply a parameter preset with scripts disabled."),
        ),
    },
)


def capability_names() -> tuple[str, ...]:
    """Return the stable service names for concise transport instructions."""

    return tuple(item["name"] for item in CAPABILITIES)
