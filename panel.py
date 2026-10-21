import time

import bpy

from . import state
from .openvr_bridge import OPENVR_AVAILABLE
from .bones import get_bone_map_conflicts


class PUPPETVMC_PT_panel(bpy.types.Panel):
    bl_label = "PuppetVMC"
    bl_idname = "PUPPETVMC_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "VMC"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        armature = scene.puppetvmc_armature

        # --- Connection ---
        layout.prop(scene, "puppetvmc_armature")
        layout.prop(scene, "puppetvmc_address")
        layout.prop(scene, "puppetvmc_port")
        row = layout.row()
        if scene.puppetvmc_running:
            row.operator("puppetvmc.disconnect")
        else:
            row.operator("puppetvmc.connect")
        layout.operator("puppetvmc.recalibrate")
        layout.operator("puppetvmc.force_t_pose")
        calib_row = layout.row(align=True)
        calib_row.prop(scene, "puppetvmc_calib_delay", text="Delay (s)")
        calib_row.operator("puppetvmc.start_calibration_timer", text="Calibrate in Ns")

        rec_row = layout.row()
        rec_row.operator("puppetvmc.toggle_record",
                          depress=scene.puppetvmc_recording,
                          text="Stop Recording" if scene.puppetvmc_recording else "Start Recording")

        # --- Local Unity animation player ---
        animation_box = layout.box()
        animation_box.label(text="Unity Animation (.anim) [WIP]")
        animation_box.prop(scene, "puppetvmc_animation_file", text="File")
        animation_box.prop(scene, "puppetvmc_animation_use_muscles")
        animation_row = animation_box.row(align=True)
        animation_row.operator("puppetvmc.load_animation", text="Import")
        animation_row.operator("puppetvmc.bake_animation", text="Bake to Timeline")
        animation_row.operator(
            "puppetvmc.play_animation",
            text="Playing" if scene.puppetvmc_animation_playing else "Play",
            depress=scene.puppetvmc_animation_playing,
        )
        animation_row.operator("puppetvmc.stop_animation", text="Stop")

        # --- Avatar Bind (Unity-style bone mapping) ---
        box = layout.box()
        box.label(text="Avatar Bind (Unity-style)")
        box.operator("puppetvmc.init_bone_map")
        for item in scene.puppetvmc_bone_map:
            row = box.row()
            row.label(text=item.vmc_name)
            if armature:
                row.prop_search(item, "bone_name", armature.pose, "bones", text="")
            else:
                row.prop(item, "bone_name", text="")
        conflicts = get_bone_map_conflicts(context)
        if conflicts:
            box.label(text="Duplicate Bind targets: fix before Play/Bake", icon='ERROR')
            for bone_name, vmc_names in conflicts.items():
                box.label(text=f"{bone_name}: {', '.join(vmc_names)}", icon='ERROR')

        # --- Head camera ---
        box2 = layout.box()
        box2.label(text="Head camera (follows bone + offset + live rotation)")
        box2.prop(scene, "puppetvmc_headcam")
        if scene.puppetvmc_headcam and armature:
            box2.prop_search(
                scene, "puppetvmc_headcam_bone",
                armature.pose, "bones", text="Bone"
            )
            box2.prop(scene, "puppetvmc_headcam_offset_loc", text="Offset Loc")
            box2.prop(scene, "puppetvmc_headcam_offset_rot", text="Offset Rot")
            box2.prop(scene, "puppetvmc_headcam_manual_rot", text="Manual Rot")

        # --- XR camera ---
        box3 = layout.box()
        box3.label(text="XR camera (real headset, or mirror head)")
        box3.prop(scene, "puppetvmc_xr_camera")
        if scene.puppetvmc_xr_camera:
            box3.prop(scene, "puppetvmc_xr_follow_head")
            box3.prop(scene, "puppetvmc_xr_offset_loc", text="Offset Loc")
            box3.prop(scene, "puppetvmc_xr_offset_rot", text="Offset Rot")
            box3.prop(scene, "puppetvmc_xr_manual_rot", text="Manual Rot")
        box3.operator("puppetvmc.xr_probe")

        # --- OpenVR fingers ---
        box4 = layout.box()
        box4.label(text="Fingers (SteamVR / OpenVR)")
        if OPENVR_AVAILABLE:
            box4.prop(scene, "puppetvmc_use_openvr_fingers")
        else:
            box4.label(text="openvr module not installed", icon='ERROR')
            box4.operator("puppetvmc.install_openvr")

        # --- VRCFaceTracking OSC parameters ---
        face_box = layout.box()
        face_box.label(text="Face tracking (VRCFaceTracking)")
        face_box.prop(scene, "puppetvmc_face_tracking_enabled")
        if scene.puppetvmc_face_tracking_enabled:
            face_box.prop(scene, "puppetvmc_face_tracking_port")
            if state.face_receiver is None:
                face_box.label(text="Connect to start the VRCFT listener")
            elif not state.face_tracking_values:
                face_box.label(text="Waiting for /avatar/parameters/... OSC")
            else:
                values = sorted(state.face_tracking_values.items())
                face_box.label(text=f"Received parameters: {len(values)}")
                age = max(0.0, time.time() - state.face_tracking_last_received)
                face_box.label(
                    text="Live" if age < 1.0 else f"Last update: {age:.1f}s ago"
                )
                for name, value in values[:12]:
                    face_box.label(text=f"{name}: {value:.3f}")
                if len(values) > 12:
                    face_box.label(text=f"... and {len(values) - 12} more")

            eye_box = face_box.box()
            eye_box.label(text="Eye gaze (v2/EyeLeftX/Y and EyeRightX/Y)")
            if armature:
                eye_box.prop_search(
                    scene, "puppetvmc_face_left_eye_bone",
                    armature.pose, "bones", text="Left Eye",
                )
                eye_box.prop_search(
                    scene, "puppetvmc_face_right_eye_bone",
                    armature.pose, "bones", text="Right Eye",
                )
            else:
                eye_box.label(text="Select an armature to map eye bones")
            eye_box.prop(scene, "puppetvmc_face_eye_max_angle")
            row = eye_box.row(align=True)
            row.prop(scene, "puppetvmc_face_eye_invert_horizontal")
            row.prop(scene, "puppetvmc_face_eye_invert_vertical")

            shape_box = face_box.box()
            shape_box.label(text="Eyelids and optional brows")
            if armature:
                shape_box.prop_search(
                    scene, "puppetvmc_face_eyelid_left_bone",
                    armature.pose, "bones", text="Left Eyelid Bone (optional)",
                )
                shape_box.prop_search(
                    scene, "puppetvmc_face_eyelid_right_bone",
                    armature.pose, "bones", text="Right Eyelid Bone (optional)",
                )
                shape_box.prop(scene, "puppetvmc_face_eyelid_max_angle")
                shape_box.prop(scene, "puppetvmc_face_eyelid_invert")
            shape_box.prop(scene, "puppetvmc_face_mesh")
            mesh = scene.puppetvmc_face_mesh
            if mesh and mesh.data.shape_keys:
                keys = mesh.data.shape_keys
                shape_box.label(text="Map blink to either a bone or shape key")
                shape_box.prop_search(
                    scene, "puppetvmc_face_blink_left_key", keys, "key_blocks",
                    text="Left Blink",
                )
                shape_box.prop_search(
                    scene, "puppetvmc_face_blink_right_key", keys, "key_blocks",
                    text="Right Blink",
                )
                shape_box.separator()
                shape_box.prop_search(
                    scene, "puppetvmc_face_brow_up_key", keys, "key_blocks",
                    text="Brow Up (optional)",
                )
                shape_box.prop_search(
                    scene, "puppetvmc_face_brow_down_left_key", keys,
                    "key_blocks", text="Left Brow Down (optional)",
                )
                shape_box.prop_search(
                    scene, "puppetvmc_face_brow_down_right_key", keys,
                    "key_blocks", text="Right Brow Down (optional)",
                )
            else:
                shape_box.label(text="Choose a mesh with shape keys")
            face_box.label(
                text="Disconnect/reconnect after changing eye-bone mappings"
            )


classes = (
    PUPPETVMC_PT_panel,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
