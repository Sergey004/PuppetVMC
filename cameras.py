"""Two independent cameras: a head-camera with a manual offset (follows a
chosen bone, like Ctrl+P > Bone but without manual parenting), and an
XR-camera driven by the real headset pose via Blender's built-in XR."""

from mathutils import Matrix, Euler


def update_head_camera(context, armature):
    cam = context.scene.vmcsimple_headcam
    bone_name = context.scene.vmcsimple_headcam_bone
    if not cam or not bone_name or not armature:
        return
    pbone = armature.pose.bones.get(bone_name)
    if not pbone:
        return
    bone_world = armature.matrix_world @ pbone.matrix
    offset_loc = Matrix.Translation(context.scene.vmcsimple_headcam_offset_loc)
    offset_rot = Euler(context.scene.vmcsimple_headcam_offset_rot, 'XYZ').to_matrix().to_4x4()
    cam.matrix_world = bone_world @ offset_loc @ offset_rot


def update_xr_camera(context):
    """Requires an active VR session: View3D > VR > Start VR Session."""
    cam = context.scene.vmcsimple_xr_camera
    if not cam:
        return
    xr = context.window_manager.xr_session_state
    if xr is None:
        return
    try:
        cam.location = xr.viewer_pose_location(context)
        cam.rotation_mode = 'QUATERNION'
        cam.rotation_quaternion = xr.viewer_pose_rotation(context)
    except RuntimeError:
        pass
