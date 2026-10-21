"""Apply VRCFaceTracking eye and expression parameters to a Blender rig."""

import math
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
    if armature is None:
        return baselines
    for name in (
        scene.puppetvmc_face_left_eye_bone,
        scene.puppetvmc_face_right_eye_bone,
        scene.puppetvmc_face_eyelid_left_bone,
        scene.puppetvmc_face_eyelid_right_bone,
        scene.puppetvmc_face_left_upper_eyelid_bone,
        scene.puppetvmc_face_left_lower_eyelid_bone,
        scene.puppetvmc_face_right_upper_eyelid_bone,
        scene.puppetvmc_face_right_lower_eyelid_bone,
        scene.puppetvmc_face_brow_up_bone,
        scene.puppetvmc_face_brow_down_left_bone,
        scene.puppetvmc_face_brow_down_right_bone,
    ):
        if name and name not in baselines:
            pose_bone = armature.pose.bones.get(name)
            if pose_bone:
                baselines[name] = pose_bone.matrix_basis.to_quaternion().copy()
    return baselines


def _apply_eye(armature, bone_name, horizontal, vertical, scene, baselines):
    if armature is None or not bone_name:
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
    _apply_eye_angles(armature, bone_name, yaw, pitch, baselines)


def _apply_eye_angles(armature, bone_name, yaw, pitch, baselines):
    if armature is None or not bone_name:
        return
    pose_bone = armature.pose.bones.get(bone_name)
    baseline = baselines.get(bone_name)
    if pose_bone is None or baseline is None:
        return

    pose_bone.rotation_mode = 'QUATERNION'
    pose_bone.rotation_quaternion = (
        baseline @ Euler((pitch, 0.0, -yaw), 'XYZ').to_quaternion()
    )


def _apply_eyelid(armature, bone_name, value, invert, scene, baselines):
    if armature is None or not bone_name or value is None:
        return
    pose_bone = armature.pose.bones.get(bone_name)
    baseline = baselines.get(bone_name)
    if pose_bone is None or baseline is None:
        return

    angle = scene.puppetvmc_face_eyelid_max_angle * max(0.0, min(1.0, value))
    if invert:
        angle = -angle
    pose_bone.rotation_mode = 'QUATERNION'
    pose_bone.rotation_quaternion = baseline @ Euler((angle, 0.0, 0.0), 'XYZ').to_quaternion()


def _reset_bone(armature, bone_name, baselines):
    if armature is None or not bone_name:
        return
    pose_bone = armature.pose.bones.get(bone_name)
    baseline = baselines.get(bone_name)
    if pose_bone is not None and baseline is not None:
        pose_bone.rotation_mode = 'QUATERNION'
        pose_bone.rotation_quaternion = baseline.copy()


def _apply_brow(armature, bone_name, value, scene, baselines):
    if armature is None or not bone_name:
        return
    pose_bone = armature.pose.bones.get(bone_name)
    baseline = baselines.get(bone_name)
    if pose_bone is None or baseline is None:
        return

    value = max(0.0, min(1.0, value or 0.0))
    angle = scene.puppetvmc_face_brow_max_angle * value
    if scene.puppetvmc_face_brow_invert:
        angle = -angle
    rotation = [0.0, 0.0, 0.0]
    rotation["XYZ".index(scene.puppetvmc_face_brow_rotation_axis)] = angle
    pose_bone.rotation_mode = 'QUATERNION'
    pose_bone.rotation_quaternion = (
        baseline @ Euler(rotation, 'XYZ').to_quaternion()
    )


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
        tracking_angles = _get_value(
            values, "tracking/eye/LeftRightPitchYaw"
        )
        if stale:
            bone_name = getattr(
                scene, f"puppetvmc_face_{side.lower()}_eye_bone"
            )
            _reset_bone(armature, bone_name, baselines)
        elif horizontal is not None or vertical is not None:
            _apply_eye(
                armature,
                getattr(scene, f"puppetvmc_face_{side.lower()}_eye_bone"),
                horizontal or 0.0,
                vertical or 0.0,
                scene,
                baselines,
            )
        elif tracking_angles is not None:
            offset = 0 if side == "Left" else 2
            pitch = max(
                -scene.puppetvmc_face_eye_max_angle,
                min(
                    scene.puppetvmc_face_eye_max_angle,
                    math.radians(tracking_angles[offset]),
                ),
            )
            yaw = max(
                -scene.puppetvmc_face_eye_max_angle,
                min(
                    scene.puppetvmc_face_eye_max_angle,
                    math.radians(tracking_angles[offset + 1]),
                ),
            )
            pitch_sign = (
                -1.0 if scene.puppetvmc_face_eye_invert_vertical else 1.0
            )
            yaw_sign = (
                -1.0 if scene.puppetvmc_face_eye_invert_horizontal else 1.0
            )
            _apply_eye_angles(
                armature,
                getattr(scene, f"puppetvmc_face_{side.lower()}_eye_bone"),
                yaw * yaw_sign,
                pitch * pitch_sign,
                baselines,
            )

    mesh = scene.puppetvmc_face_mesh
    common_blink = _get_value(
        values, "tracking/eye/EyesClosedAmount"
    )
    for side in ("Left", "Right"):
        suffix = side.lower()
        value = None if stale else _get_value(values, f"v2/EyeClosed{side}")
        if value is None and not stale:
            value = common_blink
        upper_bone = getattr(
            scene, f"puppetvmc_face_{suffix}_upper_eyelid_bone"
        )
        lower_bone = getattr(
            scene, f"puppetvmc_face_{suffix}_lower_eyelid_bone"
        )
        legacy_bone = getattr(
            scene, f"puppetvmc_face_eyelid_{suffix}_bone"
        )
        has_pair = bool(upper_bone or lower_bone)
        if stale:
            _reset_bone(armature, upper_bone, baselines)
            _reset_bone(armature, lower_bone, baselines)
            _reset_bone(armature, legacy_bone, baselines)
            _apply_shape_key(
                mesh, getattr(scene, f"puppetvmc_face_blink_{suffix}_key"), 0.0
            )
        elif has_pair:
            _apply_eyelid(
                armature, upper_bone, value,
                scene.puppetvmc_face_eyelid_upper_invert,
                scene, baselines,
            )
            _apply_eyelid(
                armature, lower_bone, value,
                scene.puppetvmc_face_eyelid_lower_invert,
                scene, baselines,
            )
        elif legacy_bone:
            _apply_eyelid(
                armature, legacy_bone, value,
                scene.puppetvmc_face_eyelid_invert,
                scene, baselines,
            )
        else:
            _apply_shape_key(
                mesh, getattr(scene, f"puppetvmc_face_blink_{suffix}_key"), value
            )

    for parameter, suffix in (
        ("BrowUp", "up"),
        ("BrowDownLeft", "down_left"),
        ("BrowDownRight", "down_right"),
    ):
        value = None if stale else _get_value(values, f"v2/{parameter}")
        bone_name = getattr(scene, f"puppetvmc_face_brow_{suffix}_bone")
        if bone_name:
            if stale:
                baseline = baselines.get(bone_name)
                pose_bone = (
                    armature.pose.bones.get(bone_name)
                    if armature is not None else None
                )
                if pose_bone is not None and baseline is not None:
                    pose_bone.rotation_mode = 'QUATERNION'
                    pose_bone.rotation_quaternion = baseline.copy()
            else:
                _apply_brow(armature, bone_name, value, scene, baselines)
        else:
            _apply_shape_key(
                mesh, getattr(scene, f"puppetvmc_face_brow_{suffix}_key"),
                0.0 if stale else value,
            )
