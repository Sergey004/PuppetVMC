bl_info = {
    "name": "PuppetVMC",
    "author": "Sergey004 (And Claude + others)",
    "version": (0, 3),
    "blender": (5, 1, 0),
    "location": "View3D > N-panel > VMC",
    "description": "Minimal custom VMC protocol receiver: UI bone list (Bind override), "
                    "T-pose calibration, delta-based root motion, bone-locked camera with offset, "
                    "XR camera from a real headset, and fingers pulled directly from SteamVR (OpenVR).",
    "category": "Animation",
}

from . import properties
from . import operators
from . import panel
from . import xr_probe
from .openvr_bridge import openvr_stop


def register():
    properties.register()
    operators.register()
    panel.register()
    xr_probe.register()


def unregister():
    openvr_stop()
    xr_probe.unregister()
    panel.unregister()
    operators.unregister()
    properties.unregister()
