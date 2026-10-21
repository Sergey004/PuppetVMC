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

- Blender 5.1+.
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
3. Set the **Address** (default `127.0.0.1`, use `0.0.0.0` only if you need
   to receive from another machine — note firewall) and **Port** to match
   SlimeVR Server's VMC output (commonly `39539` or `39540`).
4. Bind (override) → **Refresh Bone List**. This adds a slot for each
   standard VMC bone without touching already-mapped entries.
5. Map each VMC slot to a bone of your rig.
6. Click **Connect**, then stand in a T-pose and click **Calibrate**.

### VRCFaceTracking

Enable **Receive VRCFaceTracking** before clicking **Connect**. PuppetVMC
listens on a separate UDP port (default `9002`) for OSC parameters
and maps eye gaze, eyelids, and optionally brows:

For facial capture without body/FBT input, enable **Face Only (no body
tracking)** at the top of the panel. Choose an armature and/or a face mesh,
connect, then click **Record Facial Expressions**. This mode only opens the
face OSC listener; it does not start the VMC body receiver or SteamVR
tracking. Recording keys the mapped facial bones and shape keys on the
current timeline, advances one frame per add-on timer tick, and creates
separate Face Only actions instead of collecting raw VMC packets. Stop
recording with **Stop Face Recording**; disconnect when finished.

- Map **Left Eye** and **Right Eye** to the corresponding pose bones.
  `v2/EyeLeftX`, `v2/EyeLeftY`, `v2/EyeRightX`, and `v2/EyeRightY` drive
  horizontal/vertical local rotations. **Max Gaze Angle** sets the angle at
  the ends of the normalized input range; use the invert toggles if the rig
  turns the eyes the wrong way. Gaze is applied relative to the eye bones'
  pose when Connect starts, so disconnect/reconnect after changing the bones.
- Choose a mesh with shape keys, then map **Left Blink** and **Right Blink**
  to keys driven by `v2/EyeClosedLeft` and `v2/EyeClosedRight`.
- Brows are optional. In **Brows**, bind **Brow Up Bone**, **Left Brow Down
  Bone**, and **Right Brow Down Bone** to rig bones to drive their local
  rotation from `v2/BrowUp`, `v2/BrowDownLeft`, and `v2/BrowDownRight`.
  Set the rotation axis, maximum angle, and inversion to fit the rig. If a
  brow bone is assigned, it takes priority over that parameter's shape key;
  leave the bone blank to use a mapped brow shape key instead.
- For rigs with eyelid bones instead of blink shape keys, map the **Left/Right
  Upper Eyelid** and **Left/Right Lower Eyelid** bones. Both lids on each eye
  follow that eye's closure parameter; the shared
  `/tracking/eye/EyesClosedAmount` input drives both eyes when separate
  per-eye VRCFT values are unavailable. Use the independent upper/lower
  inversion toggles so the lids rotate toward one another. **Max Eyelid
  Angle** sets the rotation at full closure. Any mapped eyelid bones take
  precedence over that side's blink shape key. Older single-eyelid bone
  mappings remain available as a fallback.

PuppetVMC also accepts VRChat eye-tracking OSC input:
`/tracking/eye/LeftRightPitchYaw` (four angles in degrees: left pitch/yaw,
right pitch/yaw) and `/tracking/eye/EyesClosedAmount` (one shared 0–1
closure value). These can be used instead of VRCFT's avatar-parameter
addresses. Configure the sender to target PuppetVMC's VRCFT OSC port.

