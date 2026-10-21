"""Avatar Bind (Unity-style) lookup + applying received transforms to pose
bones, matching how VMC4B applies them.

Key design points (all mirroring VMC4B's core/utility.py + core/config.py):

- VMC bone rotations are WORLD-space Unity (Y-up, left-handed) quaternions.
  To apply them as LOCAL bone rotations on the Blender armature we conjugate
  by the rest-pose parent chain: q_local = parent_quat.inv @ q_world @ parent_quat.
  parent_quat is the accumulated rest-orientation of every ancestor up the
  chain — cached once at Connect time (see build_bone_cache) rather than
  recomputed every tick — this is §2 from the VMC4B comparison.

- For the root ("Hips") VMC sends a world-space position in Unity coordinates.
  It must be transferred to the armature's top-most root bone (the parent-less
  ancestor of Hips), expressed in that root bone's local frame, with Hips'
  rest head offset subtracted — §3 + §10. Putting it straight on Hips'
  pose.location (as the old version did) made the model either not move or
  fly off, because pose-bone.location is local to the parent, not world.

- We apply values ABSOLUTELY (no delta-from-calibration), because the
  parent_quaternion conjugation already absorbs the mismatch between how the
  tracker sits on you and the bone's rest pose. Calibration stays as a
  "reset root origin offset" button for the camera/root baseline only.
"""

from mathutils import Vector, Quaternion

from . import state
from .constants import ROOT_HUMANOID_BONE
from .convert import convert_position, convert_rotation


def _compute_parent_quaternion(bone):
    """Accumulated rest-orientation of all ancestors that propagate rotation.

    Matches VMC4B's HumanoidBone.__init__: walk parent_recursive, multiplying
    each ancestor's rest matrix quaternion, stopping at the first bone with
    use_inherit_rotation == False."""
    quat = bone.matrix.to_quaternion()
    if not bone.use_inherit_rotation:
        return quat
    for parent in bone.parent_recursive:
        quat = parent.matrix.to_quaternion() @ quat
        if not parent.use_inherit_rotation:
            break
    return quat


class _BoneEntry:
    __slots__ = (
        "pose_bone",
        "parent_quaternion",
        "parent_quaternion_inverse",
    )

    def __init__(self, pose_bone):
        self.pose_bone = pose_bone
        self.parent_quaternion = _compute_parent_quaternion(pose_bone.bone)
        self.parent_quaternion_inverse = self.parent_quaternion.inverted()


def get_bone_map(context):
    """Builds a dict vmc_name -> bone name from the Avatar Bind UI list."""
    result = {}
    for item in context.scene.puppetvmc_bone_map:
        if item.bone_name:
            result[item.vmc_name] = item.bone_name
    return result


def get_bone_map_conflicts(context):
    """Return Blender target bones that are assigned to multiple VMC slots."""
    targets = {}
    for vmc_name, bone_name in get_bone_map(context).items():
        targets.setdefault(bone_name, []).append(vmc_name)
    return {
        bone_name: vmc_names
        for bone_name, vmc_names in targets.items()
        if len(vmc_names) > 1
    }


def build_bone_cache(armature):
    """One-time cache built at Connect.

    Mirrors VMC4B's Config().init_pose(): for every mapped VMC slot we store
    the pose bone + its parent_quaternion. We also resolve the virtual "root"
    bone (the parent-less ancestor of Hips) and capture Hips' rest head_local
    offset — both needed to turn the world-space VMC root position into the
    root bone's local frame (§3 + §10)."""
    bone_map = get_bone_map(__import__('bpy').context)
    if bone_map is None:
        return None
    bones = {}
    for vmc_name, bone_name in bone_map.items():
        pb = armature.pose.bones.get(bone_name)
        if pb is not None:
            bones[vmc_name] = _BoneEntry(pb)

    # Find the virtual root: the parent-less ancestor of Hips.
    # This is the bone to which we'll apply the VMC Root/Pos position.
    hips_target = bone_map.get(ROOT_HUMANOID_BONE)
    root_pbone = None
    if hips_target:
        hips_pb = armature.pose.bones.get(hips_target)
        if hips_pb is not None:
            root_pbone = hips_pb
            while root_pbone.parent is not None:
                root_pbone = root_pbone.parent

    root_quaternion = None
    hips_head_local = None
    if root_pbone is not None:
        root_quaternion = _compute_parent_quaternion(root_pbone.bone)
    if hips_target and armature.pose.bones.get(hips_target) is not None:
        hips_head_local = armature.pose.bones.get(hips_target).bone.head_local.copy()

    return {
        "bones": bones,
        "root_pose_bone": root_pbone,
        "root_quaternion": root_quaternion,
        "root_quaternion_inverse": (
            root_quaternion.inverted() if root_quaternion is not None else None
        ),
        "hips_head_local": hips_head_local,
    }


def apply_bone(bone_cache, vmc_name, px, py, pz, qx, qy, qz, qw):
    """Applies VMC bone data using the cached parent_quaternion conjugation.

    For Hips: rotation goes on the Hips pose bone (matching VMC4B), location
    is transferred to the root bone (top ancestor) in its local frame."""
    if bone_cache is None:
        return
    entry = bone_cache["bones"].get(vmc_name)
    if entry is None:
        return
    rquat = convert_rotation(qx, qy, qz, qw)
    pbone = entry.pose_bone
    result_q = (
        entry.parent_quaternion_inverse @ rquat @ entry.parent_quaternion
    )
    pbone.rotation_mode = 'QUATERNION'
    pbone.rotation_quaternion = result_q

    if vmc_name == ROOT_HUMANOID_BONE:
        root_pbone = bone_cache["root_pose_bone"]
        root_q_inverse = bone_cache["root_quaternion_inverse"]
        hips_hl = bone_cache["hips_head_local"]
        if (root_pbone is not None and root_q_inverse is not None
                and hips_hl is not None):
            world_pos = convert_position(px, py, pz)
            # Anchor: subtract the calibration origin (captured on the first
            # frame after Calibrate/the countdown fires) so root motion is
            # relative to wherever you were standing at calibration time, not
            # to SlimeVR's own absolute room-scale origin. Without this the
            # model can spawn arbitrarily far from the Blender scene origin.
            if state.calibration["origin"] is None:
                state.calibration["origin"] = world_pos.copy()
            anchored_pos = world_pos - state.calibration["origin"]
            local = root_q_inverse @ (anchored_pos - hips_hl)
            root_pbone.location = local


def apply_local_bone(bone_cache, vmc_name, qx, qy, qz, qw):
    """Apply a Unity local rotation without world-space parent conjugation."""
    if bone_cache is None:
        return
    entry = bone_cache["bones"].get(vmc_name)
    if entry is None:
        return
    pbone = entry.pose_bone
    pbone.rotation_mode = 'QUATERNION'
    pbone.rotation_quaternion = convert_rotation(qx, qy, qz, qw)