"""Avatar Bind (Unity-style) lookup + applying received transforms to pose
bones, with T-pose calibration and root motion via delta from the
calibration point."""

from mathutils import Vector

from . import state
from .constants import ROOT_HUMANOID_BONE
from .convert import convert_position, convert_rotation


def get_bone_map(context):
    """Builds a dict vmc_name -> bone name from the Avatar Bind UI list."""
    result = {}
    for item in context.scene.puppetvmc_bone_map:
        if item.bone_name:
            result[item.vmc_name] = item.bone_name
    return result


def apply_bone(armature, bone_map, vmc_name, px, py, pz, qx, qy, qz, qw):
    target_bone_name = bone_map.get(vmc_name)
    if not target_bone_name:
        return
    pbone = armature.pose.bones.get(target_bone_name)
    if not pbone:
        return

    current_rot = convert_rotation(qx, qy, qz, qw)

    # T-pose calibration: the first value received after Calibrate becomes
    # the zero point, and only the DIFFERENCE from it is applied afterwards.
    # This absorbs the mismatch between how the tracker physically sits on
    # you and the bone's rest pose in Blender — they don't need to match,
    # only the relative change since calibration matters.
    if vmc_name not in state.calibration["rotations"]:
        state.calibration["rotations"][vmc_name] = current_rot.copy()

    baseline_rot = state.calibration["rotations"][vmc_name]
    delta_rot = baseline_rot.inverted() @ current_rot

    pbone.rotation_mode = 'QUATERNION'
    pbone.rotation_quaternion = delta_rot

    if vmc_name == ROOT_HUMANOID_BONE:
        raw = Vector((px, py, pz))
        if state.calibration["origin"] is None:
            state.calibration["origin"] = raw.copy()
        delta_pos = raw - state.calibration["origin"]
        pbone.location = convert_position(delta_pos.x, delta_pos.y, delta_pos.z)