VRCFT's default parameter addresses are `/avatar/parameters/v2/<name>`,
for example `/avatar/parameters/v2/EyeLeftX`. The parameter names and
normalized ranges are listed in the
[VRCFaceTracking parameter reference](https://docs.vrcft.io/docs/tutorial-avatars/tutorial-avatars-extras/parameters/parameters).
Avatar parameter prefixes are also supported. The panel shows recently
received values; stale values are reset to neutral after one second.

The VRCFT default OSC output port is `9000`, while `9001` is its OSC input
port. PuppetVMC listens on `9002` by default so it does not conflict with
VRCFT's input socket. Configure an OSC relay to forward VRCFT output to
PuppetVMC's port `9002`; a relay is needed if VRChat must continue receiving
the same tracking parameters. Ensure no other application is bound to the
add-on's receive port.

### Unity animation emulator (WIP\Broken)

`tools/vmc_emulator.py` can load a Unity `.anim` clip and send its sampled
motion to the add-on. Keep the add-on connected on the same UDP port, load an
animation, then press **Play**. The emulator sends these control messages to
the add-on in addition to the normal VMC bone packets:

- `/PuppetVMC/Record/Start` starts raw OSC recording in Blender.
- `/PuppetVMC/Record/Stop` stops recording and bakes the captured packets into
  a Blender Action.

The Start message carries the Unity clip's `m_SampleRate` as its first OSC
argument. The recorder uses that FPS when converting packet timestamps to
Blender frames, so the baked Action keeps the source animation timing.

`Pause` and `Clear Animation` send the stop command. The control packets are
handled on Blender's main timer thread, so they are safe to use with the
existing recorder.

Finger muscle curves such as `LeftHand.Index.1 Stretched` and `Spread` are
converted inside the add-on to the corresponding 30 VMC finger slots. Run
**Refresh Bone List** and map the finger slots
to your armature before playback. The conversion is an approximation of
Unity's Humanoid solver: `Stretched` drives curl and `Spread` drives the
proximal joint's side rotation.

For animation playback, the emulator sends raw values through the private
addresses `/PuppetVMC/Anim/Muscle` and `/PuppetVMC/Anim/Finger`. Their
conversion happens inside the add-on, where the Blender bind map and armature
rest pose are available. Real tracker messages under `/VMC/Ext/` use the
unchanged VMC path.

### Built-in Unity animation player (WIP\Broken)

The add-on can now import and play a Unity `.anim` file directly from the VMC
panel. Select an armature, refresh and fill the bind map, click **Import** in
the **Unity Animation (.anim)** section, then click **Play**. UDP Connect is
not required for local playback: the player owns its own timer and writes
directly to the bound pose bones. Playback is blocked while VMC Connect is
active, so the two sources cannot fight over the same armature. **Stop**
returns control to the armature.

The Humanoid muscle/finger conversion is **WIP**. It is intentionally kept as
an experimental implementation for future Unity Avatar solver compatibility;
it is not expected to match Unity exactly yet.

The importer honors Unity's `m_KeepOriginalOrientation`,
`m_KeepOriginalPositionY`, and `m_KeepOriginalPositionXZ` settings. Use
**Bake to Timeline** to sample the clip at its `m_SampleRate` and create a
normal Blender Action with the current bind map. Humanoid muscle conversion is
marked experimental because Blender does not have Unity's Avatar solver; it
must be enabled explicitly with **Use Humanoid muscles**.

Calibrate now **only resets the root position origin** (`state.calibration["origin"]`).
Rotation baseline is no longer used — the add-on now applies rotations
absolutely using `parent_quaternion` conjugation (matching VMC4B's approach),
which already absorbs the rest-pose mismatch between tracker and bone.

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

### Root movement from SteamVR HMD position

Enable **Use SteamVR HMD position for root** before connecting. PuppetVMC polls
the OpenVR standing-space HMD pose on a dedicated worker thread and uses the
position delta from the first valid sample as locomotion for the mapped rig
root (the top-level ancestor of the VMC **Hips** bind). Blender bone updates
still happen only on Blender's timer thread. Vertical HMD movement is ignored
by default to avoid moving the whole avatar when the user crouches; enable
**Include HMD vertical movement** if desired. Use **Calibrate** to recapture
the HMD position origin. This drives the local Blender rig; it does not send
OSC/VMC packets to another application.

## How it works

- `osc.py` parses single (non-bundle) OSC messages and runs a UDP receiver
  on a daemon thread. The thread only pushes parsed tuples onto a queue —
  it never touches `bpy.data` (Blender's API is main-thread-only).
- `loop.py::process_queue` drains the queue on each tick of a modal timer
  operator (`operators.py::PUPPETVMC_OT_connect`).
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
- SteamVR HMD position is polled on a background thread and only its latest
  sample is applied on the Blender timer. Multiple queued VMC pose packets for
  the same bone and VRCFT parameter are coalesced in the OSC thread to a
  single latest value before Blender sees them; recording still preserves
  every received packet. The UI timer processes at most 2048 queued control
  or recording events per tick to keep large bursts from monopolizing a frame.
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
| Address | `127.0.0.1` | Bind address. Use `0.0.0.0` only if receiving from another machine (may trigger firewall). |
| Port | `39539` | Must match SlimeVR Server's VMC output port. |
| Timer rate | `60.0` Hz | Defined as `FRAME_RATE` in `constants.py`. |
| Root bone slot | `Hips` | Drives root motion; see `ROOT_HUMANOID_BONE`. |
| OpenVR finger bones | 15 indices | Metacarpal and tip bones are skipped — Unity Humanoid has no slots for them. See `OPENVR_FINGER_BONES`. |

## Debugging when nothing moves

1. Check raw OSC traffic with an external OSC monitor (e.g. Protokol) on
   the same port. This separates "SlimeVR isn't sending" from "Blender is
   applying it wrong". Do this before touching code.
   **If SlimeVR Server's "Bundle OSC messages" toggle is ON, you will see
   `#bundle` packets — our parser handles them (osc.py:parse_osc_packet).**
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

MIT
