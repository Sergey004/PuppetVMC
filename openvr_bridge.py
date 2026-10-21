"""Fingers pulled directly from SteamVR via IVRInput.GetSkeletalBoneData(), no
network — the result goes straight into apply_bone() (same cache /
parent_quaternion conjugation as for the body). NOT TESTED HANDS-ON — if Connect
with the toggle enabled fails with an error, look here first (see HANDOFF.md)."""

import json
import os
import sys
import tempfile
import threading

from mathutils import Vector

from . import state
from .constants import OPENVR_FINGER_BONES
from .bones import apply_bone

# Installed via the "Install pyopenvr" button into this addon's own folder,
# not into Blender's site-packages or the user site-packages — both of those
# turned out unreliable in practice (permission errors, or Blender's bundled
# Python simply not adding the user site-packages dir to sys.path even though
# pip reports the install as successful). Vendoring next to the addon code
# sidesteps all of that.
VENDOR_DIR = os.path.join(os.path.dirname(__file__), "vendor")
if VENDOR_DIR not in sys.path:
    sys.path.insert(0, VENDOR_DIR)

try:
    import openvr
    OPENVR_AVAILABLE = True
except ImportError:
    OPENVR_AVAILABLE = False

_MANIFEST = {
    "actions": [
        {"name": "/actions/main/in/SkeletonLeftHand", "type": "skeleton", "skeleton": "/skeleton/hand/left"},
        {"name": "/actions/main/in/SkeletonRightHand", "type": "skeleton", "skeleton": "/skeleton/hand/right"},
        {"name": "/actions/main/in/RecordToggleLeft", "type": "boolean"},
        {"name": "/actions/main/in/RecordToggleRight", "type": "boolean"},
        {"name": "/actions/main/out/Haptic", "type": "vibration"},
    ],
    "action_sets": [
        {"name": "/actions/main", "usage": "leftright"},
    ],
    "localization": [
        {
            "language_tag": "en_US",
            "/actions/main/in/SkeletonLeftHand": "Left Hand Skeleton",
            "/actions/main/in/SkeletonRightHand": "Right Hand Skeleton",
            "/actions/main/in/RecordToggleLeft": "Toggle Recording (Left Y)",
            "/actions/main/in/RecordToggleRight": "Toggle Recording (Right B)",
            "/actions/main/out/Haptic": "Calibration Confirmation Buzz",
        }
    ],
}


def _write_manifest():
    path = os.path.join(tempfile.gettempdir(), "puppetvmc_openvr_actions.json")
    with open(path, "w") as f:
        json.dump(_MANIFEST, f, indent=2)
    return path


def _poll_hmd_pose():
    """Poll the latest standing-space HMD position off Blender's UI thread."""
    vr_system = state.ovr["system"]
    interval = 1.0 / 60.0
    while not state.ovr["hmd_stop"].is_set():
        try:
            poses = vr_system.getDeviceToAbsoluteTrackingPose(
                openvr.TrackingUniverseStanding, 0.0, None,
            )
            pose = poses[openvr.k_unTrackedDeviceIndex_Hmd]
            position = None
            if pose.bDeviceIsConnected and pose.bPoseIsValid:
                matrix = pose.mDeviceToAbsoluteTracking
                position = (matrix[0][3], matrix[1][3], matrix[2][3])
            with state.ovr["hmd_lock"]:
                state.ovr["hmd_position"] = position
                state.ovr["hmd_error"] = None
        except Exception as exc:
            with state.ovr["hmd_lock"]:
                state.ovr["hmd_position"] = None
                state.ovr["hmd_error"] = str(exc)
            return
        state.ovr["hmd_stop"].wait(interval)


def openvr_start(track_hmd_position=False):
    if not OPENVR_AVAILABLE or state.ovr["input"] is not None:
        return
    openvr.init(openvr.VRApplication_Overlay)
    try:
        vr_system = openvr.VRSystem() if track_hmd_position else None
        vrinput = openvr.VRInput()
        vrinput.setActionManifestPath(_write_manifest())

        action_set_handle = vrinput.getActionSetHandle("/actions/main")
        left_action = vrinput.getActionHandle("/actions/main/in/SkeletonLeftHand")
        right_action = vrinput.getActionHandle("/actions/main/in/SkeletonRightHand")

        active = openvr.VRActiveActionSet_t()
        active.ulActionSet = action_set_handle
        active.ulRestrictedToDevice = openvr.k_ulInvalidInputValueHandle

        record_left = vrinput.getActionHandle("/actions/main/in/RecordToggleLeft")
        record_right = vrinput.getActionHandle("/actions/main/in/RecordToggleRight")
        haptic = vrinput.getActionHandle("/actions/main/out/Haptic")
    except Exception:
        openvr.shutdown()
        raise

    state.ovr["input"] = vrinput
    state.ovr["system"] = vr_system
    state.ovr["action_sets"] = [active]
    state.ovr["left"] = left_action
    state.ovr["right"] = right_action
    state.ovr["record_left"] = record_left
    state.ovr["record_right"] = record_right
    state.ovr["haptic"] = haptic
    if track_hmd_position:
        state.ovr["hmd_stop"].clear()
        state.ovr["hmd_position"] = None
        state.ovr["hmd_error"] = None
        state.ovr["hmd_thread"] = threading.Thread(
            target=_poll_hmd_pose, name="PuppetVMC-HMD", daemon=True,
        )
        state.ovr["hmd_thread"].start()


