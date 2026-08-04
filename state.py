"""Shared mutable state — a single source of truth so different modules
(OSC receiver, OpenVR bridge, operators) see the same data.
Mutate via attributes/dict contents, not by reassigning module-level
variables directly from other files (plain reassignment doesn't propagate
across modules — attribute assignment on the module object does)."""

receiver = None  # OSCReceiver instance, see osc.py — reassigned by operators via state.receiver = ...

calibration = {
    "origin": None,     # calibration point (raw VMC position) for root motion
    "rotations": {},    # vmc_name -> Quaternion, the "zero" captured at calibration time (T-pose)
}

ovr = {"input": None, "action_sets": None, "left": None, "right": None}
