"""Main tick, called from the Connect operator's modal timer."""

from . import state
from .bones import apply_bone, get_bone_map  # get_bone_map kept for panel UI; process_queue uses state.bone_cache
from .cameras import update_head_camera, update_xr_camera
from .openvr_bridge import poll_openvr_fingers, poll_record_buttons
from .constants import ROOT_HUMANOID_BONE


def _record_frame(context, armature, bone_map):
    """Advances the timeline by one frame and keyframes every mapped bone.
    Plain keyframe_insert() only — avoids the action.groups.new() bug that
    breaks VMC4B on Blender 5.1's new Action API."""
    scene = context.scene
    frame = scene.frame_current
    for vmc_name, bone_name in bone_map.items():
        pbone = armature.pose.bones.get(bone_name)
        if not pbone:
            continue
        pbone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
        if vmc_name == ROOT_HUMANOID_BONE:
            pbone.keyframe_insert(data_path="location", frame=frame)
    scene.frame_set(frame + 1)


def process_queue(context):
    if state.receiver is None:
        return

    # --- Delayed calibration: fires once the countdown started via
    # puppetvmc.start_calibration_timer has elapsed. Lets you trigger it
    # BEFORE raising your arms into T-pose instead of needing a free hand
    # while already posed.
    if state.calibration["countdown_end"] is not None:
        import time
        if time.time() >= state.calibration["countdown_end"]:
            state.calibration["origin"] = None
            state.calibration["countdown_end"] = None
            from .openvr_bridge import haptic_pulse
            haptic_pulse()

    armature = context.scene.puppetvmc_armature
    bone_map = get_bone_map(context)

    while not state.receiver.queue.empty():
        item = state.receiver.queue.get()
        address = item.get("address")
        args = item.get("args", [])
        timestamp = item.get("timestamp")
        # VMC4B-style recording: store raw packets
        if context.scene.puppetvmc_recording:
            if address and address.startswith("/VMC/Ext/"):
                state.recorder_queue.append(item)
        # Apply bone data
        if armature and address == "/VMC/Ext/Bone/Pos" and len(args) >= 8:
            name, px, py, pz, qx, qy, qz, qw = args[:8]
            apply_bone(state.bone_cache, name, px, py, pz, qx, qy, qz, qw)

    if context.scene.puppetvmc_use_openvr_fingers and armature:
        poll_openvr_fingers(armature)

    poll_record_buttons(context)

    if armature:
        update_head_camera(context, armature)
    update_xr_camera(context)