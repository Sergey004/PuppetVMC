"""Main tick, called from the Connect operator's modal timer."""

from . import state
from .bones import get_bone_map, apply_bone
from .cameras import update_head_camera, update_xr_camera
from .openvr_bridge import poll_openvr_fingers


def process_queue(context):
    if state.receiver is None:
        return
    armature = context.scene.vmcsimple_armature
    bone_map = get_bone_map(context)

    while not state.receiver.queue.empty():
        address, args = state.receiver.queue.get()
        if address in ("/VMC/Ext/Bone/Pos", "/VMC/Ext/Root/Pos") and armature and len(args) >= 8:
            name, px, py, pz, qx, qy, qz, qw = args[:8]
            apply_bone(armature, bone_map, name, px, py, pz, qx, qy, qz, qw)

    if context.scene.vmcsimple_use_openvr_fingers and armature:
        poll_openvr_fingers(armature, bone_map)

    if armature:
        update_head_camera(context, armature)
    update_xr_camera(context)
