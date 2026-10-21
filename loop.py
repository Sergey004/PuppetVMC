"""Main tick, called from the Connect operator's modal timer."""

import time
from queue import Empty

from . import state
from .bones import apply_bone, apply_local_bone
from .cameras import update_head_camera, update_xr_camera
from .openvr_bridge import (
    apply_hmd_root_position,
    poll_openvr_fingers,
    poll_record_buttons,
)
from .constants import ROOT_HUMANOID_BONE
from .face_tracking import FACE_TRACKING_TIMEOUT, apply_face_tracking

_MAX_QUEUED_EVENTS_PER_TICK = 2048


def _set_recording_from_osc(context, enabled, args=None):
    """Start or stop the Blender recorder from an emulator control packet."""
    if context.scene.puppetvmc_recording == enabled:
        return

    from . import recorder
    import time

    if enabled:
        context.scene.puppetvmc_recording = True
        if state.receiver is not None:
            state.receiver.recording = True
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
        if state.receiver is not None:
            state.receiver.recording = False
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
    scene = context.scene
    if (state.receiver is None and state.face_receiver is None
            and not scene.puppetvmc_animation_playing):
        return

    # --- Delayed calibration: fires once the countdown started via
    # puppetvmc.start_calibration_timer has elapsed. Lets you trigger it
    # BEFORE raising your arms into T-pose instead of needing a free hand
    # while already posed.
    if state.calibration["countdown_end"] is not None:
        if time.time() >= state.calibration["countdown_end"]:
            state.calibration["origin"] = None
            state.ovr["hmd_origin"] = None
            state.calibration["countdown_end"] = None
            from .openvr_bridge import haptic_pulse
            haptic_pulse()

    armature = scene.puppetvmc_armature
    animation_muscles = {}
    animation_fingers = {}
    receiver = state.receiver
    event_queue = receiver.queue if receiver is not None else None
    face_tracking_updated = False
    if receiver is not None:
        receiver.recording = scene.puppetvmc_recording

    events_processed = 0
    while (event_queue is not None
           and events_processed < _MAX_QUEUED_EVENTS_PER_TICK):
        try:
            item = event_queue.get_nowait()
        except Empty:
            break
        events_processed += 1
        address = item["address"]
        args = item["args"]
        if address == "/PuppetVMC/Record/Start":
            _set_recording_from_osc(context, True, args)
            continue
        if address == "/PuppetVMC/Record/Stop":
            _set_recording_from_osc(context, False)
            continue
        if address == "/PuppetVMC/Anim/Muscle" and len(args) >= 2:
            if scene.puppetvmc_recording:
                state.recorder_queue.append(item)
            animation_muscles[str(args[0])] = float(args[1])
            continue
        if address == "/PuppetVMC/Anim/Finger" and len(args) >= 3:
            if scene.puppetvmc_recording:
                state.recorder_queue.append(item)
            animation_fingers[str(args[0])] = (float(args[1]), float(args[2]))
            continue
        # Lossless source packets are queued only while the receiver is recording.
        if scene.puppetvmc_recording:
            if address and (address.startswith("/VMC/Ext/") or
                            address == "/PuppetVMC/Anim/LocalBone/Pos"):
                state.recorder_queue.append(item)

    # The OSC thread coalesces repeated samples before they enter the UI loop.
    if receiver is not None:
        latest_poses = receiver.take_latest()
        if armature:
            for key, (_, args) in latest_poses.items():
                if key[0] == "bone":
                    name, px, py, pz, qx, qy, qz, qw = args[:8]
                    apply_bone(state.bone_cache, name, px, py, pz, qx, qy, qz, qw)
                elif key[0] == "local_bone":
                    name, qx, qy, qz, qw = args[:5]
                    apply_local_bone(state.bone_cache, name, qx, qy, qz, qw)

    if state.face_receiver is not None:
        for name, (timestamp, value) in state.face_receiver.take_latest().items():
            value = float(value)
            if state.face_tracking_values.get(name) != value:
                state.face_tracking_values[name] = value
                face_tracking_updated = True
            state.face_tracking_last_received = max(
                state.face_tracking_last_received or 0.0,
                timestamp,
            )

    if armature and (animation_muscles or animation_fingers):
        from .unity_animation import apply_pose
        apply_pose(state.bone_cache, animation_muscles, animation_fingers)

    face_tracking_expired = (
        state.face_tracking_last_received is not None
        and time.time() - state.face_tracking_last_received > FACE_TRACKING_TIMEOUT
    )
    if (armature and state.face_receiver is not None
            and (face_tracking_updated or face_tracking_expired)):
        apply_face_tracking(
            armature,
            scene,
            state.face_tracking_values,
            state.face_eye_baselines,
            state.face_tracking_last_received,
        )
        if face_tracking_expired:
            state.face_tracking_values.clear()
            state.face_tracking_last_received = None

    if armature and scene.puppetvmc_animation_playing and state.animation_clip:
        from .unity_animation import apply_clip
        elapsed = time.perf_counter() - state.animation_started_at
        state.animation_elapsed = elapsed
        apply_clip(state.bone_cache, state.animation_clip, elapsed)

    if scene.puppetvmc_use_openvr_fingers and armature:
        poll_openvr_fingers(armature)
    if scene.puppetvmc_use_openvr_hmd_position and armature:
        apply_hmd_root_position(
            armature,
            include_vertical=scene.puppetvmc_openvr_hmd_vertical,
            unit_scale=scene.unit_settings.scale_length,
        )

    poll_record_buttons(context)

    if armature and scene.puppetvmc_headcam:
        update_head_camera(context, armature)
    if scene.puppetvmc_xr_camera:
        update_xr_camera(context)