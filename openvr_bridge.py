"""Fingers pulled directly from SteamVR via IVRInput.GetSkeletalBoneData(), no
network — the result goes straight into apply_bone() (same calibration /
T-pose baseline as for the body). NOT TESTED HANDS-ON — if Connect with the
toggle enabled fails with an error, look here first (see HANDOFF.md)."""

import json
import os
import tempfile

from . import state
from .constants import OPENVR_FINGER_BONES
from .bones import apply_bone

try:
    import openvr
    OPENVR_AVAILABLE = True
except ImportError:
    OPENVR_AVAILABLE = False


_MANIFEST = {
    "actions": [
        {"name": "/actions/main/in/SkeletonLeftHand", "type": "skeleton", "skeleton": "/skeleton/hand/left"},
        {"name": "/actions/main/in/SkeletonRightHand", "type": "skeleton", "skeleton": "/skeleton/hand/right"},
    ],
    "action_sets": [
        {"name": "/actions/main", "usage": "leftright"},
    ],
    "localization": [
        {
            "language_tag": "en_US",
            "/actions/main/in/SkeletonLeftHand": "Left Hand Skeleton",
            "/actions/main/in/SkeletonRightHand": "Right Hand Skeleton",
        }
    ],
}


def _write_manifest():
    path = os.path.join(tempfile.gettempdir(), "vmcsimple_openvr_actions.json")
    with open(path, "w") as f:
        json.dump(_MANIFEST, f, indent=2)
    return path


def openvr_start():
    if not OPENVR_AVAILABLE or state.ovr["input"] is not None:
        return
    openvr.init(openvr.VRApplication_Overlay)
    vrinput = openvr.VRInput()
    vrinput.setActionManifestPath(_write_manifest())

    action_set_handle = vrinput.getActionSetHandle("/actions/main")
    left_action = vrinput.getActionHandle("/actions/main/in/SkeletonLeftHand")
    right_action = vrinput.getActionHandle("/actions/main/in/SkeletonRightHand")

    active = openvr.VRActiveActionSet_t()
    active.ulActionSet = action_set_handle
    active.ulRestrictedToDevice = openvr.k_ulInvalidInputValueHandle

    state.ovr["input"] = vrinput
    state.ovr["action_sets"] = [active]
    state.ovr["left"] = left_action
    state.ovr["right"] = right_action


def openvr_stop():
    if state.ovr["input"] is not None:
        try:
            openvr.shutdown()
        except Exception:
            pass
    state.ovr["input"] = None
    state.ovr["action_sets"] = None


def _convert_ovr_position(v):
    # SteamVR: right-handed Y-up. Unity/VMC convention expected by apply_bone:
    # left-handed Y-up. If fingers fly off in the wrong direction after
    # connecting, the signs here are the first thing to check (see HANDOFF.md).
    return (v[0], v[1], -v[2])


def _convert_ovr_rotation(q):
    return (q.x, q.y, -q.z, -q.w)


def poll_openvr_fingers(armature, bone_map):
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
            apply_bone(armature, bone_map, f"{side}{suffix}", px, py, pz, qx, qy, qz, qw)
