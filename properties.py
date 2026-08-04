import math

import bpy

from .constants import RECEIVE_PORT_DEFAULT


class VMCSIMPLE_BoneMapItem(bpy.types.PropertyGroup):
    vmc_name: bpy.props.StringProperty(name="VMC Bone")
    bone_name: bpy.props.StringProperty(name="Target Bone")


def _poll_armature(self, obj):
    return obj.type == 'ARMATURE'


def _poll_camera(self, obj):
    return obj.type == 'CAMERA'


classes = (
    VMCSIMPLE_BoneMapItem,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)

    bpy.types.Scene.vmcsimple_port = bpy.props.IntProperty(
        name="Port", default=RECEIVE_PORT_DEFAULT)
    bpy.types.Scene.vmcsimple_running = bpy.props.BoolProperty(default=False)

    bpy.types.Scene.vmcsimple_armature = bpy.props.PointerProperty(
        type=bpy.types.Object, poll=_poll_armature, name="Armature")

    bpy.types.Scene.vmcsimple_bone_map = bpy.props.CollectionProperty(
        type=VMCSIMPLE_BoneMapItem)

    bpy.types.Scene.vmcsimple_headcam = bpy.props.PointerProperty(
        type=bpy.types.Object, poll=_poll_camera, name="Head Camera")
    bpy.types.Scene.vmcsimple_headcam_bone = bpy.props.StringProperty(name="Head Bone")
    bpy.types.Scene.vmcsimple_headcam_offset_loc = bpy.props.FloatVectorProperty(
        name="Offset Location", subtype='TRANSLATION', size=3, default=(0.0, 0.05, 0.0))
    bpy.types.Scene.vmcsimple_headcam_offset_rot = bpy.props.FloatVectorProperty(
        name="Offset Rotation", subtype='EULER', unit='ROTATION', size=3,
        default=(math.radians(-90.0), 0.0, 0.0))

    bpy.types.Scene.vmcsimple_xr_camera = bpy.props.PointerProperty(
        type=bpy.types.Object, poll=_poll_camera, name="XR Camera")

    bpy.types.Scene.vmcsimple_use_openvr_fingers = bpy.props.BoolProperty(
        name="Read fingers from SteamVR", default=False)


def unregister():
    del bpy.types.Scene.vmcsimple_port
    del bpy.types.Scene.vmcsimple_running
    del bpy.types.Scene.vmcsimple_armature
    del bpy.types.Scene.vmcsimple_bone_map
    del bpy.types.Scene.vmcsimple_headcam
    del bpy.types.Scene.vmcsimple_headcam_bone
    del bpy.types.Scene.vmcsimple_headcam_offset_loc
    del bpy.types.Scene.vmcsimple_headcam_offset_rot
    del bpy.types.Scene.vmcsimple_xr_camera
    del bpy.types.Scene.vmcsimple_use_openvr_fingers

    for c in reversed(classes):
        bpy.utils.unregister_class(c)
