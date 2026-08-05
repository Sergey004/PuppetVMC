"""Two cameras, both live-tweakable from the UI while Connect runs.

Head camera follows a chosen bone with an offset location + offset rotation,
plus a manual rotation that the user can drag in the panel to look around in
real time. The XR camera is driven by the real headset pose and gets the same
treatment (offset loc + offset rot + manual rot); optionally it can mirror
the head camera when there is no active VR session or the user wants one
shared viewport target. Both are recomputed every tick in loop.py, so any
property change in the panel is reflected on the next frame.
"""

from mathutils import Matrix, Euler


def _compose(base_matrix, offset_loc, offset_rot, manual_rot):
    """base @ Translate(offset_loc) @ Rotate(offset_rot) @ Rotate(manual).

    Offset is a fixed rig of the camera relative to its driver; manual_rot
    is the live user twist layered on last so it never gets clobbered by the
    bone or headset pose.
    """
    m_loc = Matrix.Translation(offset_loc)
    m_off = Euler(offset_rot, 'XYZ').to_matrix().to_4x4()
    m_man = Euler(manual_rot, 'XYZ').to_matrix().to_4x4()
    return base_matrix @ m_loc @ m_off @ m_man


def update_head_camera(context, armature):
    scene = context.scene
    cam = scene.vmcsimple_headcam
    bone_name = scene.vmcsimple_headcam_bone
    if not cam or not bone_name or not armature:
        return
    pbone = armature.pose.bones.get(bone_name)
    if not pbone:
        return
    bone_world = armature.matrix_world @ pbone.matrix
    cam.matrix_world = _compose(
        bone_world,
        scene.vmcsimple_headcam_offset_loc,
        scene.vmcsimple_headcam_offset_rot,
        scene.vmcsimple_headcam_manual_rot,
    )


def _xr_pose_matrix(context):
    """World-space headset pose as a 4x4, or None if no active XR session."""
    xr = context.window_manager.xr_session_state
    if xr is None:
        return None
    try:
        loc = xr.viewer_pose_location(context)
        rot = xr.viewer_pose_rotation(context)
    except RuntimeError:
        return None
    return Matrix.Translation(loc) @ rot.to_matrix().to_4x4()


def update_xr_camera(context):
    """Requires an active VR session: View3D > VR > Start VR Session.

    Without a session, the camera is left where it was last set — the user
    can still drag Offset/Manual fields when 'XR follows Head' mirrors the
    head camera instead.
    """
    scene = context.scene
    cam = scene.vmcsimple_xr_camera
    if not cam:
        return

    if scene.vmcsimple_xr_follow_head:
        base = Matrix.Identity(4)
    else:
        base = _xr_pose_matrix(context)
        if base is None:
            return

    cam.matrix_world = _compose(
        base,
        scene.vmcsimple_xr_offset_loc,
        scene.vmcsimple_xr_offset_rot,
        scene.vmcsimple_xr_manual_rot,
    )
