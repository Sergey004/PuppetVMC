# PuppetVMC — agent notes

Blender 5.1 add-on: receives the VMC protocol (SlimeVR → UDP/OSC) and applies
bone transforms to a user-chosen armature. Optional finger tracking pulls
skeleton data directly from SteamVR via OpenVR, bypassing Blender's XR API
(which exposes only head + controller poses, no hand skeleton). Read
`HANDOFF.md` first — it's the densest source of design context and pitfalls.

## Non-obvious facts

- **Never run in real Blender yet.** Every fix attempt is the first real
  launch. `py_compile` was used for syntax checking only — it does not
  execute bpy calls. Expect AttributeError / bpy API mismatches on first run.
- **No hardcoded bone names.** VMC standard slot names live in
  `constants.py::VMC_BONE_SLOTS`; the user maps them to their rig's bone
  names via the UI ("Bind override"). Don't add bone-name assumptions.
- **`mathutils` and `bpy` are Blender-only.** Any unit test or import check
  running outside Blender needs stub modules (the existing checks used
  fake `bpy`/`mathutils`/`openvr` stubs).
- **Threading rule (hard).** `osc.py::OSCReceiver` runs on a daemon thread
  and only pushes parsed tuples onto a queue. It must **never** touch
  `bpy.data` — Blender's API is main-thread-only. All application happens in
  `loop.py::process_queue`, ticked by a modal timer operator
  (`operators.py::VMCSIMPLE_OT_connect.modal`).
- **Shared state lives in `state.py`.** Mutate via attributes/dict contents,
  not module reassignment (plain `state.receiver = x` from another module
  works because it's attribute assignment on the module object; reassigning
  the dict *inside* would not propagate).
- **Coordinate convention.** `convert.py` flips Unity (Y-up, left-handed) →
  Blender (Z-up, right-handed): position `(-px, -pz, py)`, rotation
  `(qw, qx, qz, -qy)`. OpenVR uses SteamVR (RH, Y-up) → Unity LH flip is in
  `openvr_bridge.py::_convert_ovr_*` and is **empirical/untested** — if
  fingers fly off or mirror, fix signs there first.
- **Root motion is delta-based.** `bones.py::apply_bone` for
  `ROOT_HUMANOID_BONE` ("Hips") uses delta from the first position after
  Calibrate, not absolute coords. If the model doesn't move, verify SlimeVR
  is actually sending changing numbers for the Hips slot before debugging
  code.
- **Calibrate resets everything at once.** `state.calibration["rotations"]
  = {}` clears both body and fingers to a single T-pose baseline.

## Module graph (acyclic)

```
state ← osc/convert ← bones ← cameras/openvr_bridge ← loop ← operators/panel
__init__.py registers properties → operators → panel; openvr_stop on unregister
```

## Verification you can run outside Blender

No formal test suite. To sanity-check syntax + import graph without Blender:

```bash
python -m py_compile *.py
```

Full functional testing requires launching Blender with the add-on enabled
and a live SlimeVR + SteamVR source.

## Operating the add-on

1. Blender → Preferences → Add-ons → enable "PuppetVMC" (folder must be on
   the Blender scripts/addons path; `bl_info["name"]` ≠ folder name, that's
   fine).
2. N-panel → **VMC** tab → pick Armature, set Port (default `39539`, must
   match SlimeVR Server's VMC output port).
3. Bind (override) → "Refresh Bone List" → map each VMC slot to a bone
   of your rig. Re-running it only adds missing slots, never destroys
   existing mappings.
4. Connect → **Calibrate** while standing in T-pose.

## OpenVR fingers — known fragile spots

- Requires `pip install openvr` into Blender's own Python; the UI "Install
  pyopenvr" button uses `--user`. **Blender must be restarted** after
  install — imports are cached at add-on load.
- Exact `pyopenvr` attribute names (`VRApplication_Overlay`,
  `VRSkeletalTransformSpace_Parent`, `VRActiveActionSet_t`,
  `k_ulInvalidInputValueHandle`) are unverified against the installed
  version. On AttributeError, run
  `python -c "import openvr; print(dir(openvr))"` against Blender's Python.
- Requires SteamVR running and a hand actually tracked (Quest 3 via Virtual
  Desktop emulates Index Knuckles skeletal input — confirmed working path).
- Thumb has no real Intermediate in OpenVR; mapping to Unity slots is
  approximate (see `constants.py::OPENVR_FINGER_BONES` comment).
- A failure to poll a hand is swallowed silently (`except Exception:
  continue`) — a missing/untracked hand is not a bug.

## Debugging order when nothing moves

1. Check raw OSC traffic with an external OSC monitor (e.g. Protokol) on the
   same port — distinguishes "SlimeVR isn't sending" from "Blender isn't
   applying". Do this **before** touching code.
2. Check the Bind map is non-empty and targets real pose bones.
3. Only then inspect `loop.py` / `bones.py`.
