# Blender MCP Workspace

This workspace is a **Blender ↔ AI bridge** via the Model Context Protocol (MCP).
When the user asks to create, modify, or inspect 3D content, use the Blender MCP tools.

## **Always start with `ping`**

Call `ping` at the start of every new conversation. It returns:
- Connection status + Blender version
- Active scene + active camera + active object
- Object/material counts (so you know if the scene is empty or populated)
- Current selection
- Units system (metric/imperial) and render engine

This single call replaces multiple `query`/`list` calls and gives you enough orientation to plan intelligently. **Don't skip it.**

## Available MCP Tools

You have access to these Blender tools (call them directly — the MCP server handles routing):

### Scene & Objects
- `ping` — **call first in every chat**. Returns scene context (objects, selection, units, camera) so you don't have to query separately.
- `query` — inspect objects by name/type (returns transforms, mesh data, etc.)
- `list` — list all objects or filter by type
- `create_primitive` — create mesh primitives (cube, sphere, cylinder, cone, plane, torus, monkey)
- `create_objects` — batch-create multiple objects at once
- `set_transform` — set position/rotation/scale on objects
- `delete_object` — remove objects from the scene
- `duplicate_object` — duplicate an object (linked or full copy) without selection juggling
- `apply_to_selection` — apply operations to the current selection
- `bbox_info` — read-only world-space bounding box {min, max, size, center}
- `set_visibility` — toggle viewport / render / selectable / show flags on object(s)
- `set_parent` / `clear_parent` — reparent existing objects (with `keep_transform`)

### Selection (use these BEFORE operators that need a specific selection)
- `select` — select named objects (`additive` to add, `active` to set active)
- `deselect_all` — clear selection
- `set_active` — set active object (with or without selecting)
- `select_all` — select all (optionally filtered by type)

### Collections
- `create_collection` / `delete_collection` / `list_collections`
- `move_to_collection` — move object(s) into a collection

### Spatial Helpers (use these instead of computing coordinates manually)
- `place_above` — sit object on top of another (or "ground"), auto-aligns Z based on bbox
- `align_to` — align centers/edges along chosen axes (`mode`: center | min | max)
- `array_around` — duplicate N copies in a circle (chair legs, columns, fence posts)
- `distribute` — evenly space objects along a line
- `look_at` — rotate object/camera to face a target (or arbitrary point)

### Materials & Datablocks
- `assign_material` — create and assign materials (PBR: base_color, metallic, roughness, emission, etc.)
- `rename` — **the right way to rename anything** (object, material, mesh, light, image, node_group, action, world, ...). Args: `kind`, `from_name`, `to_name`. Don't use `execute_python` for renames.
- `create_light` — POINT / SUN / SPOT / AREA with energy, color, size (radius / angle), spot params.
- `create_camera` — lens, ortho_scale, sensor, clip planes; `set_active=true` makes it the scene camera.
- `set_active_camera` — switch the active scene camera by object name.
- `create_empty` — controllers / parents (display: PLAIN_AXES, ARROWS, CUBE, SPHERE, CIRCLE, ...).
- `create_text` — 3D text (body, size, extrude, bevel, alignment).
- `create_curve` — bezier / nurbs / poly from a list of control points (`closed`, `bevel_depth`).
- `create_armature` — atomic armature creation with initial bones (parent/connect/roll) — caller stays in OBJECT mode.
- `load_image` — load an image file (use `colorspace="Non-Color"` for normal/roughness/metallic maps).
- `create_image` — blank image datablock (e.g. for procedural baking).

### Mode (use BEFORE EDIT-mode operators)
- `set_mode` — switch interaction mode atomically with compatibility validation (rejects e.g. EDIT on a LIGHT). Pass `object` to also set it active in one call.

### Mesh editing (use INSTEAD of call_operator + EDIT mode dance)
- `mesh_edit` — declarative bmesh DSL: extrude_faces / extrude_edges / extrude_verts, inset_faces, bevel_edges / bevel_verts, subdivide, loop_cut, merge_verts, remove_doubles, delete_*/dissolve_* (verts/edges/faces), bridge_loops, fill, triangulate, recalc_normals, flip_normals, smooth_verts, transform_verts. All ops in one undo step. Bypasses edit mode entirely.
- `mesh_read` — read vertices/edges/faces/normals/uvs with bounded slicing (`start`+`limit`, max 10000/call) so you don't blow up the response.

### Constraints
- `add_constraint` — object OR pose-bone constraints (pass `bone="..."`). Types: COPY_LOCATION, COPY_ROTATION, COPY_SCALE, COPY_TRANSFORMS, LIMIT_*, TRACK_TO, DAMPED_TRACK, IK, FOLLOW_PATH, CHILD_OF, ARMATURE, SHRINKWRAP, ... Convenience: `target` (object name) and `subtarget` (bone name) auto-resolve. Free-form `properties` for the rest (use `describe_api("CopyLocationConstraint")` to discover).
- `remove_constraint` / `list_constraints` — by name on object or pose bone.

