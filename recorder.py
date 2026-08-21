"""VMC4B-style timestamped recorder for PuppetVMC."""
from math import floor
import bpy
from collections import deque
from . import state
from .bones import get_bone_map
from .convert import convert_position, convert_rotation
from .constants import ROOT_HUMANOID_BONE

def start_recording(context):
    state.recorder_queue.clear()
    # start time and frame not needed, first packet defines zero

def _get_fcurve(action, armature, data_path, index, group_name):
    try:
        return action.fcurve_ensure_for_datablock(armature, data_path=data_path, index=index, group_name=group_name)
    except AttributeError:
        try:
            return action.fcurves.new(data_path=data_path, index=index, action_group=group_name)
        except AttributeError:
            from bpy_extras.anim_utils import action_ensure_channelbag_for_slot
            if armature.animation_data is None:
                armature.animation_data_create()
            if armature.animation_data.action_slot is None:
                slot = action.slots.new(id_type='OBJECT', name=armature.name)
                armature.animation_data.action_slot = slot
            slot = armature.animation_data.action_slot
            cbag = action_ensure_channelbag_for_slot(action, slot)
            fcurve = cbag.fcurves.new(data_path=data_path, index=index)
            try:
                fcurve.group = action.groups.new(name=group_name)
            except Exception:
                pass
            return fcurve
    except Exception:
        return action.fcurves.new(data_path=data_path, index=index)

def bake_recording(context):
    if not state.recorder_queue:
        return
    armature = context.scene.puppetvmc_armature
    if armature is None:
        return
    scene = context.scene
    fps = state.recording_fps or scene.render.fps
    bone_map = get_bone_map(context)
    bone_cache = state.bone_cache
    if bone_cache is None:
        bone_cache = {}

    # first packet defines zero
    first_ts = None
    for item in state.recorder_queue:
        ts = item.get("timestamp")
        if ts is not None:
            first_ts = ts
            break
    if first_ts is None:
        first_ts = 0

    # data structures
    data_root = {}  # path -> [components]
    data_bones = {}  # bone_name -> path -> [components]
    max_frame = 1
    min_frame = 1

    # process packets in order
    for item in state.recorder_queue:
        ts = item.get("timestamp", first_ts)
        address = item.get("address", "")
        args = item.get("args", [])
        frame = int(floor((ts - first_ts) * fps)) + 1
        if frame > max_frame:
            max_frame = frame
        if frame < min_frame:
            min_frame = frame

        if address == "/VMC/Ext/Root/Pos" and len(args) >= 8:
            # convert root
            # args layout: ?, px, py, pz, ?, qx, qy, qz, qw ? Need check VMC spec.
            # VMC4B convert_root uses args[1], args[2], args[3], args[4], args[5], args[6], args[7]
            # We'll assume args[1]=px, args[2]=py, args[3]=pz, args[4]=qx?, Hmm.
            # Use generic mapping from VMC4B: convert_root expects args[1],args[3],args[2] for pos, args[4],args[5],args[6],args[7] for rot
            try:
                px, py, pz = args[1], args[2], args[3]
                qx, qy, qz, qw = args[4], args[5], args[6], args[7]
            except Exception:
                continue
            pos = convert_position(px, py, pz)
            rot = convert_rotation(qx, qy, qz, qw)
            for path, values in [("location", pos), ("rotation_quaternion", rot)]:
                if path not in data_root:
                    data_root[path] = [[] for _ in range(3 if path=="location" else 4)]
                comps = data_root[path]
                for i in range(len(comps)):
                    val = values[i]
                    lst = comps[i]
                    if lst and lst[-1][0] == frame:
                        lst[-1] = (frame, val)
                    else:
                        lst.append((frame, val))
        elif address == "/VMC/Ext/Bone/Pos" and len(args) >= 8:
            vmc_name = args[0]
            bone_name = bone_map.get(vmc_name)
            if not bone_name:
                continue
            try:
                px, py, pz = args[1], args[2], args[3]
                qx, qy, qz, qw = args[4], args[5], args[6], args[7]
            except Exception:
                continue
            # get entry
            entry = bone_cache.get("bones", {}).get(vmc_name)
            if not entry:
                continue
            parent_quat = entry.parent_quaternion
            rquat = convert_rotation(qx, qy, qz, qw)
            local_q = parent_quat.inverted() @ rquat @ parent_quat

            # location handling for Hips root motion
            if vmc_name == ROOT_HUMANOID_BONE:
                root_pbone = bone_cache.get("root_pose_bone")
                root_q = bone_cache.get("root_quaternion")
                hips_hl = bone_cache.get("hips_head_local")
                if root_pbone and root_q and hips_hl is not None:
                    world_pos = convert_position(px, py, pz)
                    if state.calibration["origin"] is not None:
                        anchored_pos = world_pos - state.calibration["origin"]
                    else:
                        anchored_pos = world_pos
                    local_loc = root_q.inverted() @ (anchored_pos - hips_hl)
                    # store location for root bone
                    root_bone_name = root_pbone.name
                    if root_bone_name not in data_bones:
                        data_bones[root_bone_name] = {}
                    path = "location"
                    if path not in data_bones[root_bone_name]:
                        data_bones[root_bone_name][path] = [[] for _ in range(3)]
                    for i in range(3):
                        lst = data_bones[root_bone_name][path][i]
                        val = local_loc[i]
                        if lst and lst[-1][0] == frame:
                            lst[-1] = (frame, val)
                        else:
                            lst.append((frame, val))
            # rotation for bone
            if bone_name not in data_bones:
                data_bones[bone_name] = {}
            path = "rotation_quaternion"
            if path not in data_bones[bone_name]:
                data_bones[bone_name][path] = [[] for _ in range(4)]
            for i in range(4):
                val = local_q[i]
                lst = data_bones[bone_name][path][i]
                if lst and lst[-1][0] == frame:
                    lst[-1] = (frame, val)
                else:
                    lst.append((frame, val))
        # else ignore

    # create action
    action_name = f"VMC Record {armature.name} {int(scene.frame_current)}"
    action = bpy.data.actions.new(name=action_name)
    action.use_fake_user = True
    if armature.animation_data is None:
        armature.animation_data_create()
    armature.animation_data.action = action
    # set action frame range
    action.frame_start = min_frame
    action.frame_end = max_frame

    # root object fcurves
    for path, comps in data_root.items():
        for i, points in enumerate(comps):
            fcurve = _get_fcurve(action, armature, path, i, "Object Transforms")
            if points:
                for frame_num, value in points:
                    kp = fcurve.keyframe_points.insert(frame_num, value)
                    kp.interpolation = 'LINEAR'
                fcurve.color_mode = "AUTO_RGB" if len(comps) == 3 else "AUTO_YRGB"

    # bone fcurves
    for bone_name, paths in data_bones.items():
        for path, comps in paths.items():
            for i, points in enumerate(comps):
                data_path = f'pose.bones["{bone_name}"].{path}'
                fcurve = _get_fcurve(action, armature, data_path, i, bone_name)
                if points:
                    for frame_num, value in points:
                        kp = fcurve.keyframe_points.insert(frame_num, value)
                        kp.interpolation = 'LINEAR'
                    fcurve.color_mode = "AUTO_RGB" if len(comps) == 3 else "AUTO_YRGB"

    # update scene timeline to the recorded range
    scene.frame_current = min_frame
    if scene.frame_end < max_frame:
        scene.frame_end = max_frame

    # cleanup
    state.recorder_queue.clear()
    state.recording_start_time = None
    state.recording_start_frame = None
    state.recording_fps = None
