import bpy

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


classes = (
    PUPPETVMC_PT_panel,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
