import bpy

from .openvr_bridge import OPENVR_AVAILABLE


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

        rec_row = layout.row()
        rec_row.operator("puppetvmc.toggle_record",
                          depress=scene.puppetvmc_recording,
                          text="Stop Recording" if scene.puppetvmc_recording else "Start Recording")

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
