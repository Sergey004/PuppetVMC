# PuppetVMC

A Blender 5.1 add-on that receives the [VMC protocol][vmc] over UDP/OSC and
applies bone transforms to an armature you choose. It is written for a
custom (non-Unity-Humanoid) rig: no bone names are hardcoded — every VMC
slot is mapped to a bone of your rig through the UI.

[vmc]: https://protocol.vmc.info/

Body motion comes from SlimeVR (which speaks VMC). Finger motion is pulled
directly from SteamVR through OpenVR, bypassing Blender's XR API (which only
exposes head and controller poses, no hand skeleton). Two camera helpers are
included: a head camera that follows a bone with an offset, and an XR
camera driven by a real headset.

## Status

Not yet run inside a real Blender. Syntax and the import graph are checked
with `python -m py_compile`; functional testing requires launching Blender
with a live SlimeVR + SteamVR source. Treat the first launch as the first
real test — expect `AttributeError` or bpy API mismatches.

## Requirements

- Blender 5.1.
- A SlimeVR Server with VMC output enabled, sending to a known UDP port
  (default in this add-on: `39539`).
- For fingers (optional): SteamVR running and a tracked hand that exposes a
  skeleton (Quest 3 via Virtual Desktop emulates Index Knuckles skeletal
  input and is a known-working path).
- For fingers: the `openvr` Python package installed into Blender's own
  Python. There is an in-panel "Install pyopenvr" button that runs
  `pip install --user openvr`; **Blender must be restarted** after install,
  because imports are cached at add-on load.

## Installation

1. Place the `PuppetVMC` folder on Blender's scripts/addons path.
2. Blender → Preferences → Add-ons → enable "PuppetVMC".
3. If you plan to use fingers and `openvr` isn't installed yet, click
   "Install pyopenvr" in the panel, then restart Blender.



## Usage

1. Open the N-panel in the 3D viewport → **VMC** tab.
2. Pick your Armature object.
3. Set the Port to match SlimeVR Server's VMC output (commonly `39539` or
   `39540`).
4. Bind (override) → **Refresh Bone List**. This adds a slot for each
   standard VMC bone without touching already-mapped entries.
5. Map each VMC slot to a bone of your rig.
6. Click **Connect**, then stand in a T-pose and click **Calibrate**.

Calibrate captures the current pose as the baseline (both body and fingers)
and the root position as the origin. From then on, only the **delta** from
the baseline is applied — the rest pose of your bones in Blender does not
need to match how the tracker sits on you.

### Cameras

- **Head camera**: a camera object that follows a chosen bone plus a
  configurable location and rotation offset. Equivalent to parenting the
  camera to the bone, but without a manual parent relationship.
- **XR camera**: a camera object that copies the pose of the active VR
  session's headset. Requires View3D → VR → Start VR Session.

### Fingers from SteamVR

Enable "Read fingers from SteamVR" before connecting. The add-on reads
`IVRInput.GetSkeletalBoneData()` for both hands and routes each finger bone
through the same `apply_bone()` path as the body, so the same calibration
applies. The OpenVR thumb has no real Intermediate bone, so its mapping to
Unity's Proximal/Intermediate/Distal slots is approximate.

## How it works

- `osc.py` parses single (non-bundle) OSC messages and runs a UDP receiver
  on a daemon thread. The thread only pushes parsed tuples onto a queue —
  it never touches `bpy.data` (Blender's API is main-thread-only).
- `loop.py::process_queue` drains the queue on each tick of a modal timer
  operator (`operators.py::VMCSIMPLE_OT_connect`).
- `convert.py` flips Unity (Y-up, left-handed) to Blender (Z-up,
  right-handed): position `(-px, -pz, py)`, rotation `(qw, qx, qz, -qy)`.
- `bones.py::apply_bone` uses a per-bone rotation delta against the
  calibrated T-pose baseline. For the root bone (`Hips`), location is the
  delta from the calibrated origin, not absolute coordinates.
- `openvr_bridge.py` converts SteamVR (right-handed, Y-up) poses to the
  Unity left-handed convention `apply_bone` expects. This conversion is
  empirical and untested — if fingers mirror or fly off, the signs in
  `_convert_ovr_position` / `_convert_ovr_rotation` are the first thing to
  check.
- Shared state lives in `state.py` and is mutated via attributes / dict
  contents (not module reassignment).

Module dependency graph (acyclic):

```
state ← osc/convert ← bones ← cameras/openvr_bridge ← loop ← operators/panel
__init__.py registers properties → operators → panel; openvr_stop on unregister
```

## Configuration

| Setting | Default | Notes |
| --- | --- | --- |
| Port | `39539` | Must match SlimeVR Server's VMC output port. |
| Timer rate | `60.0` Hz | Defined as `FRAME_RATE` in `constants.py`. |
| Root bone slot | `Hips` | Drives root motion; see `ROOT_HUMANOID_BONE`. |
| OpenVR finger bones | 15 indices | Metacarpal and tip bones are skipped — Unity Humanoid has no slots for them. See `OPENVR_FINGER_BONES`. |

## Debugging when nothing moves

1. Check raw OSC traffic with an external OSC monitor (e.g. Protokol) on
   the same port. This separates "SlimeVR isn't sending" from "Blender is
   applying it wrong". Do this before touching code.
2. Check the Bind map is non-empty and targets real pose bones.
3. Only then inspect `loop.py` / `bones.py`.

### OpenVR-specific notes

- The exact `pyopenvr` attribute names (`VRApplication_Overlay`,
  `VRSkeletalTransformSpace_Parent`, `VRActiveActionSet_t`,
  `k_ulInvalidInputValueHandle`) are unverified against the installed
  version. On an `AttributeError`, run
  `python -c "import openvr; print(dir(openvr))"` against Blender's Python.
- A hand that isn't tracked is swallowed silently — a missing or untracked
  hand is not a bug.

## Verifying without Blender

There is no test suite. To sanity-check syntax and the import graph:

```bash
python -m py_compile *.py
```

This does not execute bpy calls and will not catch runtime bpy API
mismatches.

## License

None specified.
