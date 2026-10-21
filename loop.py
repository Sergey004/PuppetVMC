"""Main tick, called from the Connect operator's modal timer."""

import time

from . import state
from .bones import apply_bone, apply_local_bone, get_bone_map  # get_bone_map kept for panel UI; process_queue uses state.bone_cache
from .cameras import update_head_camera, update_xr_camera
from .openvr_bridge import poll_openvr_fingers, poll_record_buttons
from .constants import ROOT_HUMANOID_BONE
from .face_tracking import FACE_TRACKING_TIMEOUT, apply_face_tracking


def _set_recording_from_osc(context, enabled, args=None):
    """Start or stop the Blender recorder from an emulator control packet."""
    if context.scene.puppetvmc_recording == enabled:
        return

    from . import recorder
    import time

    if enabled:
        context.scene.puppetvmc_recording = True
        recorder.start_recording(context)
        state.recording_start_time = time.time()
        state.recording_fps = None
        if args:
            try:
                announced_fps = float(args[0])
                if announced_fps > 0.0:
                    state.recording_fps = announced_fps
            except (TypeError, ValueError):
                pass
    else:
        recorder.bake_recording(context)
        context.scene.puppetvmc_recording = False


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
    if (state.receiver is None and state.face_receiver is None
            and not context.scene.puppetvmc_animation_playing):
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
    animation_muscles = {}
    animation_fingers = {}

    while state.receiver is not None and not state.receiver.queue.empty():
        item = state.receiver.queue.get()
        address = item.get("address")
        args = item.get("args", [])
        timestamp = item.get("timestamp")
        if address == "/PuppetVMC/Record/Start":
            _set_recording_from_osc(context, True, args)
            continue
        if address == "/PuppetVMC/Record/Stop":
            _set_recording_from_osc(context, False)
            continue
        if address == "/PuppetVMC/Anim/Muscle" and len(args) >= 2:
            if context.scene.puppetvmc_recording:
                state.recorder_queue.append(item)
            animation_muscles[str(args[0])] = float(args[1])
            continue
        if address == "/PuppetVMC/Anim/Finger" and len(args) >= 3:
            if context.scene.puppetvmc_recording:
                state.recorder_queue.append(item)
            animation_fingers[str(args[0])] = (float(args[1]), float(args[2]))
            continue
        # VMC4B-style recording: store raw packets
        if context.scene.puppetvmc_recording:
            if address and (address.startswith("/VMC/Ext/") or
                            address == "/PuppetVMC/Anim/LocalBone/Pos"):
                state.recorder_queue.append(item)
        # Apply bone data
        if armature and address == "/VMC/Ext/Bone/Pos" and len(args) >= 8:
            name, px, py, pz, qx, qy, qz, qw = args[:8]
            apply_bone(state.bone_cache, name, px, py, pz, qx, qy, qz, qw)
        if armature and address == "/PuppetVMC/Anim/LocalBone/Pos" and len(args) >= 5:
            name, qx, qy, qz, qw = args[:5]
            apply_local_bone(state.bone_cache, name, qx, qy, qz, qw)

    while state.face_receiver is not None and not state.face_receiver.queue.empty():
        item = state.face_receiver.queue.get()
        address = item.get("address", "")
        args = item.get("args", [])
        prefix = "/avatar/parameters/"
        if address.startswith(prefix) and args:
            value = args[0]
            if isinstance(value, (int, float, bool)):
                state.face_tracking_values[address[len(prefix):]] = float(value)
                state.face_tracking_last_received = item.get("timestamp")

    if armature and (animation_muscles or animation_fingers):
        from .unity_animation import apply_pose
        apply_pose(state.bone_cache, animation_muscles, animation_fingers)

    if armature and state.face_receiver is not None:
        apply_face_tracking(
            armature,
            context.scene,
            state.face_tracking_values,
            state.face_eye_baselines,
            state.face_tracking_last_received,
        )
        if (state.face_tracking_last_received is not None
                and time.time() - state.face_tracking_last_received > FACE_TRACKING_TIMEOUT):
            state.face_tracking_values.clear()
            state.face_tracking_last_received = None

    if armature and context.scene.puppetvmc_animation_playing and state.animation_clip:
        from .unity_animation import apply_clip
        elapsed = time.perf_counter() - state.animation_started_at
        state.animation_elapsed = elapsed
        apply_clip(state.bone_cache, state.animation_clip, elapsed)

    if context.scene.puppetvmc_use_openvr_fingers and armature:
        poll_openvr_fingers(armature)

    poll_record_buttons(context)

    if armature:
        update_head_camera(context, armature)
    update_xr_camera(context)