def openvr_stop():
    hmd_thread = state.ovr.get("hmd_thread")
    if hmd_thread is not None:
        state.ovr["hmd_stop"].set()
        hmd_thread.join(timeout=1.0)
        if hmd_thread.is_alive():
            raise RuntimeError("SteamVR HMD pose polling thread did not stop")
        state.ovr["hmd_thread"] = None
    if state.ovr["input"] is not None:
        try:
            openvr.shutdown()
        except Exception:
            pass
    state.ovr["input"] = None
    state.ovr["system"] = None
    state.ovr["action_sets"] = None
    state.ovr["left"] = None
    state.ovr["right"] = None
    state.ovr["record_left"] = None
    state.ovr["record_right"] = None
    state.ovr["haptic"] = None
    state.ovr["hmd_position"] = None
    state.ovr["hmd_origin"] = None
    state.ovr["hmd_root_base"] = None


def haptic_pulse(duration=0.15, frequency=150.0, amplitude=1.0):
    """Short vibration on whatever device the action set is bound to — used
    to confirm a calibration countdown started/fired while the headset makes
    the screen unusable. NOT hand-tested: exact pyopenvr
    triggerHapticVibrationAction() argument order/names may not match this
    installed version. No-ops silently if OpenVR isn't running, so it's safe
    to call unconditionally."""
    vrinput = state.ovr.get("input")
    haptic = state.ovr.get("haptic")
    if vrinput is None or haptic is None:
        return
    try:
        vrinput.triggerHapticVibrationAction(
            haptic, 0.0, duration, frequency, amplitude,
            openvr.k_ulInvalidInputValueHandle,
        )
    except Exception:
        pass  # signature mismatch or no device bound — see docstring


def _convert_ovr_position(v):
    # SteamVR: right-handed Y-up. Unity/VMC convention expected by apply_bone:
    # left-handed Y-up. If fingers fly off in the wrong direction after
    # connecting, the signs here are the first thing to check (see HANDOFF.md).
    return (v[0], v[1], -v[2])


def _convert_ovr_rotation(q):
    return (q.x, q.y, -q.z, -q.w)


def apply_hmd_root_position(armature, include_vertical=False, unit_scale=1.0):
    """Apply calibrated HMD translation to the armature's mapped root bone."""
    bone_cache = state.bone_cache
    if bone_cache is None:
        return
    root_bone = bone_cache.get("root_pose_bone")
    root_quaternion_inverse = bone_cache.get("root_quaternion_inverse")
    if root_bone is None or root_quaternion_inverse is None:
        return

    with state.ovr["hmd_lock"]:
        position = state.ovr["hmd_position"]
    if position is None:
        return

    if state.ovr["hmd_origin"] is None:
        state.ovr["hmd_origin"] = position
        state.ovr["hmd_root_base"] = root_bone.location.copy()

    origin = state.ovr["hmd_origin"]
    # OpenVR is right-handed, +Y up, -Z forward; Blender is Z up, +Y forward.
    delta = Vector((position[0] - origin[0],
                    -(position[2] - origin[2]),
                    position[1] - origin[1]))
    delta /= unit_scale
    if not include_vertical:
        delta.z = 0.0
    armature_delta = armature.matrix_world.inverted().to_3x3() @ delta
    root_bone.location = (
        state.ovr["hmd_root_base"] + root_quaternion_inverse @ armature_delta
    )


def poll_record_buttons(context):
    """Reads the two digital button actions and toggles puppetvmc_recording
    on a rising edge (press, not hold). Call once per tick alongside
    poll_openvr_fingers — updateActionState() only needs to run once per
    tick total, so this assumes fingers already called it, or falls back to
    calling it itself if fingers are disabled."""
    vrinput = state.ovr["input"]
    if vrinput is None:
        return
    if not context.scene.puppetvmc_use_openvr_fingers:
        # Fingers didn't already sync this tick — do it ourselves once.
        vrinput.updateActionState(state.ovr["action_sets"])

    for action_key in ("record_left", "record_right"):
        action = state.ovr.get(action_key)
        if action is None:
            continue
        try:
            data = vrinput.getDigitalActionData(action, openvr.k_ulInvalidInputValueHandle)
        except Exception:
            continue
        if data.bState and data.bChanged:  # rising edge only, not held-down repeat
            context.scene.puppetvmc_recording = not context.scene.puppetvmc_recording


def poll_openvr_fingers(armature):
    vrinput = state.ovr["input"]
    if vrinput is None:
        return
    vrinput.updateActionState(state.ovr["action_sets"])

    for hand_action, side in ((state.ovr["left"], "Left"), (state.ovr["right"], "Right")):
        try:
            bone_transforms = vrinput.getSkeletalBoneData(
                hand_action,
                openvr.VRSkeletalTransformSpace_Parent,
                openvr.VRSkeletalMotionRange_WithoutController,
            )
        except Exception:
            continue  # hand isn't tracked right now — skip the frame silently

        for bone_index, suffix in OPENVR_FINGER_BONES.items():
            if bone_index >= len(bone_transforms):
                continue
            t = bone_transforms[bone_index]
            px, py, pz = _convert_ovr_position(t.position.v)
            qx, qy, qz, qw = _convert_ovr_rotation(t.orientation)
            # pass the globally-built bone_cache so apply_bone can conjugate
            apply_bone(state.bone_cache, f"{side}{suffix}", px, py, pz, qx, qy, qz, qw)