"""Apply VRCFaceTracking eye and expression parameters to a Blender rig."""

import time

from mathutils import Euler


FACE_TRACKING_TIMEOUT = 1.0


def _get_value(values, parameter_name):
    """Find a parameter even when the avatar prefixes its v2 category."""
    for name, value in values.items():
        if name == parameter_name or name.endswith("/" + parameter_name):
            return value
    return None


def _shape_key_value(mesh, key_name):
    if not mesh or not key_name or not mesh.data.shape_keys:
        return None
    return mesh.data.shape_keys.key_blocks.get(key_name)


def capture_eye_baselines(armature, scene):
    baselines = {}
    for name in (
        scene.puppetvmc_face_left_eye_bone,
        scene.puppetvmc_face_right_eye_bone,
        scene.puppetvmc_face_eyelid_left_bone,
        scene.puppetvmc_face_eyelid_right_bone,
    ):
        if name and name not in baselines:
            pose_bone = armature.pose.bones.get(name)
            if pose_bone:
                baselines[name] = pose_bone.matrix_basis.to_quaternion().copy()
    return baselines


def _apply_eye(armature, bone_name, horizontal, vertical, scene, baselines):
    if not bone_name:
        return
    pose_bone = armature.pose.bones.get(bone_name)
    baseline = baselines.get(bone_name)
    if pose_bone is None or baseline is None:
        return

    limit = scene.puppetvmc_face_eye_max_angle
    horizontal_sign = -1.0 if scene.puppetvmc_face_eye_invert_horizontal else 1.0
    vertical_sign = -1.0 if scene.puppetvmc_face_eye_invert_vertical else 1.0
    yaw = max(-1.0, min(1.0, horizontal)) * limit * horizontal_sign
    pitch = max(-1.0, min(1.0, vertical)) * limit * vertical_sign

    pose_bone.rotation_mode = 'QUATERNION'
    pose_bone.rotation_quaternion = (
        baseline @ Euler((pitch, 0.0, -yaw), 'XYZ').to_quaternion()
    )


def _apply_eyelid(armature, bone_name, value, scene, baselines):
    if not bone_name or value is None:
        return
    pose_bone = armature.pose.bones.get(bone_name)
    baseline = baselines.get(bone_name)
    if pose_bone is None or baseline is None:
        return

    angle = scene.puppetvmc_face_eyelid_max_angle * max(0.0, min(1.0, value))
    if scene.puppetvmc_face_eyelid_invert:
        angle = -angle
    pose_bone.rotation_mode = 'QUATERNION'
    pose_bone.rotation_quaternion = baseline @ Euler((angle, 0.0, 0.0), 'XYZ').to_quaternion()


def _apply_shape_key(mesh, key_name, value):
    key_block = _shape_key_value(mesh, key_name)
    if key_block is not None and value is not None:
        key_block.value = max(0.0, min(1.0, value))


def apply_face_tracking(armature, scene, values, baselines, last_received):
    stale = (
        last_received is not None
        and time.time() - last_received > FACE_TRACKING_TIMEOUT
    )
    if stale:
        values = {}

    for side in ("Left", "Right"):
        horizontal = _get_value(values, f"v2/Eye{side}X")
        vertical = _get_value(values, f"v2/Eye{side}Y")
        if stale:
            bone_name = getattr(
                scene, f"puppetvmc_face_{side.lower()}_eye_bone"
            )
            baseline = baselines.get(bone_name)
            pose_bone = armature.pose.bones.get(bone_name) if bone_name else None
            if pose_bone is not None and baseline is not None:
                pose_bone.rotation_mode = 'QUATERNION'
                pose_bone.rotation_quaternion = baseline.copy()
        elif horizontal is not None or vertical is not None:
            _apply_eye(
                armature,
                getattr(scene, f"puppetvmc_face_{side.lower()}_eye_bone"),
                horizontal or 0.0,
                vertical or 0.0,
                scene,
                baselines,
            )

    mesh = scene.puppetvmc_face_mesh
    for side in ("Left", "Right"):
        suffix = side.lower()
        value = None if stale else _get_value(values, f"v2/EyeClosed{side}")
        bone_name = getattr(scene, f"puppetvmc_face_eyelid_{suffix}_bone")
        if stale:
            baseline = baselines.get(bone_name)
            pose_bone = armature.pose.bones.get(bone_name) if bone_name else None
            if pose_bone is not None and baseline is not None:
                pose_bone.rotation_mode = 'QUATERNION'
                pose_bone.rotation_quaternion = baseline.copy()
            _apply_shape_key(
                mesh, getattr(scene, f"puppetvmc_face_blink_{suffix}_key"), 0.0
            )
        elif bone_name:
            _apply_eyelid(armature, bone_name, value, scene, baselines)
        else:
            _apply_shape_key(
                mesh, getattr(scene, f"puppetvmc_face_blink_{suffix}_key"), value
            )

    _apply_shape_key(
        mesh,
        scene.puppetvmc_face_brow_up_key,
        0.0 if stale else _get_value(values, "v2/BrowUp"),
    )
    _apply_shape_key(
        mesh,
        scene.puppetvmc_face_brow_down_left_key,
        0.0 if stale else _get_value(values, "v2/BrowDownLeft"),
    )
    _apply_shape_key(
        mesh,
        scene.puppetvmc_face_brow_down_right_key,
        0.0 if stale else _get_value(values, "v2/BrowDownRight"),
    )
