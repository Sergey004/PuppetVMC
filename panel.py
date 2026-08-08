import bpy

from .openvr_bridge import OPENVR_AVAILABLE


class VMCSIMPLE_PT_panel(bpy.types.Panel):
    bl_label = "PuppetVMC"
    bl_idname = "VMCSIMPLE_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "VMC"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        armature = scene.vmcsimple_armature

        # --- Connection ---
        layout.prop(scene, "vmcsimple_armature")
        layout.prop(scene, "vmcsimple_port")
        row = layout.row()
        if scene.vmcsimple_running:
            row.operator("vmcsimple.disconnect")
        else:
            row.operator("vmcsimple.connect")
        layout.operator("vmcsimple.recalibrate")

        rec_row = layout.row()
        rec_row.operator("vmcsimple.toggle_record",
                          depress=scene.vmcsimple_recording,
                          text="Stop Recording" if scene.vmcsimple_recording else "Start Recording")

        # --- Avatar Bind (Unity-style bone mapping) ---
        box = layout.box()
        box.label(text="Avatar Bind (Unity-style)")
        box.operator("vmcsimple.init_bone_map")
        for item in scene.vmcsimple_bone_map:
            row = box.row()
            row.label(text=item.vmc_name)
            if armature:
                row.prop_search(item, "bone_name", armature.pose, "bones", text="")
            else:
                row.prop(item, "bone_name", text="")

        # --- Head camera ---
        box2 = layout.box()
        box2.label(text="Head camera (follows bone + offset + live rotation)")
        box2.prop(scene, "vmcsimple_headcam")
        if scene.vmcsimple_headcam and armature:
            box2.prop_search(
                scene, "vmcsimple_headcam_bone",
                armature.pose, "bones", text="Bone"
            )
            box2.prop(scene, "vmcsimple_headcam_offset_loc", text="Offset Loc")
            box2.prop(scene, "vmcsimple_headcam_offset_rot", text="Offset Rot")
            box2.prop(scene, "vmcsimple_headcam_manual_rot", text="Manual Rot")

        # --- XR camera ---
        box3 = layout.box()
        box3.label(text="XR camera (real headset, or mirror head)")
        box3.prop(scene, "vmcsimple_xr_camera")
        if scene.vmcsimple_xr_camera:
            box3.prop(scene, "vmcsimple_xr_follow_head")
            box3.prop(scene, "vmcsimple_xr_offset_loc", text="Offset Loc")
            box3.prop(scene, "vmcsimple_xr_offset_rot", text="Offset Rot")
            box3.prop(scene, "vmcsimple_xr_manual_rot", text="Manual Rot")
        box3.operator("vmcsimple.xr_probe")

        # --- OpenVR fingers ---
        box4 = layout.box()
        box4.label(text="Fingers (SteamVR / OpenVR)")
        if OPENVR_AVAILABLE:
            box4.prop(scene, "vmcsimple_use_openvr_fingers")
        else:
            box4.label(text="openvr module not installed", icon='ERROR')
            box4.operator("vmcsimple.install_openvr")


classes = (
    VMCSIMPLE_PT_panel,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
