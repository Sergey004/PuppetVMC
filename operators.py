import sys
import os
import subprocess
import time
import math

import bpy

from . import state
from .osc import OSCReceiver
from .openvr_bridge import openvr_start, openvr_stop, VENDOR_DIR
from .loop import process_queue
from .face_tracking import (
    FACE_TRACKING_TIMEOUT,
    apply_face_tracking,
    capture_eye_baselines,
)
from .bones import build_bone_cache, get_bone_map_conflicts
from .constants import FRAME_RATE, VMC_BONE_SLOTS
from .unity_animation import UnityAnimationClip, apply_clip, apply_clip_to_armature


class PUPPETVMC_OT_connect(bpy.types.Operator):
    bl_idname = "puppetvmc.connect"
    bl_label = "Connect"

    _timer = None

    def modal(self, context, event):
        if event.type == 'TIMER':
            process_queue(context)
        if not context.scene.puppetvmc_running:
            self.cancel(context)
            return {'CANCELLED'}
        return {'PASS_THROUGH'}

    def execute(self, context):
        armature = context.scene.puppetvmc_armature
        if armature is None:
            self.report({'ERROR'}, "Pick an armature first")
            return {'CANCELLED'}
        state.bone_cache = build_bone_cache(armature)
        if state.bone_cache is None:
            self.report({'WARNING'}, "Bind map is empty — nothing will move until you map VMC slots to bones")
        try:
            state.receiver = OSCReceiver(
                context.scene.puppetvmc_address,
                context.scene.puppetvmc_port,
            )
        except OSError as e:
            state.bone_cache = None
            self.report({'ERROR'}, f"Could not bind {context.scene.puppetvmc_address}:{context.scene.puppetvmc_port} — {e}")
            return {'CANCELLED'}
        state.face_tracking_values.clear()
        state.face_tracking_last_received = None
        state.face_eye_baselines = capture_eye_baselines(
            armature, context.scene,
        )
        state.face_receiver = None
        if context.scene.puppetvmc_face_tracking_enabled:
            try:
                state.face_receiver = OSCReceiver(
                    context.scene.puppetvmc_address,
                    context.scene.puppetvmc_face_tracking_port,
                    face_tracking=True,
                )
            except OSError as e:
                self.report(
                    {'WARNING'},
                    f"VMC connected, but VRCFaceTracking listener could not bind "
                    f"{context.scene.puppetvmc_address}:"
                    f"{context.scene.puppetvmc_face_tracking_port} — {e}",
                )
        state.calibration["origin"] = None
        state.calibration["countdown_end"] = None
        state.ovr["hmd_origin"] = None
        if (context.scene.puppetvmc_use_openvr_fingers
                or context.scene.puppetvmc_use_openvr_hmd_position):
            try:
                openvr_start(
                    track_hmd_position=context.scene.puppetvmc_use_openvr_hmd_position,
                )
            except Exception as e:
                self.report({'WARNING'}, f"OpenVR init failed: {e}")
        context.scene.puppetvmc_running = True
        wm = context.window_manager
        PUPPETVMC_OT_connect._timer = wm.event_timer_add(1.0 / FRAME_RATE, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        if state.receiver:
            state.receiver.stop()
            state.receiver = None
        if state.face_receiver:
            armature = context.scene.puppetvmc_armature
            if armature:
                apply_face_tracking(
                    armature,
                    context.scene,
                    {},
                    state.face_eye_baselines,
                    time.time() - FACE_TRACKING_TIMEOUT - 1.0,
                )
            state.face_receiver.stop()
            state.face_receiver = None
        try:
            openvr_stop()
        except RuntimeError as e:
            self.report({'WARNING'}, str(e))
        if PUPPETVMC_OT_connect._timer is not None:
            context.window_manager.event_timer_remove(PUPPETVMC_OT_connect._timer)
            PUPPETVMC_OT_connect._timer = None
        state.bone_cache = None


class PUPPETVMC_OT_disconnect(bpy.types.Operator):
    bl_idname = "puppetvmc.disconnect"
    bl_label = "Disconnect"

    def execute(self, context):
        context.scene.puppetvmc_running = False
        return {'FINISHED'}


class PUPPETVMC_OT_recalibrate(bpy.types.Operator):
    bl_idname = "puppetvmc.recalibrate"
    bl_label = "Calibrate (stand in T-pose and click)"
    bl_description = "Resets the root position and T-pose baseline across all bones"

    def execute(self, context):
        state.calibration["origin"] = None
        state.calibration["rotations"] = {}
        state.calibration["countdown_end"] = None
        state.ovr["hmd_origin"] = None
        return {'FINISHED'}


class PUPPETVMC_OT_force_t_pose(bpy.types.Operator):
    bl_idname = "puppetvmc.force_t_pose"
    bl_label = "Force T-Pose"
    bl_description = "Reset all pose bones to the armature rest pose"

    @classmethod
    def poll(cls, context):
        return context.scene.puppetvmc_armature is not None

    def execute(self, context):
        armature = context.scene.puppetvmc_armature
        for pose_bone in armature.pose.bones:
            pose_bone.matrix_basis.identity()

        state.calibration["origin"] = None
        state.calibration["rotations"] = {}
        state.ovr["hmd_origin"] = None
        self.report({'INFO'}, "Armature reset to rest/T-pose")
        return {'FINISHED'}


class PUPPETVMC_OT_start_calibration_timer(bpy.types.Operator):
    bl_idname = "puppetvmc.start_calibration_timer"
    bl_label = "Calibrate in 5s"
    bl_description = ("Start a countdown — stand in T-pose, wait N seconds, "
                      "then calibration origin/rotations reset automatically")

    _timer = None

    @classmethod
    def poll(cls, context):
        return context.scene.puppetvmc_armature is not None

    def modal(self, context, event):
        if event.type in {'TIMER', 'WINDOWPOSTPAINT'}:
            if state.calibration["countdown_end"] is not None:
                if time.time() >= state.calibration["countdown_end"]:
                    state.calibration["origin"] = None
                    state.calibration["rotations"] = {}
                    state.ovr["hmd_origin"] = None
                    state.calibration["countdown_end"] = None
                    try:
                        from .openvr_bridge import haptic_pulse
                        haptic_pulse()
                    except Exception:
                        pass
                    self.cancel(context)
                    return {'FINISHED'}
            return {'RUNNING_MODAL'}

        if event.type == 'ESC':
            self.cancel(context)
            return {'CANCELLED'}

        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        seconds = context.scene.puppetvmc_calib_delay
        state.calibration["countdown_end"] = time.time() + seconds
        try:
            from .openvr_bridge import haptic_pulse
            haptic_pulse()
        except Exception:
            pass
        context.window_manager.modal_handler_add(self)
        self._timer = context.window_manager.event_timer_add(1.0, window=context.window)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        state.calibration["countdown_end"] = None


class PUPPETVMC_OT_init_bone_map(bpy.types.Operator):
    bl_idname = "puppetvmc.init_bone_map"
    bl_label = "Refresh Bone List"
    bl_description = "Adds missing slots for the standard VMC bones without touching already-mapped ones"

    def execute(self, context):
        coll = context.scene.puppetvmc_bone_map
        existing = {item.vmc_name for item in coll}
        added = 0
        for name in VMC_BONE_SLOTS:
            if name not in existing:
                item = coll.add()
                item.vmc_name = name
                added += 1
        self.report({'INFO'}, f"New slots added: {added}")
        return {'FINISHED'}


class PUPPETVMC_OT_install_openvr(bpy.types.Operator):
    bl_idname = "puppetvmc.install_openvr"
    bl_label = "Install pyopenvr"
    bl_description = "Installs openvr straight into this addon's folder (vendor/). Blender must be restarted after install."

    def execute(self, context):
        py = sys.executable
        try:
            os.makedirs(VENDOR_DIR, exist_ok=True)
            subprocess.run([py, "-m", "ensurepip"], check=False)
            subprocess.run(
                [py, "-m", "pip", "install", "--target", VENDOR_DIR, "openvr"],
                check=True,
            )
            self.report({'INFO'}, "openvr installed into the addon's vendor/ folder — restart Blender")
        except subprocess.CalledProcessError as e:
            self.report({'ERROR'}, f"pip failed: {e}")
        except Exception as e:
            self.report({'ERROR'}, f"Failed: {e}")
        return {'FINISHED'}


class PUPPETVMC_OT_toggle_record(bpy.types.Operator):
    bl_idname = "puppetvmc.toggle_record"
    bl_label = "Record"
    bl_description = "Toggle VMC4B-style timestamped recording — stores packets and bakes an Action on stop"

    def execute(self, context):
        if not context.scene.puppetvmc_recording:
            # start recording
            context.scene.puppetvmc_recording = True
            if state.receiver is not None:
                state.receiver.recording = True
            from . import state
            from .recorder import start_recording
            start_recording(context)
            state.recording_start_time = __import__('time').time()
            self.report({'INFO'}, "Recording started")
        else:
            # stop recording and bake
            if state.receiver is not None:
                state.receiver.recording = False
            from .recorder import bake_recording
            bake_recording(context)
            context.scene.puppetvmc_recording = False
            self.report({'INFO'}, "Recording stopped and baked")
        return {'FINISHED'}


class PUPPETVMC_OT_load_animation(bpy.types.Operator):
    bl_idname = "puppetvmc.load_animation"
    bl_label = "Load Unity .anim"

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        try:
            clip = UnityAnimationClip(self.filepath)
        except (OSError, ValueError) as error:
            self.report({'ERROR'}, f"Could not load Unity animation: {error}")
            return {'CANCELLED'}
        state.animation_clip = clip
        state.animation_elapsed = 0.0
        context.scene.puppetvmc_animation_file = self.filepath
        context.scene.puppetvmc_animation_playing = False
        self.report({'INFO'}, f"Loaded {os.path.basename(self.filepath)} ({clip.sample_rate:g} FPS)")
        return {'FINISHED'}


class PUPPETVMC_OT_play_animation(bpy.types.Operator):
    bl_idname = "puppetvmc.play_animation"
    bl_label = "Play Animation"

    _timer = None

    def execute(self, context):
        if state.animation_clip is None:
            self.report({'ERROR'}, "Load a Unity .anim file first")
            return {'CANCELLED'}
        if context.scene.puppetvmc_armature is None:
            self.report({'ERROR'}, "Pick an armature first")
            return {'CANCELLED'}
        if context.scene.puppetvmc_running:
            self.report({'ERROR'}, "Disconnect VMC before playing a local animation")
            return {'CANCELLED'}
        conflicts = get_bone_map_conflicts(context)
        if conflicts:
            details = "; ".join(
                f"{bone}: {', '.join(names)}"
                for bone, names in conflicts.items()
            )
            self.report({'ERROR'}, f"Duplicate Bind targets: {details}")
            return {'CANCELLED'}
        armature = context.scene.puppetvmc_armature
        if armature.animation_data is not None:
            # Do not delete the old Action; detach it so it cannot fight the
            # direct Unity player while the clip is running.
            armature.animation_data.action = None
        if state.bone_cache is None:
            state.bone_cache = build_bone_cache(armature)
        state.animation_started_at = time.perf_counter() - state.animation_elapsed
        context.scene.puppetvmc_animation_playing = True
        self._timer = context.window_manager.event_timer_add(
            1.0 / FRAME_RATE, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'TIMER':
            if state.animation_started_at is not None:
                state.animation_elapsed = time.perf_counter() - state.animation_started_at
            apply_clip_to_armature(
                context.scene.puppetvmc_armature,
                state.bone_cache,
                state.animation_clip,
                state.animation_elapsed,
                context.scene.puppetvmc_animation_use_muscles,
            )
        if not context.scene.puppetvmc_animation_playing:
            self.cancel(context)
            return {'CANCELLED'}
        return {'PASS_THROUGH'}

    def cancel(self, context):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None


class PUPPETVMC_OT_stop_animation(bpy.types.Operator):
    bl_idname = "puppetvmc.stop_animation"
    bl_label = "Stop Animation"

    def execute(self, context):
        if state.animation_started_at is not None:
            state.animation_elapsed = time.perf_counter() - state.animation_started_at
        context.scene.puppetvmc_animation_playing = False
        return {'FINISHED'}


class PUPPETVMC_OT_bake_animation(bpy.types.Operator):
    bl_idname = "puppetvmc.bake_animation"
    bl_label = "Bake to Timeline"
    bl_description = "Sample the Unity clip and create a Blender Action on the armature"

    def execute(self, context):
        if state.animation_clip is None:
            self.report({'ERROR'}, "Load a Unity .anim file first")
            return {'CANCELLED'}
        if context.scene.puppetvmc_running or context.scene.puppetvmc_animation_playing:
            self.report({'ERROR'}, "Stop VMC and animation playback before baking")
            return {'CANCELLED'}

        armature = context.scene.puppetvmc_armature
        if armature is None:
            self.report({'ERROR'}, "Pick an armature first")
            return {'CANCELLED'}
        conflicts = get_bone_map_conflicts(context)
        if conflicts:
            self.report({'ERROR'}, "Fix duplicate Bind targets before baking")
            return {'CANCELLED'}
        if state.bone_cache is None:
            state.bone_cache = build_bone_cache(armature)
        if state.bone_cache is None:
            self.report({'ERROR'}, "Build the Avatar Bind map first")
            return {'CANCELLED'}

        clip = state.animation_clip
        fps = clip.sample_rate if clip.sample_rate > 0 else 30.0
        frame_end = max(1, int(math.ceil(clip.duration * fps)))
        action = bpy.data.actions.new(name=f"Unity {os.path.basename(clip.path)}")
        action.use_fake_user = True
        if armature.animation_data is None:
            armature.animation_data_create()
        armature.animation_data.action = action
        state.calibration["origin"] = None
        use_muscles = context.scene.puppetvmc_animation_use_muscles
        original_frame = context.scene.frame_current
        original_fps = context.scene.render.fps
        original_fps_base = context.scene.render.fps_base
        context.scene.render.fps = max(1, int(round(fps)))
        context.scene.render.fps_base = 1.0

        for frame in range(1, frame_end + 1):
            elapsed = (frame - 1) / fps
            context.scene.frame_set(frame)
            apply_clip(state.bone_cache, clip, elapsed, use_muscles=use_muscles)
            for item in context.scene.puppetvmc_bone_map:
                if not item.bone_name:
                    continue
                pose_bone = armature.pose.bones.get(item.bone_name)
                if pose_bone is None:
                    continue
                pose_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
                if item.vmc_name == "Hips":
                    pose_bone.keyframe_insert(data_path="location", frame=frame)

        action.frame_start = 1
        action.frame_end = frame_end
        context.scene.frame_start = 1
        context.scene.frame_end = frame_end
        context.scene.frame_set(original_frame if 1 <= original_frame <= frame_end else 1)
        self.report({'INFO'}, f"Baked {frame_end} frames at {fps:g} FPS to {action.name}")
        return {'FINISHED'}


classes = (
    PUPPETVMC_OT_connect,
    PUPPETVMC_OT_disconnect,
    PUPPETVMC_OT_recalibrate,
    PUPPETVMC_OT_force_t_pose,
    PUPPETVMC_OT_start_calibration_timer,
    PUPPETVMC_OT_init_bone_map,
    PUPPETVMC_OT_install_openvr,
    PUPPETVMC_OT_toggle_record,
    PUPPETVMC_OT_load_animation,
    PUPPETVMC_OT_play_animation,
    PUPPETVMC_OT_stop_animation,
    PUPPETVMC_OT_bake_animation,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)