### Rigging primitives
- `create_vertex_group` / `remove_vertex_group` / `list_vertex_groups`
- `set_vertex_weights` — `indices` + parallel `weights` list (or single float), `type`: REPLACE / ADD / SUBTRACT.
- `add_shape_key` — first call auto-creates Basis. Pass `from_mix=true` to capture current state.
- `set_shape_key_value` / `remove_shape_key` (single, or `all=true`) / `list_shape_keys`.

### Modifiers
- `add_modifier` — add modifiers (Subdivision, Bevel, Array, Mirror, Solidify, etc.)
- `remove_modifier` — remove a modifier from an object

### Geometry Nodes
- `geonodes_create_modifier` — add a Geometry Nodes modifier with a fresh tree to an object
- `geonodes_create_group` — create a reusable node group
- `geonodes_describe_group` — inspect an existing node group (inputs, outputs, internal nodes)
- `geonodes_set_input` — set an exposed input value on a modifier
- `geonodes_animate_input` — keyframe an exposed input over time
- `geonodes_realize` — bake the geometry-nodes result back to a regular mesh
- `geonodes_list_presets` / `geonodes_get_preset` / `geonodes_apply_preset` — preset library (scatter, bend, extrude_faces, etc.)

### Shader Nodes
- `build_nodes` — build shader / world / compositor node graphs via a DSL
  - **Socket disambiguation**: nodes like `ShaderNodeMix` have `A`/`B`/`Result` sockets for Float, Vector AND Color. Use type-qualified names: `"A:Color"`, `"B:Float"`, `"Result:Vector"`. Or pass an integer index: `6`. Plain `"A"` picks the first match (often wrong).
  - Supports `color_ramp` per-node config: `[{"position": 0.0, "color": [r,g,b,a]}, ...]`
  - Supports `curves` per-node config (RGBCurves/FloatCurve): `[{"points":[{"x":0,"y":0},{"x":1,"y":1}]}]`
  - Auto-handles deprecated node types (e.g. ShaderNodeTexMusgrave → ShaderNodeTexNoise) and reports them in `warnings`
  - **Surgical edits** with `clear: false`: pass `remove_nodes: ["name1"]` and/or `remove_links: [{from:"a.b", to:"c.d"}]` in the graph to delete specific items without rebuilding
  - To inspect existing links of a tree: `query` with target like `material:Name.node_tree.links` returns each link with `from`/`to` socket strings

### Animation
- `set_keyframe` — set keyframes on object properties

### Rendering
- `viewport_screenshot` — take a viewport screenshot (returns base64 image)
- `render_region` — render a region of the viewport
- `bake_preview` — bake a quick preview render

### Assets
- `import_asset` — import external files (FBX, OBJ, glTF, etc.)
- `link_blend` — link/append from .blend files
- `list_assets` — list available asset libraries

### Advanced
- `set_property` / `get_property` — get/set any Blender property by RNA path
- `call_operator` — call any Blender operator (bpy.ops.*). Pass `select=[names]` and/or `active=name` to set up the operator's selection context atomically (no separate select call needed). Most operators that returned `CANCELLED` just needed this.
  - **CANCELLED diagnostic envelope (v3.0)**: when an operator returns CANCELLED, the response now includes `code:"OP_CANCELLED"`, `current_mode`, `expected_mode`, `area_type`, `active_type`, and a one-line `hint` (e.g. "Operator 'mesh.bevel' needs EDIT_MESH; currently OBJECT — call set_mode(...)"). Read these instead of guessing why it failed.
- `execute_python` — run arbitrary Python in Blender (sandboxed by default). **Use sparingly**: prefer dedicated tools (`mesh_edit`, `add_constraint`, `set_mode`, `create_light`, `rename`, ...) when one exists.
- `describe_api` — look up Blender Python API docs for a type/operator
- `transaction` — group multiple operations into a single undo step

### Safety & State
- `scene_diff` — compare current scene to a previous snapshot
- `create_checkpoint` / `list_checkpoints` / `restore_checkpoint` — scene versioning
- `get_audit_log` — view operation history

## Conventions

- All coordinates are in Blender's coordinate system (Z-up, right-handed)
- Colors use linear RGB [0-1] values, e.g. red = [1, 0, 0, 1]
- Rotations are in radians unless stated otherwise
- Object names are case-sensitive
- When creating complex objects, use `create_objects` for batch efficiency
- Always use `viewport_screenshot` to show the user the result after visual changes
- Use `assign_material` after creating objects to add color/appearance
- If unsure about an API, use `describe_api` to look it up

## Workflow Tips

1. Create objects first, then apply materials, then modifiers
2. Use `list` to check what's in the scene before modifying
3. Use `query` to inspect specific objects
4. Take a `viewport_screenshot` after major changes so the user can see the result
5. For complex geo-node setups: `geonodes_create_modifier` to seed a tree, then `geonodes_set_input` for parameters, or use `geonodes_apply_preset` for common patterns. For shader graphs: `build_nodes` (single call) is usually faster than building node-by-node.
6. Use `transaction` to wrap multi-step operations for clean undo
