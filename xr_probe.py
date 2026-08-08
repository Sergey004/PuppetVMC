"""XR probe operator — introspects the live Blender OpenXR session and dumps
everything it can reach to the system console. Run it AFTER View3D > VR >
Start VR Session, then copy the console output back.

Goal: find out what Blender's built-in XR actually exposes (accessor names,
controller/hand poses, action state). Whether full finger skeletons can be
pulled without a C-extension depends on what shows up here on the user's
Blender + runtime combination.
"""

import bpy


def _section(title):
    print("\n" + "=" * 12 + " " + title + " " + "=" * 12)


def _dump_dir(obj, label):
    _section(label)
    if obj is None:
        print("(None)")
        return
    try:
        names = [n for n in dir(obj) if not n.startswith("__")]
    except Exception as e:
        print(f"dir() failed: {e!r}")
        return
    print(", ".join(names))


def _dump_attr(obj, label, attr):
    _section(f"{label}.{attr}")
    if obj is None:
        print("(owner None)")
        return
    if not hasattr(obj, attr):
        print("(absent)")
        return
    try:
        val = getattr(obj, attr)
    except Exception as e:
        print(f"getattr failed: {e!r}")
        return
    # Callables are tricky: some bpy accessors are methods, some are
    # descriptors. Probe both shapes.
    if callable(val):
        print(f"callable — trying no-arg call")
        try:
            res = val()
            print(f"  -> {res!r}")
        except Exception as e:
            print(f"  no-arg call failed: {e!r}")
            try:
                # Many Blender accessors want a context arg.
                res = val(bpy.context)
                print(f"  with context -> {res!r}")
            except Exception as e2:
                print(f"  with context failed: {e2!r}")
    else:
        print(f"value = {val!r}  (type {type(val).__name__})")


# Known XrSessionState accessors we care about for finger tracking.
# Some of these may not exist on Blender 5.1 — that itself is diagnostic.
_KNOWN_ACCESSORS = [
    "viewer_pose_location", "viewer_pose_rotation",
    "controller_grip0_location", "controller_grip0_rotation",
    "controller_grip1_location", "controller_grip1_rotation",
    "controller_aim0_location", "controller_aim0_rotation",
    "controller_aim1_location", "controller_aim1_rotation",
    "action_poses", "action_states", "action_state",
    "is_running", "supported",
]


class VMCSIMPLE_OT_xr_probe(bpy.types.Operator):
    bl_idname = "vmcsimple.xr_probe"
    bl_label = "XR Probe (dump to console)"
    bl_description = (
        "Introspect the active Blender OpenXR session and write every reachable "
        "field / accessor to the system console. Run after View3D > VR > "
        "Start VR Session. Results go to Window > Toggle System Console."
    )

    def execute(self, context):
        wm = context.window_manager

        _section("Blender version")
        print(bpy.app.version_string)

        # Settings exist even without a running session — action_set_config
        # lives here and is the official path to register extra OpenXR actions
        # (e.g. a hand-tracking pose action).
        settings = wm.xr_session_settings
        _dump_dir(settings, "wm.xr_session_settings")
        for attr in ("reference_space", "base_pose_type", "base_pose_location",
                     "base_pose_angle", "action_set_config",
                     "default_bindings", "enabled_extensions"):
            _dump_attr(settings, "settings", attr)
        # action_set_config / default_bindings are often collections — dump
        # their entries' RNA properties so we can see how to populate them.
        for coll_attr in ("action_set_config", "default_bindings"):
            try:
                coll = getattr(settings, coll_attr)
            except Exception:
                continue
            _section(f"settings.{coll_attr} contents")
            try:
                n = len(coll)
            except Exception as e:
                print(f"len failed: {e!r}")
                continue
            print(f"len = {n}")
            if n:
                first = coll[0]
                try:
                    print(f"first item RNA props: {[p.identifier for p in first.bl_rna.properties if p.identifier != 'rna_type']}")
                except Exception as e:
                    print(f"bl_rna probe failed: {e!r}")

        # The live session state — this is only meaningful while the session
        # is running. Probe accessors both as descriptors and callables.
        xr = wm.xr_session_state
        _dump_dir(xr, "wm.xr_session_state")
        _section("xr_session_state.bl_rna properties")
        try:
            for p in xr.bl_rna.properties:
                if p.identifier == "rna_type":
                    continue
                flags = []
                if p.is_readonly:
                    flags.append("ro")
                # Some pose accessors are functions on the RNA but exposed
                # as methods; flag them so we know to call with context.
                if p.type == 'COLLECTION':
                    flags.append("collection")
                if p.type == 'FLOAT_VECTOR':
                    flags.append("vec3")
                print(f"  {p.identifier:30s} type={p.type:12s} {' '.join(flags)}")
        except Exception as e:
            print(f"bl_rna walk failed: {e!r}")

        for attr in _KNOWN_ACCESSORS:
            _dump_attr(xr, "xr_state", attr)

        _section("done")
        self.report({'INFO'}, "XR probe written to system console")
        return {'FINISHED'}


classes = (
    VMCSIMPLE_OT_xr_probe,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
