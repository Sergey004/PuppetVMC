import math

import bpy

from .constants import RECEIVE_PORT_DEFAULT


def _headcam_update(self, context):
    """Called immediately when any head camera offset slider changes.
    Applies the new offset to the camera even without an active VMC connection."""
    from .cameras import update_head_camera
    armature = context.scene.puppetvmc_armature
    if armature:
        update_head_camera(context, armature)


class PUPPETVMC_BoneMapItem(bpy.types.PropertyGroup):
    vmc_name: bpy.props.StringProperty(name="VMC Bone")
    bone_name: bpy.props.StringProperty(name="Target Bone")


def _poll_armature(self, obj):
    return obj.type == 'ARMATURE'


def _poll_camera(self, obj):
    return obj.type == 'CAMERA'


classes = (
    PUPPETVMC_BoneMapItem,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)

    bpy.types.Scene.puppetvmc_port = bpy.props.IntProperty(
        name="Port", default=RECEIVE_PORT_DEFAULT)
    bpy.types.Scene.puppetvmc_running = bpy.props.BoolProperty(default=False)

    bpy.types.Scene.puppetvmc_armature = bpy.props.PointerProperty(
        type=bpy.types.Object, poll=_poll_armature, name="Armature")

    bpy.types.Scene.puppetvmc_bone_map = bpy.props.CollectionProperty(
        type=PUPPETVMC_BoneMapItem)

    bpy.types.Scene.puppetvmc_headcam = bpy.props.PointerProperty(
        type=bpy.types.Object, poll=_poll_camera, name="Head Camera")
    bpy.types.Scene.puppetvmc_headcam_bone = bpy.props.StringProperty(name="Head Bone")
    bpy.types.Scene.puppetvmc_headcam_offset_loc = bpy.props.FloatVectorProperty(
        name="Offset Location", subtype='TRANSLATION', size=3, default=(0.0, 0.05, 0.0),
        update=_headcam_update)
    bpy.types.Scene.puppetvmc_headcam_offset_rot = bpy.props.FloatVectorProperty(
        name="Offset Rotation", subtype='EULER', unit='ROTATION', size=3,
        default=(math.radians(-90.0), 0.0, 0.0),
        update=_headcam_update)
    # Live-tweakable extra twist added on top of bone + offset every tick.
    bpy.types.Scene.puppetvmc_headcam_manual_rot = bpy.props.FloatVectorProperty(
        name="Manual Rotation", subtype='EULER', unit='ROTATION', size=3,
        default=(0.0, 0.0, 0.0),
        update=_headcam_update)

    bpy.types.Scene.puppetvmc_xr_camera = bpy.props.PointerProperty(
        type=bpy.types.Object, poll=_poll_camera, name="XR Camera")
    bpy.types.Scene.puppetvmc_xr_offset_loc = bpy.props.FloatVectorProperty(
        name="XR Offset Location", subtype='TRANSLATION', size=3, default=(0.0, 0.0, 0.0))
    bpy.types.Scene.puppetvmc_xr_offset_rot = bpy.props.FloatVectorProperty(
        name="XR Offset Rotation", subtype='EULER', unit='ROTATION', size=3,
        default=(0.0, 0.0, 0.0))
    bpy.types.Scene.puppetvmc_xr_manual_rot = bpy.props.FloatVectorProperty(
        name="XR Manual Rotation", subtype='EULER', unit='ROTATION', size=3,
        default=(0.0, 0.0, 0.0))
    # When enabled, the XR camera mirrors the head camera so both share one
    # pose; manual rotation still applies on top.
    bpy.types.Scene.puppetvmc_xr_follow_head = bpy.props.BoolProperty(
        name="XR follows Head", default=False)

    bpy.types.Scene.puppetvmc_use_openvr_fingers = bpy.props.BoolProperty(
        name="Read fingers from SteamVR", default=False)

    bpy.types.Scene.puppetvmc_recording = bpy.props.BoolProperty(
        name="Recording", default=False,
        description="While on, every tick advances the timeline and keyframes all mapped bones")


def unregister():
    del bpy.types.Scene.puppetvmc_port
    del bpy.types.Scene.puppetvmc_running
    del bpy.types.Scene.puppetvmc_armature
    del bpy.types.Scene.puppetvmc_bone_map
    del bpy.types.Scene.puppetvmc_headcam
    del bpy.types.Scene.puppetvmc_headcam_bone
    del bpy.types.Scene.puppetvmc_headcam_offset_loc
    del bpy.types.Scene.puppetvmc_headcam_offset_rot
    del bpy.types.Scene.puppetvmc_headcam_manual_rot
    del bpy.types.Scene.puppetvmc_xr_camera
    del bpy.types.Scene.puppetvmc_xr_offset_loc
    del bpy.types.Scene.puppetvmc_xr_offset_rot
    del bpy.types.Scene.puppetvmc_xr_manual_rot
    del bpy.types.Scene.puppetvmc_xr_follow_head
    del bpy.types.Scene.puppetvmc_use_openvr_fingers
    del bpy.types.Scene.puppetvmc_recording

    for c in reversed(classes):
        bpy.utils.unregister_class(c)
