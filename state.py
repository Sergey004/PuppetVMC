"""Shared mutable state — a single source of truth so different modules
(OSC receiver, OpenVR bridge, operators) see the same data.
Mutate via attributes/dict contents, not by reassigning module-level
variables directly from other files (plain reassignment doesn't propagate
across modules — attribute assignment on the module object does)."""

receiver = None  # OSCReceiver instance, see osc.py — reassigned by operators via state.receiver = ...

bone_cache = None  # built once at Connect time via build_bone_cache(); holds
# parent_quaternion conjugation data + root bookkeeping (see bones.py::build_bone_cache).

calibration = {
    "origin": None,     # calibration point (raw VMC position) for root motion.
    # Rotations baseline was removed — parent_quaternion conjugation already
    # absorbs rest-pose mismatch; Calibrate resets only origin below.
}

ovr = {"input": None, "action_sets": None, "left": None, "right": None}