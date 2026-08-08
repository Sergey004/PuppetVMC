"""Two cameras, both live-tweakable from the UI while Connect runs.

Head camera follows a chosen bone every tick: cam.matrix_world =
bone_world @ Translate(offset_loc) @ Rotate(offset_rot) @ Rotate(manual_rot).
No Child Of constraint and no bpy.ops calls — the matrix is written directly,
so nothing depends on which object is active in the scene, and any change to
Offset/Manual sliders in the N-panel is reflected on the next tick (or
immediately via properties._headcam_update).

XR camera is driven by the real headset pose, with the same offset/manual
layering; optionally it can mirror the head camera's pose instead.
"""

from mathutils import Matrix, Euler


def _compose(base_matrix, offset_loc, offset_rot, manual_rot):
    """base @ Translate(offset_loc) @ Rotate(offset_rot) @ Rotate(manual).

    Offset is the fixed rig of the camera relative to its driver; manual_rot
    is the live user twist layered on last so the bone or headset pose can
    never clobber it.
    """
    m_loc = Matrix.Translation(offset_loc)
    m_off = Euler(offset_rot, 'XYZ').to_matrix().to_4x4()
    m_man = Euler(manual_rot, 'XYZ').to_matrix().to_4x4()
    return base_matrix @ m_loc @ m_off @ m_man


def update_head_camera(context, armature):
    scene = context.scene
    cam = scene.puppetvmc_headcam
    bone_name = scene.puppetvmc_headcam_bone
    if not cam or not bone_name or not armature:
        return
    pbone = armature.pose.bones.get(bone_name)
    if not pbone:
        return
    bone_world = armature.matrix_world @ pbone.matrix
    cam.matrix_world = _compose(
        bone_world,
        scene.puppetvmc_headcam_offset_loc,
        scene.puppetvmc_headcam_offset_rot,
        scene.puppetvmc_headcam_manual_rot,
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
    """XR camera pose source, chosen per tick:

    - 'XR follows Head' off (default): the real headset pose from the active
      VR session. Requires View3D > VR > Start VR Session; with no session
      running the camera is left in place.
    - 'XR follows Head' on: the XR camera copies the head camera's current
      world matrix, so a single bone-driven view feeds both cameras. The
      Manual/Offset fields still layer on top.

    Either way the result is base @ Translate(offset_loc) @ Rotate(offset_rot)
    @ Rotate(manual_rot), so every UI field updates live on the next tick.
    """
    scene = context.scene
    cam = scene.puppetvmc_xr_camera
    if not cam:
        return

    if scene.puppetvmc_xr_follow_head:
        head = scene.puppetvmc_headcam
        if not head:
            return
        base = head.matrix_world.copy()
    else:
        base = _xr_pose_matrix(context)
        if base is None:
            return

    cam.matrix_world = _compose(
        base,
        scene.puppetvmc_xr_offset_loc,
        scene.puppetvmc_xr_offset_rot,
        scene.puppetvmc_xr_manual_rot,
    )
