"""Shared mutable state — a single source of truth so different modules
(OSC receiver, OpenVR bridge, operators) see the same data.
Mutate via attributes/dict contents, not by reassigning module-level
variables directly from other files (plain reassignment doesn't propagate
across modules — attribute assignment on the module object does)."""

receiver = None  # OSCReceiver instance, see osc.py — reassigned by operators via state.receiver = ...
face_receiver = None  # Separate OSCReceiver for VRCFaceTracking avatar parameters.
face_tracking_values = {}
face_tracking_last_received = None
face_eye_baselines = {}

bone_cache = None  # built once at Connect time via build_bone_cache(); holds
# parent_quaternion conjugation data + root bookkeeping (see bones.py::build_bone_cache).

calibration = {
    "origin": None,     # calibration point (raw VMC position) for root motion.
    # Rotations baseline was removed — parent_quaternion conjugation already
    # absorbs rest-pose mismatch; Calibrate resets only origin below.
    "countdown_end": None,  # unix timestamp (time.time()) when a delayed
    # calibration should fire; None means no countdown is pending. Used so
    # you can trigger calibration BEFORE raising your arms into T-pose
    # instead of needing a free hand to press something while already posed.
}

from threading import Event, Lock

ovr = {
    "input": None,
    "system": None,
    "action_sets": None,
    "left": None,
    "right": None,
    "hmd_stop": Event(),
    "hmd_lock": Lock(),
    "hmd_thread": None,
    "hmd_position": None,
    "hmd_error": None,
    "hmd_origin": None,
    "hmd_root_base": None,
}

# Recorder state for VMC4B-style timestamped recording
from collections import deque
recorder_queue = deque()  # deque of raw packets {timestamp, address, args}
recording_start_time = None
recording_start_frame = None
recording_fps = None  # FPS announced by the animation emulator, if provided.
face_recording_targets = ()
face_recording_start_time = None
face_recording_last_frame = None

# Local Unity .anim player. It is only sampled when the user starts playback;
# the normal /VMC/Ext receiver path remains independent.
animation_clip = None
animation_started_at = None
animation_elapsed = 0.0