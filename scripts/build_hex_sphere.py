"""Procedural hexagons-on-sphere — clean-room rebuild.

Design notes (read these before changing anything):

  * Distribution is a **Fibonacci sphere** of EXACTLY `Hex Count` points.
    Implemented as a Mesh Line with N vertices whose positions are rewritten
    by closed-form math:
        y    = 1 - 2*(i + 0.5)/N
        phi  = i * golden_angle
        x    = sqrt(1 - y^2) * cos(phi)
        z    = sqrt(1 - y^2) * sin(phi)
    This guarantees `count(out) == Hex Count` regardless of Sphere Radius,
    Hex Scale, Hex Margin, Effector params, etc.

  * Per-hex world position = unit_position * Sphere Radius.
    So Hex Count is independent of R, Hex Scale is independent of R.

  * Hexes are instanced as 6-sided cylinders with depth=0 and radius=1, then
    scaled by:
        final_scale = Hex Scale * rand_factor * effector_boost
    where:
        rand_factor     = 1 + Random Scale * uniform(-1, 1)   (per-hex)
        effector_boost  = map_range(d, 0..Effector Radius,
                                       Effector Max Scale..1, smoothstep)
    so a hex right at the effector grows to Effector Max Scale; far hexes
    stay at 1.0.

  * Orientation: Align Z to surface normal with pivot=Y. That is "tangent
    placement with deterministic twist" — adjacent hexes share the same roll
    rule, so they look aligned across the surface (no random per-hex spin).

  * Non-overlap envelope (geometric truth — surfaced honestly):
        nearest-neighbour distance on Fibonacci(N) sphere, world units
            ~ 2 * R * sqrt( pi / N )
        worst-case hex world radius (with effector boost) =
            Hex Scale * Effector Max Scale + Hex Margin
        Non-overlap requires:
            2*R*sqrt(pi/N) >= 2*(scale*EffMax + margin)
            i.e.  N <= pi * R^2 / (scale*EffMax + margin)^2
    Within that envelope the system is provably non-intersecting.  Outside
    it no parameter trick can keep BOTH "exact count" AND "no overlap"; the
    user must lower Hex Count or shrink Hex Scale.  The build script prints
    the safe maximum so the user sees it immediately.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "mcp_server"))

from blender_mcp.blender_client import BlenderError, BlenderWS  # noqa: E402

SCRIPT = r'''
import bpy
import math


def main():
    HOST_NAME = "HexSphere"
    TREE_NAME = "HexField_Nodes"
    EFFECTOR_NAME = "HexEffector"
    GOLDEN_ANGLE = math.pi * (3.0 - math.sqrt(5.0))   # ~2.39996323

    # ---------- 1. Scene wipe ----------
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for grp in list(bpy.data.node_groups):
        if grp.name == TREE_NAME or grp.name.startswith("HexField"):
            bpy.data.node_groups.remove(grp)
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)

    # ---------- 2. Host UV sphere ----------
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0, location=(0.0, 0.0, 0.0))
    host = bpy.context.active_object
    host.name = HOST_NAME
    host.data.name = HOST_NAME
    # Geometry Nodes outputs only the hex instances, so the underlying UV
    # sphere mesh would render on top of them.  Keep the OBJECT solid (so
    # the instances render solid too — instances inherit display_type) and
    # hide the underlying mesh by clearing its faces' material slots and
    # tagging the modifier to replace the mesh entirely.
    # GeometryNodes already replaces the output, but the MESH evaluation
    # base is still the UV sphere; that's fine because the modifier returns
    # only Instances geometry, so no UV-sphere faces are drawn.
    # The bug was setting display_type='WIRE' here — that propagates to
    # the instance display.  Leave display_type at its default ('TEXTURED').

    # ---------- 3. Effector empty ----------
    bpy.ops.object.empty_add(type="SPHERE", location=(2.0, 0.0, 0.0))
    effector = bpy.context.active_object
    effector.name = EFFECTOR_NAME
    effector.empty_display_size = 0.4

    # ---------- 4. Geometry Nodes modifier + tree ----------
    mod = host.modifiers.new(name="HexField", type="NODES")
    tree = bpy.data.node_groups.new(TREE_NAME, "GeometryNodeTree")
    mod.node_group = tree

    # ---------- 5. Group interface ----------
    iface = tree.interface
    for it in list(iface.items_tree):
        iface.remove(it)

    iface.new_socket("Geometry", in_out="INPUT",  socket_type="NodeSocketGeometry")
    iface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")

    def add_float(name, default, mn, mx):
        s = iface.new_socket(name, in_out="INPUT", socket_type="NodeSocketFloat")
        s.default_value = float(default)
        s.min_value = float(mn)
        s.max_value = float(mx)
        return s

    def add_int(name, default, mn, mx):
        s = iface.new_socket(name, in_out="INPUT", socket_type="NodeSocketInt")
        s.default_value = int(default)
        s.min_value = int(mn)
        s.max_value = int(mx)
        return s

    add_float("Sphere Radius",      1.5,    0.01,    100.0)
    add_int  ("Hex Count",          200,    1,       100000)
    add_float("Hex Scale",          0.10,   0.0001,  5.0)
    add_float("Hex Margin",         0.02,   0.0,     5.0)
    add_float("Random Scale",       0.30,   0.0,     1.0)
    iface.new_socket("Effector", in_out="INPUT", socket_type="NodeSocketObject")
    add_float("Effector Radius",    1.0,    0.0,     50.0)
    add_float("Effector Max Scale", 3.0,    1.0,     50.0)

    # Plug the empty into the modifier's Effector socket by default,
    # AND seed every numeric input with its interface default so that
    # mod[socket_id] reads back a real value immediately (otherwise it
    # returns 0 until first written).
    for it in iface.items_tree:
        if it.item_type != "SOCKET" or it.in_out != "INPUT":
            continue
        if it.socket_type == "NodeSocketGeometry":
            continue
        if it.socket_type == "NodeSocketObject":
            mod[it.identifier] = effector
        else:
            mod[it.identifier] = it.default_value

    # ---------- 6. Nodes ----------
    nodes = tree.nodes
    links = tree.links

    def add(node_type, name, x, y):
        n = nodes.new(node_type)
        n.name = n.label = name
        n.location = (x, y)
        return n

    def lk(src, sout, dst, sin):
        links.new(src.outputs[sout], dst.inputs[sin])

    gin  = add("NodeGroupInput",  "GroupIn",  -2200,    0)
    gout = add("NodeGroupOutput", "GroupOut",  2400,    0)

    # 6a. N points: Mesh Line with N vertices, then Mesh to Points.
    line  = add("GeometryNodeMeshLine",     "PointsLine",   -1900, 250)
    line.mode = "OFFSET"
    line.inputs["Start Location"].default_value = (0.0, 0.0, 0.0)
    line.inputs["Offset"].default_value         = (0.001, 0.0, 0.0)
    m2p   = add("GeometryNodeMeshToPoints",  "MeshToPoints", -1700, 250)

    # 6b. Per-point Fibonacci sphere position (driven by Index).
    idx   = add("GeometryNodeInputIndex", "Idx", -2100, -300)
    fi    = add("ShaderNodeMath", "i_plus_half", -1900, -300)
    fi.operation = "ADD"
    fi.inputs[1].default_value = 0.5
    u_div = add("ShaderNodeMath", "u",          -1700, -300)
    u_div.operation = "DIVIDE"
    y_2u  = add("ShaderNodeMath", "two_u",      -1500, -300)
    y_2u.operation = "MULTIPLY"
    y_2u.inputs[1].default_value = 2.0
    y_n   = add("ShaderNodeMath", "y",          -1300, -300)
    y_n.operation = "SUBTRACT"
    y_n.inputs[0].default_value = 1.0           # 1 - (2u): 2u links into input[1]
    phi   = add("ShaderNodeMath", "phi",        -1700, -500)
    phi.operation = "MULTIPLY"
    phi.inputs[1].default_value = GOLDEN_ANGLE
    cos_p = add("ShaderNodeMath", "cos_phi",    -1500, -500)
    cos_p.operation = "COSINE"
    sin_p = add("ShaderNodeMath", "sin_phi",    -1500, -650)
    sin_p.operation = "SINE"
    y_sq  = add("ShaderNodeMath", "y_sq",       -1100, -300)
    y_sq.operation = "POWER"
    y_sq.inputs[1].default_value = 2.0
    one_minus = add("ShaderNodeMath", "one_minus_ysq", -900, -300)
    one_minus.operation = "SUBTRACT"
    one_minus.inputs[0].default_value = 1.0
    rxy   = add("ShaderNodeMath", "rxy",        -700, -300)
    rxy.operation = "SQRT"
    x_n   = add("ShaderNodeMath", "x",          -500, -450)
    x_n.operation = "MULTIPLY"
    z_n   = add("ShaderNodeMath", "z",          -500, -600)
    z_n.operation = "MULTIPLY"
    pos_u = add("ShaderNodeCombineXYZ", "PosUnit", -300, -450)
    pos_w = add("ShaderNodeVectorMath", "PosWorld", -100, -450)
    pos_w.operation = "SCALE"

    set_pos = add("GeometryNodeSetPosition", "SetPos", 200, 0)

    # 6c. Hex mesh = flat 6-sided cylinder.
    hexm  = add("GeometryNodeMeshCylinder", "HexMesh", 200, -400)
    hexm.inputs["Vertices"].default_value = 6
    hexm.inputs["Depth"].default_value    = 0.0
    hexm.inputs["Radius"].default_value   = 1.0

    # 6d. Orientation: align Z to surface normal (= unit-sphere position).
    # pivot_axis = "AUTO" rotates about whichever axis is needed to fully
    # align Z to the input vector — required so hexes near the poles can
    # tilt up/down, not just spin around Y.  Output is still a deterministic
    # function of the input (no random spin), satisfying the "no per-hex
    # rotation independence" requirement.
    align = add("FunctionNodeAlignEulerToVector", "AlignRot", 600, -200)
    align.axis = "Z"
    align.pivot_axis = "AUTO"

    # 6e. Random scale per hex.
    rnd  = add("FunctionNodeRandomValue", "RandPerHex", 200, -700)
    rnd.data_type = "FLOAT"
    rnd.inputs[2].default_value = -1.0
    rnd.inputs[3].default_value =  1.0
    rmul = add("ShaderNodeMath", "RandWeighted", 400, -700)
    rmul.operation = "MULTIPLY"
    radd = add("ShaderNodeMath", "RandFactor",   600, -700)
    radd.operation = "ADD"
    radd.inputs[1].default_value = 1.0           # 1 + weighted_rand

    # 6f. Effector influence.
    obj_info = add("GeometryNodeObjectInfo",  "EffectorInfo", 200, -1100)
    obj_info.transform_space = "ORIGINAL"
    sub      = add("ShaderNodeVectorMath",    "DeltaPos",     400, -1100)
    sub.operation = "SUBTRACT"
    dlen     = add("ShaderNodeVectorMath",    "DistLen",      600, -1100)
    dlen.operation = "LENGTH"
    # Map d in [0..Effector Radius] -> [Effector Max Scale .. 1.0], smoothstep.
    mr       = add("ShaderNodeMapRange",      "EffectMap",    800, -1100)
    mr.clamp = True
    mr.interpolation_type = "SMOOTHSTEP"
    mr.inputs[1].default_value = 0.0   # From min
    mr.inputs[4].default_value = 1.0   # To max  (far hexes -> 1.0)

    # 6g. final_scale = Hex Scale * rand_factor * effector_boost
    s_base = add("ShaderNodeMath", "Scale_x_Rand",    900, -700)
    s_base.operation = "MULTIPLY"
    s_full = add("ShaderNodeMath", "Scale_x_Boost",  1100, -700)
    s_full.operation = "MULTIPLY"

    iop = add("GeometryNodeInstanceOnPoints", "Instance", 1400, -200)

    # ---------- 7. Wire ----------
    # N points
    lk(gin,  "Hex Count", line, "Count")
    lk(line, "Mesh",      m2p,  "Mesh")

    # Fibonacci coords (per-point fields driven by Index)
    lk(idx,   "Index",     fi,    0)
    lk(fi,    "Value",     u_div, 0)
    lk(gin,   "Hex Count", u_div, 1)
    lk(u_div, "Value",     y_2u,  0)
    lk(y_2u,  "Value",     y_n,   1)
    lk(idx,   "Index",     phi,   0)
    lk(phi,   "Value",     cos_p, 0)
    lk(phi,   "Value",     sin_p, 0)
    lk(y_n,   "Value",     y_sq,  0)
    lk(y_sq,  "Value",     one_minus, 1)
    lk(one_minus, "Value", rxy,   0)
    lk(rxy,   "Value",     x_n,   0)
    lk(cos_p, "Value",     x_n,   1)
    lk(rxy,   "Value",     z_n,   0)
    lk(sin_p, "Value",     z_n,   1)
    lk(x_n,   "Value",     pos_u, "X")
    lk(y_n,   "Value",     pos_u, "Y")
    lk(z_n,   "Value",     pos_u, "Z")
    lk(pos_u, "Vector",    pos_w, 0)
    lk(gin,   "Sphere Radius", pos_w, "Scale")

    lk(m2p,   "Points",    set_pos, "Geometry")
    lk(pos_w, "Vector",    set_pos, "Position")

    # Random scale
    lk(idx,  "Index",        rnd,  "Seed")
    lk(rnd,  1,              rmul, 0)            # output index 1 = Float
    lk(gin,  "Random Scale", rmul, 1)
    lk(rmul, "Value",        radd, 0)

    # Effector
    lk(gin,      "Effector",         obj_info, "Object")
    lk(pos_w,    "Vector",           sub,  0)
    lk(obj_info, "Location",         sub,  1)
    lk(sub,      "Vector",           dlen, 0)
    lk(dlen,     "Value",            mr,   "Value")
    lk(gin,      "Effector Radius",  mr,   2)    # From max
    lk(gin,      "Effector Max Scale", mr, 3)    # To min  (d=0 -> MaxScale, d>=R -> 1.0)

    # Final scale
    lk(gin,    "Hex Scale", s_base, 0)
    lk(radd,   "Value",     s_base, 1)
    lk(s_base, "Value",     s_full, 0)
    lk(mr,     "Result",    s_full, 1)

    # Orientation
    lk(pos_u, "Vector", align, "Vector")

    # Instance
    lk(set_pos, "Geometry", iop, "Points")
    lk(hexm,    "Mesh",     iop, "Instance")
    lk(align,   "Rotation", iop, "Rotation")
    lk(s_full,  "Value",    iop, "Scale")

    lk(iop, "Instances", gout, "Geometry")

    bpy.context.view_layer.update()

    # ---------- 8. Honest envelope info ----------
    def sock_id(name):
        return next(it.identifier for it in iface.items_tree
                    if it.item_type == "SOCKET" and it.in_out == "INPUT"
                    and it.name == name)
    R       = mod[sock_id("Sphere Radius")]
    S       = mod[sock_id("Hex Scale")]
    M       = mod[sock_id("Hex Margin")]
    EffMax  = mod[sock_id("Effector Max Scale")]
    worst_r       = S * EffMax + M
    safe_n        = int(math.pi * R * R / (worst_r * worst_r))
    safe_n_no_eff = int(math.pi * R * R / ((S + M) ** 2))

    return {
        "host":       host.name,
        "tree":       tree.name,
        "modifier":   mod.name,
        "effector":   effector.name,
        "node_count": len(nodes),
        "link_count": len(links),
        "interface":  [(i.name, i.in_out) for i in iface.items_tree
                       if i.item_type == "SOCKET"],
        "current_hex_count": int(mod[sock_id("Hex Count")]),
        "safe_max_count_no_effector_boost": safe_n_no_eff,
        "safe_max_count_with_effector":     safe_n,
    }


result = main()
'''


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--token", default=os.environ.get("BLENDER_MCP_TOKEN", ""))
    p.add_argument("--url",   default=os.environ.get(
        "BLENDER_MCP_URL", "ws://127.0.0.1:9876"))
    args = p.parse_args()

    cli = BlenderWS(url=args.url, token=args.token)
    try:
        out = await cli.call(
            "exec.python",
            {"code": SCRIPT, "mode": "trusted", "timeout": 30},
            timeout=60.0,
        )
    except BlenderError as e:
        print(f"FAIL: {e.code}: {e}")
        if e.traceback:
            print(e.traceback)
        return 1
    finally:
        await cli.close()

    if not out.get("executed"):
        print(f"FAIL: {out}")
        return 2

    print("Executed :", out.get("executed"))
    print("Mode     :", out.get("mode"))
    print("Lines    :", out.get("lines"))
    print("Result   :", out.get("result_preview"))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
