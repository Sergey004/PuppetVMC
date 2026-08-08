import sys
import os
import subprocess

import bpy

from . import state
from .osc import OSCReceiver
from .openvr_bridge import openvr_start, openvr_stop, VENDOR_DIR
from .loop import process_queue
from .constants import FRAME_RATE, VMC_BONE_SLOTS


class VMCSIMPLE_OT_connect(bpy.types.Operator):
    bl_idname = "vmcsimple.connect"
    bl_label = "Connect"

    _timer = None

    def modal(self, context, event):
        if event.type == 'TIMER':
            process_queue(context)
        if not context.scene.vmcsimple_running:
            self.cancel(context)
            return {'CANCELLED'}
        return {'PASS_THROUGH'}

    def execute(self, context):
        state.receiver = OSCReceiver(context.scene.vmcsimple_port)
        state.calibration["origin"] = None
        state.calibration["rotations"] = {}
        if context.scene.vmcsimple_use_openvr_fingers:
            try:
                openvr_start()
            except Exception as e:
                self.report({'WARNING'}, f"OpenVR init failed: {e}")
        context.scene.vmcsimple_running = True
        wm = context.window_manager
        self._timer = wm.event_timer_add(1.0 / FRAME_RATE, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        if state.receiver:
            state.receiver.stop()
            state.receiver = None
        openvr_stop()
        context.window_manager.event_timer_remove(self._timer)


class VMCSIMPLE_OT_disconnect(bpy.types.Operator):
    bl_idname = "vmcsimple.disconnect"
    bl_label = "Disconnect"

    def execute(self, context):
        context.scene.vmcsimple_running = False
        return {'FINISHED'}


class VMCSIMPLE_OT_recalibrate(bpy.types.Operator):
    bl_idname = "vmcsimple.recalibrate"
    bl_label = "Calibrate (stand in T-pose and click)"
    bl_description = "Resets the root position and T-pose baseline across all bones"

    def execute(self, context):
        state.calibration["origin"] = None
        state.calibration["rotations"] = {}
        return {'FINISHED'}


class VMCSIMPLE_OT_init_bone_map(bpy.types.Operator):
    bl_idname = "vmcsimple.init_bone_map"
    bl_label = "Refresh Bone List"
    bl_description = "Adds missing slots for the standard VMC bones without touching already-mapped ones"

    def execute(self, context):
        coll = context.scene.vmcsimple_bone_map
        existing = {item.vmc_name for item in coll}
        added = 0
        for name in VMC_BONE_SLOTS:
            if name not in existing:
                item = coll.add()
                item.vmc_name = name
                added += 1
        self.report({'INFO'}, f"New slots added: {added}")
        return {'FINISHED'}


class VMCSIMPLE_OT_install_openvr(bpy.types.Operator):
    bl_idname = "vmcsimple.install_openvr"
    bl_label = "Install pyopenvr"
    bl_description = "Installs openvr straight into this addon's folder (vendor/). Blender must be restarted after install."

    def execute(self, context):
        py = sys.executable
        try:
            os.makedirs(VENDOR_DIR, exist_ok=True)
            # In case pip isn't installed at all in this Blender build.
            subprocess.run([py, "-m", "ensurepip"], check=False)
            # --target installs straight into our own addon folder instead of
            # Blender's site-packages or the user site-packages. This sidesteps
            # two real issues seen in practice: (1) write permission errors when
            # Blender lives under Program Files, and (2) Blender's bundled
            # Python not adding the user site-packages dir to sys.path at all
            # (pip install --user succeeds and "pip show" finds it, but
            # "import openvr" still fails — confirmed on this exact machine).
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


class VMCSIMPLE_OT_toggle_record(bpy.types.Operator):
    bl_idname = "vmcsimple.toggle_record"
    bl_label = "Record"
    bl_description = "Toggle keyframe recording — advances the timeline and keys every mapped bone each tick while on"

    def execute(self, context):
        context.scene.vmcsimple_recording = not context.scene.vmcsimple_recording
        return {'FINISHED'}


classes = (
    VMCSIMPLE_OT_connect,
    VMCSIMPLE_OT_disconnect,
    VMCSIMPLE_OT_recalibrate,
    VMCSIMPLE_OT_init_bone_map,
    VMCSIMPLE_OT_install_openvr,
    VMCSIMPLE_OT_toggle_record,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
