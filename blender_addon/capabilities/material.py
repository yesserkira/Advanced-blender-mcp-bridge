"""Material creation and assignment capabilities."""

import bpy

from . import register_capability


def material_create_pbr(args: dict) -> dict:
    """Create a Principled BSDF material.

    Args:
        args: {
            "name": str - material name
            "base_color": [r, g, b, a] - default [0.8, 0.8, 0.8, 1.0]
            "metallic": float (0-1) - default 0.0
            "roughness": float (0-1) - default 0.5
            "emission_color": [r, g, b, a] - optional
            "emission_strength": float - optional
            "alpha": float - optional
        }
    """
    name = args.get("name")
    if not name:
        raise ValueError("name is required")

    base_color = args.get("base_color", [0.8, 0.8, 0.8, 1.0])
    metallic = args.get("metallic", 0.0)
    roughness = args.get("roughness", 0.5)
    emission_color = args.get("emission_color")
    emission_strength = args.get("emission_strength")
    alpha = args.get("alpha")

    # Validate
    if len(base_color) != 4:
        raise ValueError("base_color must be [r, g, b, a]")
    if not 0.0 <= metallic <= 1.0:
        raise ValueError("metallic must be between 0 and 1")
    if not 0.0 <= roughness <= 1.0:
        raise ValueError("roughness must be between 0 and 1")
    if emission_color is not None and len(emission_color) != 4:
        raise ValueError("emission_color must be [r, g, b, a]")

    # Push undo checkpoint
    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:material.create_pbr:{cmd_id}")

    # Create material
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    node_tree = mat.node_tree

    # Get Principled BSDF node
    principled = None
    for node in node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            principled = node
            break

    if principled is None:
        raise RuntimeError("Principled BSDF node not found in default node tree")

    inputs_set = []

    # Set inputs
    principled.inputs["Base Color"].default_value = base_color
    inputs_set.append("Base Color")

    principled.inputs["Metallic"].default_value = metallic
    inputs_set.append("Metallic")

    principled.inputs["Roughness"].default_value = roughness
    inputs_set.append("Roughness")

    if emission_color is not None:
        principled.inputs["Emission Color"].default_value = emission_color
        inputs_set.append("Emission Color")

    if emission_strength is not None:
        principled.inputs["Emission Strength"].default_value = emission_strength
        inputs_set.append("Emission Strength")

    if alpha is not None:
        principled.inputs["Alpha"].default_value = alpha
        inputs_set.append("Alpha")

    return {
        "name": mat.name,
        "node_tree": "Principled BSDF",
        "inputs_set": inputs_set,
    }


def material_assign(args: dict) -> dict:
    """Assign an existing material to an object.

    Args:
        args: {
            "object_name": str - target object name
            "material_name": str - material to assign
            "slot": int - material slot index (default 0)
        }
    """
    object_name = args.get("object_name")
    material_name = args.get("material_name")
    slot = args.get("slot", 0)

    if not object_name:
        raise ValueError("object_name is required")
    if not material_name:
        raise ValueError("material_name is required")

    obj = bpy.data.objects.get(object_name)
    if obj is None:
        raise ValueError(f"Object not found: {object_name}")

    mat = bpy.data.materials.get(material_name)
    if mat is None:
        raise ValueError(f"Material not found: {material_name}")

    # Push undo checkpoint
    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:material.assign:{cmd_id}")

    # Assign material
    if len(obj.material_slots) == 0:
        obj.data.materials.append(mat)
        actual_slot = 0
    elif slot < len(obj.material_slots):
        obj.material_slots[slot].material = mat
        actual_slot = slot
    else:
        raise ValueError(
            f"Slot index {slot} out of range. "
            f"Object has {len(obj.material_slots)} slots."
        )

    return {
        "object": obj.name,
        "material": mat.name,
        "slot": actual_slot,
    }


register_capability("material.create_pbr", material_create_pbr)
register_capability("material.assign", material_assign)
