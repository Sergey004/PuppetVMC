import sys
import os
import subprocess
import time

import bpy

from . import state
from .osc import OSCReceiver
from .openvr_bridge import openvr_start, openvr_stop, VENDOR_DIR
from .loop import process_queue
from .bones import build_bone_cache
from .constants import FRAME_RATE, VMC_BONE_SLOTS


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
        state.calibration["origin"] = None
        state.calibration["countdown_end"] = None
        if context.scene.puppetvmc_use_openvr_fingers:
            try:
                openvr_start()
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
        openvr_stop()
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
            from . import state
            from .recorder import start_recording
            start_recording(context)
            state.recording_start_time = __import__('time').time()
            self.report({'INFO'}, "Recording started")
        else:
            # stop recording and bake
            from .recorder import bake_recording
            bake_recording(context)
            context.scene.puppetvmc_recording = False
            self.report({'INFO'}, "Recording stopped and baked")
        return {'FINISHED'}


classes = (
    PUPPETVMC_OT_connect,
    PUPPETVMC_OT_disconnect,
    PUPPETVMC_OT_recalibrate,
    PUPPETVMC_OT_start_calibration_timer,
    PUPPETVMC_OT_init_bone_map,
    PUPPETVMC_OT_install_openvr,
    PUPPETVMC_OT_toggle_record,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)