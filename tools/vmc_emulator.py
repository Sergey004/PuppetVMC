"""
VMC Emulator — sliders + optional "load pose from photo" — sends real VMC
OSC traffic on localhost so PuppetVMC (or any VMC receiver) can be tested
end-to-end without launching SlimeVR / wearing trackers.

Sends BOTH:
  - /VMC/Ext/Bone/Pos  (rotation-only, per confirmed real-world SlimeVR
    behaviour: position on this channel is always zero, only rotation moves)
  - /VMC/Ext/Tra/Pos human://WAIST  (the actual position channel)

Uses pythonosc (pip install python-osc) to send, deliberately NOT the
hand-rolled OSC builder that PuppetVMC's own osc.py uses to parse. Testing
our parser against our own sender would only prove internal consistency,
not correctness against the real OSC spec — if both shared the same
misunderstanding of the format, a test against ourselves would never catch
it, and it would only surface against a real sender like SlimeVR. Sending
through an independent, well-tested library is the actual test.

Photo pose extraction (optional, lazy-imported):
    pip install mediapipe opencv-python
Without those installed, everything else (sliders) still works fine.

MediaPipe API compatibility
--------------------------
MediaPipe >= 0.10.21 / 1.x removed the legacy ``mp.solutions.pose`` API
and replaced it with the new Tasks API (``mp.tasks.vision.PoseLandmarker``),
which additionally requires an external ``pose_landmarker.task`` model file
and returns a differently-shaped result. ``extract_pose_from_photo`` below
auto-detects which API is available and uses the right one, so this script
works with both old (<= 0.10.20) and new (>= 0.10.21 / 1.x) MediaPipe.

When using the new Tasks API, the model file is looked for in:
  1. Next to this script (``<addon>/tools/pose_landmarker.task``)
  2. In the user's home directory
and downloaded once from the official Google storage URL if missing, then
cached next to this script for offline use afterwards.

LIMITATION on photo poses: position-based pose estimation from a single
image gives joint POSITIONS, not bone ROTATIONS. We compute "swing" (which
direction a bone points) accurately from those positions; "twist" (rotation
around the bone's own axis) is NOT recoverable from a single photo and is
left at zero. Expect a ballpark/silhouette match, not frame-perfect copying.

Run standalone: python vmc_emulator.py
"""

import sys
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import math
import re
import time

try:
    from pythonosc.udp_client import SimpleUDPClient
except ImportError:
    print("Missing dependency: pip install python-osc", file=sys.stderr)
    raise

TARGET_IP = "127.0.0.1"
TARGET_PORT = 39539
SEND_RATE_HZ = 30

# ---------------------------------------------------------------------------
# OSC sending via pythonosc — deliberately independent of PuppetVMC's own
# hand-rolled parser, see module docstring for why.
# ---------------------------------------------------------------------------

osc_client = SimpleUDPClient(TARGET_IP, TARGET_PORT)


def send_bone_pos(name, px, py, pz, qx, qy, qz, qw):
    osc_client.send_message("/VMC/Ext/Bone/Pos", [name, px, py, pz, qx, qy, qz, qw])


def send_local_bone_pos(name, qx, qy, qz, qw):
    osc_client.send_message(
        "/PuppetVMC/Anim/LocalBone/Pos", [name, qx, qy, qz, qw]
    )


def send_anim_muscle(name, value):
    osc_client.send_message("/PuppetVMC/Anim/Muscle", [name, value])


def send_anim_finger(name, curl, spread):
    osc_client.send_message("/PuppetVMC/Anim/Finger", [name, curl, spread])


def send_tra_pos(name, px, py, pz, qx, qy, qz, qw):
    osc_client.send_message("/VMC/Ext/Tra/Pos", [name, px, py, pz, qx, qy, qz, qw])


def send_record_control(start, fps=None):
    address = "/PuppetVMC/Record/Start" if start else "/PuppetVMC/Record/Stop"
    osc_client.send_message(address, [float(fps)] if start and fps else [])


# ---------------------------------------------------------------------------
# Euler (degrees) -> quaternion, for slider-driven bones.
# ---------------------------------------------------------------------------

def euler_to_quat(pitch_deg, yaw_deg, roll_deg):
    p, y, r = (math.radians(a) for a in (pitch_deg, yaw_deg, roll_deg))
    cy, sy = math.cos(y * 0.5), math.sin(y * 0.5)
    cp, sp = math.cos(p * 0.5), math.sin(p * 0.5)
    cr, sr = math.cos(r * 0.5), math.sin(r * 0.5)
    qw = cr * cp * cy + sr * sp * sy
    qx = sr * cp * cy - cr * sp * sy
    qy = cr * sp * cy + sr * cp * sy
    qz = cr * cp * sy - sr * sp * cy
    return qx, qy, qz, qw


def muscle_angles_to_quat(x_deg, y_deg, z_deg):
    """Convert Unity muscle XYZ angles to an (x, y, z, w) quaternion."""
    x, y, z = (math.radians(value) for value in (x_deg, y_deg, z_deg))
    cx, sx = math.cos(x * 0.5), math.sin(x * 0.5)
    cy, sy = math.cos(y * 0.5), math.sin(y * 0.5)
    cz, sz = math.cos(z * 0.5), math.sin(z * 0.5)
    return (
        sx * cy * cz - cx * sy * sz,
        cx * sy * cz + sx * cy * sz,
        cx * cy * sz - sx * sy * cz,
        cx * cy * cz + sx * sy * sz,
    )


# ---------------------------------------------------------------------------
# Vector math for photo-pose swing rotation (no numpy dependency).
# ---------------------------------------------------------------------------

def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _normalize(v):
    length = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if length < 1e-9:
        return (0.0, 0.0, 1.0)
    return (v[0] / length, v[1] / length, v[2] / length)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def rotation_between_vectors(v_from, v_to):
    """Shortest-arc quaternion (x,y,z,w) rotating v_from onto v_to. Pure
    swing, zero twist by construction — see module docstring."""
    v_from = _normalize(v_from)
    v_to = _normalize(v_to)
    d = _dot(v_from, v_to)

    if d > 0.999999:
        return (0.0, 0.0, 0.0, 1.0)

    if d < -0.999999:
        axis = _cross((1.0, 0.0, 0.0), v_from)
        if math.sqrt(sum(c * c for c in axis)) < 1e-6:
            axis = _cross((0.0, 1.0, 0.0), v_from)
        axis = _normalize(axis)
        return (axis[0], axis[1], axis[2], 0.0)

    axis = _cross(v_from, v_to)
    s = math.sqrt((1.0 + d) * 2.0)
    inv_s = 1.0 / s
    return (axis[0] * inv_s, axis[1] * inv_s, axis[2] * inv_s, s * 0.5)


# ---------------------------------------------------------------------------
# MediaPipe pose landmark indices in the standard 33-point model.
# These numeric indices are IDENTICAL for both the legacy Solutions API
# (mp.solutions.pose.PoseLandmark.NAME) and the new Tasks API — we hardcode
# them here so we don't depend on the enum being importable on new
# MediaPipe versions where it was moved/removed.
# Reference: developers.google.com/mediapipe/solutions/vision/pose_landmarker
# ---------------------------------------------------------------------------

POSE_LANDMARK_IDX = {
    "NOSE":             0,
    "LEFT_SHOULDER":   11, "RIGHT_SHOULDER":   12,
    "LEFT_ELBOW":      13, "RIGHT_ELBOW":      14,
    "LEFT_WRIST":      15, "RIGHT_WRIST":      16,
    "LEFT_HIP":        23, "RIGHT_HIP":        24,
    "LEFT_KNEE":       25, "RIGHT_KNEE":       26,
    "LEFT_ANKLE":      27, "RIGHT_ANKLE":      28,
}

# Bones we can derive from a photo: (vmc_name, parent_landmark_name,
# child_landmark_name, rest_direction_in_vmc_space)
PHOTO_BONE_DEFS = [
    ("Spine",         "LEFT_HIP",      "LEFT_SHOULDER",  (0, 1, 0)),
    ("LeftUpperArm",  "LEFT_SHOULDER", "LEFT_ELBOW",     (1, 0, 0)),
    ("LeftLowerArm",  "LEFT_ELBOW",    "LEFT_WRIST",     (1, 0, 0)),
    ("RightUpperArm", "RIGHT_SHOULDER", "RIGHT_ELBOW",   (-1, 0, 0)),
    ("RightLowerArm", "RIGHT_ELBOW",   "RIGHT_WRIST",    (-1, 0, 0)),
    ("LeftUpperLeg",  "LEFT_HIP",      "LEFT_KNEE",      (0, -1, 0)),
    ("LeftLowerLeg",  "LEFT_KNEE",     "LEFT_ANKLE",     (0, -1, 0)),
    ("RightUpperLeg", "RIGHT_HIP",     "RIGHT_KNEE",     (0, -1, 0)),
    ("RightLowerLeg", "RIGHT_KNEE",    "RIGHT_ANKLE",    (0, -1, 0)),
]


def _landmark_to_vmc_vec(lm):
    # Both legacy NormalizedLandmark and new Tasks-API Landmark expose
    # .x/.y/.z as floats. MediaPipe image/world space: x right, y DOWN,
    # z more negative = closer to camera. Flip Y to get Y-up, and Z so
    # that "more negative = closer" becomes "more positive = closer"
    # (matches the VMC convention used by the rest of the codebase).
    return (lm.x, -lm.y, -lm.z)


# ---------------------------------------------------------------------------
# Pose detection — supports BOTH legacy mp.solutions.pose (mediapipe
# <= 0.10.20) and the new mp.tasks.vision.PoseLandmarker (mediapipe
# >= 0.10.21 / 1.x). The new Tasks API additionally needs an external
# .task model file; we look for it in standard locations and download
# it once from Google's official storage if missing, then cache it
# next to this script so subsequent runs are offline.
# ---------------------------------------------------------------------------

# Official Google-hosted MediaPipe Tasks model. ~9 MB, float16.
POSE_LANDMARKER_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "pose_landmarker/pose_landmarker_full/float16/latest/"
    "pose_landmarker_full.task"
)


def _find_or_download_pose_model():
    """Returns absolute path to pose_landmarker.task, downloading it once
    if not present. Raises RuntimeError with manual instructions if the
    download fails (offline / proxy / firewall)."""
    import urllib.request

    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(script_dir, "pose_landmarker.task"),
        os.path.join(os.path.expanduser("~"), "pose_landmarker.task"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p

    # Not found anywhere — download next to this script (writable in
    # both standalone and Blender-addon contexts) and cache for reuse.
    target = candidates[0]
    try:
        os.makedirs(script_dir, exist_ok=True)
        urllib.request.urlretrieve(POSE_LANDMARKER_MODEL_URL, target)
        return target
    except Exception as e:
        raise RuntimeError(
            "MediaPipe Tasks API requires the model file "
            "'pose_landmarker.task' (it could not be downloaded "
            f"automatically: {e}).\n\n"
            "Download it manually from:\n"
            f"  {POSE_LANDMARKER_MODEL_URL}\n\n"
            "and place it at any of:\n" +
            "".join(f"  - {p}\n" for p in candidates)
        )


def _detect_pose_legacy(mp, cv2, image):
    """Legacy MediaPipe Solutions API (mediapipe <= 0.10.20).
    Returns a flat list of 33 landmark objects, or None if no pose."""
    with mp.solutions.pose.Pose(static_image_mode=True) as pose_model:
        result = pose_model.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    if not result.pose_world_landmarks:
        return None
    # pose_world_landmarks.landmark is a RepeatedCompositeContainer;
    # convert to a plain list so we can index by integer.
    return list(result.pose_world_landmarks.landmark)


def _detect_pose_tasks(mp, cv2, image):
    """New MediaPipe Tasks API (mediapipe >= 0.10.21 / 1.x).
    Returns a flat list of 33 landmark objects, or None if no pose.

    Result-shape difference from legacy:
      legacy: result.pose_world_landmarks.landmark[i]
      tasks : result.pose_world_landmarks[pose_idx][i]   (list of lists)
    This helper flattens the first detected pose to match the legacy shape.
    """
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    model_path = _find_or_download_pose_model()

    options = vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=model_path),
        running_mode=vision.RunningMode.IMAGE,
        num_poses=1,
    )
    with vision.PoseLandmarker.create_from_options(options) as landmarker:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = landmarker.detect(mp_image)

    if not result.pose_world_landmarks:
        return None
    # Take the first detected pose, convert to plain list for legacy-shape parity.
    return list(result.pose_world_landmarks[0])


def extract_pose_from_photo(path):
    """Lazy-imports mediapipe/cv2. Returns dict vmc_name -> (qx,qy,qz,qw),
    or raises RuntimeError with a human-readable message on failure.

    Auto-detects which MediaPipe API is available:
      - legacy ``mp.solutions.pose.Pose`` (mediapipe <= 0.10.20)
      - new ``mp.tasks.vision.PoseLandmarker`` (mediapipe >= 0.10.21 / 1.x)
    The new API additionally downloads + caches the pose_landmarker.task
    model file on first use; see ``_find_or_download_pose_model``.
    """
    try:
        import cv2
        import mediapipe as mp
    except ImportError:
        raise RuntimeError(
            "mediapipe/opencv-python not installed.\n"
            "Run: pip install mediapipe opencv-python"
        )

    image = cv2.imread(path)
    if image is None:
        raise RuntimeError(f"Could not read image: {path}")

    # MediaPipe >= 0.10.21 / 1.x removed mp.solutions entirely. Detect
    # which API is available and dispatch accordingly — the legacy and
    # Tasks APIs have incompatible result-shapes (see _detect_pose_tasks
    # docstring), so we normalise to a flat landmark list here.
    has_legacy = (
        hasattr(mp, "solutions")
        and hasattr(mp.solutions, "pose")
        and hasattr(mp.solutions.pose, "Pose")
    )

    if has_legacy:
        landmarks = _detect_pose_legacy(mp, cv2, image)
    else:
        landmarks = _detect_pose_tasks(mp, cv2, image)

    if not landmarks:
        raise RuntimeError("No pose detected in this image.")

    quats = {}
    for vmc_name, parent_name, child_name, rest_dir in PHOTO_BONE_DEFS:
        p = _landmark_to_vmc_vec(landmarks[POSE_LANDMARK_IDX[parent_name]])
        c = _landmark_to_vmc_vec(landmarks[POSE_LANDMARK_IDX[child_name]])
        direction = _sub(c, p)
        quats[vmc_name] = rotation_between_vectors(rest_dir, direction)
    return quats


# ---------------------------------------------------------------------------
# Unity AnimationClip playback.
# ---------------------------------------------------------------------------

_ANIM_ATTRIBUTE_RE = re.compile(r"^\s+attribute: (.+?)\s*$")
_ANIM_DURATION_RE = re.compile(r"^\s+m_StopTime: ([^\s]+)\s*$")
_ANIM_SAMPLE_RATE_RE = re.compile(r"^\s+m_SampleRate: ([^\s]+)\s*$")
_ANIM_LOOP_RE = re.compile(r"^\s+m_LoopTime: ([01])\s*$")
_ANIM_KEEP_POSITION_RE = re.compile(
    r"^\s+m_KeepOriginalPosition(Y|XZ): ([01])\s*$"
)


def _finish_animation_curve(curves, attribute, key_values):
    if attribute and key_values:
        curves[attribute] = key_values


class UnityAnimation:
    """Read Unity YAML float curves that can be sent directly through VMC."""

    DIRECT_TRACKS = {
        "RootQ": "Hips",
        "RootT": "Hips",
        "LeftFootQ": "LeftFoot",
        "RightFootQ": "RightFoot",
        "LeftHandQ": "LeftHand",
        "RightHandQ": "RightHand",
    }
    MUSCLE_TRACKS = {
        "Spine Front-Back": ("Spine", 0),
        "Spine Left-Right": ("Spine", 1),
        "Spine Twist Left-Right": ("Spine", 2),
        "Chest Front-Back": ("Chest", 0),
        "Chest Left-Right": ("Chest", 1),
        "Chest Twist Left-Right": ("Chest", 2),
        "UpperChest Front-Back": ("UpperChest", 0),
        "UpperChest Left-Right": ("UpperChest", 1),
        "UpperChest Twist Left-Right": ("UpperChest", 2),
        "Neck Nod Down-Up": ("Neck", 0),
        "Neck Tilt Left-Right": ("Neck", 1),
        "Neck Turn Left-Right": ("Neck", 2),
        "Head Nod Down-Up": ("Head", 0),
        "Head Tilt Left-Right": ("Head", 1),
        "Head Turn Left-Right": ("Head", 2),
        "Left Upper Leg Front-Back": ("LeftUpperLeg", 0),
        "Left Upper Leg In-Out": ("LeftUpperLeg", 1),
        "Left Upper Leg Twist In-Out": ("LeftUpperLeg", 2),
        "Right Upper Leg Front-Back": ("RightUpperLeg", 0),
        "Right Upper Leg In-Out": ("RightUpperLeg", 1),
        "Right Upper Leg Twist In-Out": ("RightUpperLeg", 2),
        "Left Lower Leg Twist In-Out": ("LeftLowerLeg", 2),
        "Right Lower Leg Twist In-Out": ("RightLowerLeg", 2),
        "Left Foot Up-Down": ("LeftFoot", 0),
        "Left Foot Twist In-Out": ("LeftFoot", 2),
        "Right Foot Up-Down": ("RightFoot", 0),
        "Right Foot Twist In-Out": ("RightFoot", 2),
        "Left Shoulder Down-Up": ("LeftUpperArm", 0),
        "Left Shoulder Front-Back": ("LeftUpperArm", 2),
        "Left Arm Down-Up": ("LeftUpperArm", 0),
        "Left Arm Front-Back": ("LeftUpperArm", 2),
        "Left Arm Twist In-Out": ("LeftUpperArm", 1),
        "Left Forearm Twist In-Out": ("LeftLowerArm", 2),
        "Left Hand Down-Up": ("LeftHand", 0),
        "Left Hand In-Out": ("LeftHand", 1),
        "Right Shoulder Down-Up": ("RightUpperArm", 0),
        "Right Shoulder Front-Back": ("RightUpperArm", 2),
        "Right Arm Down-Up": ("RightUpperArm", 0),
        "Right Arm Front-Back": ("RightUpperArm", 2),
        "Right Arm Twist In-Out": ("RightUpperArm", 1),
        "Right Forearm Twist In-Out": ("RightLowerArm", 2),
        "Right Hand Down-Up": ("RightHand", 0),
        "Right Hand In-Out": ("RightHand", 1),
    }

    def __init__(self, path):
        self.path = path
        self.curves = {}
        self.duration = 0.0
        self.sample_rate = float(SEND_RATE_HZ)
        self.loop = False
        self.keep_original_position_y = False
        self.keep_original_position_xz = False
        self._read(path)
        self.rotation_tracks = self._build_tracks("Q")
        self.position_tracks = self._build_tracks("T")
        self.muscle_tracks = {
            attribute: (bone_name, axis, self.curves[attribute])
            for attribute, (bone_name, axis) in self.MUSCLE_TRACKS.items()
            if attribute in self.curves
        }
        self.finger_tracks = self._build_finger_tracks()

    def _build_finger_tracks(self):
        tracks = {}
        for side in ("Left", "Right"):
            for finger in ("Thumb", "Index", "Middle", "Ring", "Little"):
                spread = self.curves.get(f"{side}Hand.{finger}.Spread", [])
                for joint, joint_name in enumerate(
                    ("Proximal", "Intermediate", "Distal"), start=1
                ):
                    curl = self.curves.get(
                        f"{side}Hand.{finger}.{joint} Stretched", []
                    )
                    if curl:
                        tracks[f"{side}{finger}{joint_name}"] = (curl, spread)
        return tracks

    def _read(self, path):
        current_attribute = None
        key_values = []
        pending_time = None
        with open(path, "r", encoding="utf-8") as animation_file:
            for line in animation_file:
                duration_match = _ANIM_DURATION_RE.match(line)
                if duration_match:
                    self.duration = float(duration_match.group(1))
                sample_rate_match = _ANIM_SAMPLE_RATE_RE.match(line)
                if sample_rate_match:
                    parsed_rate = float(sample_rate_match.group(1))
                    if parsed_rate > 0.0:
                        self.sample_rate = parsed_rate
                loop_match = _ANIM_LOOP_RE.match(line)
                if loop_match:
                    self.loop = loop_match.group(1) == "1"
                keep_position_match = _ANIM_KEEP_POSITION_RE.match(line)
                if keep_position_match:
                    keep_name, keep_value = keep_position_match.groups()
                    if keep_name == "Y":
                        self.keep_original_position_y = keep_value == "1"
                    else:
                        self.keep_original_position_xz = keep_value == "1"

                attribute_match = _ANIM_ATTRIBUTE_RE.match(line)
                if attribute_match:
                    _finish_animation_curve(self.curves, current_attribute, key_values)
                    current_attribute = attribute_match.group(1)
                    key_values = []
                    pending_time = None
                    continue

                if current_attribute is None:
                    continue
                time_match = re.match(r"^\s+time: ([^\s]+)\s*$", line)
                if time_match:
                    pending_time = float(time_match.group(1))
                    continue
                value_match = re.match(r"^\s+value: ([^\s]+)\s*$", line)
                if value_match and pending_time is not None:
                    key_values.append((pending_time, float(value_match.group(1))))
                    pending_time = None

        _finish_animation_curve(self.curves, current_attribute, key_values)
        if self.duration <= 0.0:
            self.duration = max(
                (key[0] for curve in self.curves.values() for key in curve),
                default=0.0,
            )
        if not self.curves:
            raise ValueError("AnimationClip does not contain float curves")

    def _build_tracks(self, suffix):
        tracks = {}
        for prefix, bone_name in self.DIRECT_TRACKS.items():
            if not prefix.endswith(suffix):
                continue
            components = {
                component: self.curves.get(f"{prefix}.{component}", [])
                for component in "xyzw"
                if f"{prefix}.{component}" in self.curves
            }
            if components:
                tracks[bone_name] = components
        return tracks

    @staticmethod
    def _sample_curve(keys, at_time):
        if not keys:
            return None
        if at_time <= keys[0][0]:
            return keys[0][1]
        if at_time >= keys[-1][0]:
            return keys[-1][1]
        for (left_time, left_value), (right_time, right_value) in zip(keys, keys[1:]):
            if at_time <= right_time:
                fraction = (at_time - left_time) / (right_time - left_time)
                return left_value + (right_value - left_value) * fraction
        return keys[-1][1]

    def sample(self, elapsed):
        if self.duration <= 0.0:
            at_time = 0.0
        elif self.loop:
            at_time = elapsed % self.duration
        else:
            at_time = min(elapsed, self.duration)

        rotations = {}
        muscles = {}
        fingers = {}
        for bone_name, components in self.rotation_tracks.items():
            values = [self._sample_curve(components.get(component), at_time)
                      for component in "xyzw"]
            if all(value is not None for value in values):
                length = math.sqrt(sum(value * value for value in values))
                rotations[bone_name] = tuple(value / length for value in values) \
                    if length > 1e-9 else (0.0, 0.0, 0.0, 1.0)

        for attribute, (_, _, keys) in self.muscle_tracks.items():
            muscles[attribute] = self._sample_curve(keys, at_time)

        for bone_name, (curl_keys, spread_keys) in self.finger_tracks.items():
            curl = self._sample_curve(curl_keys, at_time)
            spread = self._sample_curve(spread_keys, at_time) if spread_keys else 0.0
            if curl is None:
                continue
            spread_sign = 1.0 if bone_name.startswith("Left") else -1.0
            fingers[bone_name] = (
                curl,
                spread * spread_sign if bone_name.endswith("Proximal") else 0.0,
            )

        positions = {}
        root_components = self.position_tracks.get("Hips", {})
        root_values = [self._sample_curve(root_components.get(component), at_time)
                       for component in "xyz"]
        if all(value is not None for value in root_values):
            if self.keep_original_position_xz:
                root_values[0] = 0.0
                root_values[2] = 0.0
            if self.keep_original_position_y:
                root_values[1] = 0.0
            positions["hips_bonepos"] = tuple(root_values)
        return rotations, positions, muscles, fingers


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

ROTATION_BONES = [
    "Hips", "Spine", "Head",
    "LeftUpperArm", "LeftLowerArm", "LeftHand",
    "RightUpperArm", "RightLowerArm", "RightHand",
    "LeftUpperLeg", "LeftLowerLeg", "LeftFoot",
    "RightUpperLeg", "RightLowerLeg", "RightFoot",
]
for _side in ("Left", "Right"):
    for _finger in ("Thumb", "Index", "Middle", "Ring", "Little"):
        for _joint in ("Proximal", "Intermediate", "Distal"):
            ROTATION_BONES.append(f"{_side}{_finger}{_joint}")
PHOTO_COVERED_BONES = {name for name, *_ in PHOTO_BONE_DEFS}

root = tk.Tk()
root.title("VMC Emulator (no SlimeVR needed)")
root.geometry("480x720")

# Scrollable container — 11 bones x 3 sliders + position rows is too tall
# for a fixed window.
outer = ttk.Frame(root)
outer.pack(fill="both", expand=True)
canvas = tk.Canvas(outer, borderwidth=0, highlightthickness=0)
scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
main = ttk.Frame(canvas, padding=10)
main.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
canvas.create_window((0, 0), window=main, anchor="nw")
canvas.configure(yscrollcommand=scrollbar.set)
canvas.pack(side="left", fill="both", expand=True)
scrollbar.pack(side="right", fill="y")

rot_vars = {}        # bone_name -> (pitch_var, yaw_var, roll_var)
pos_vars = {}         # key -> (x_var, y_var, z_var)
photo_override = {}   # bone_name -> (qx, qy, qz, qw), takes priority over sliders
bone_labelframes = {}  # bone_name -> LabelFrame, for visual override indication
animation = None
animation_elapsed = 0.0
animation_started_at = None
animation_playing = False


def add_rotation_row(parent, label):
    frame = ttk.LabelFrame(parent, text=label)
    frame.pack(fill="x", pady=3)
    bone_labelframes[label] = frame
    pitch = tk.DoubleVar(value=0.0)
    yaw = tk.DoubleVar(value=0.0)
    roll = tk.DoubleVar(value=0.0)
    for name, var in (("Pitch", pitch), ("Yaw", yaw), ("Roll", roll)):
        row = ttk.Frame(frame)
        row.pack(fill="x")
        ttk.Label(row, text=name, width=6).pack(side="left")
        ttk.Scale(row, from_=-180, to=180, variable=var, orient="horizontal").pack(
            side="left", fill="x", expand=True)
    rot_vars[label] = (pitch, yaw, roll)


def add_position_row(parent, label, key, rng=1.0):
    frame = ttk.LabelFrame(parent, text=label)
    frame.pack(fill="x", pady=3)
    x = tk.DoubleVar(value=0.0)
    y = tk.DoubleVar(value=0.0)
    z = tk.DoubleVar(value=0.0)
    for name, var in (("X", x), ("Y", y), ("Z", z)):
        row = ttk.Frame(frame)
        row.pack(fill="x")
        ttk.Label(row, text=name, width=6).pack(side="left")
        ttk.Scale(row, from_=-rng, to=rng, variable=var, orient="horizontal").pack(
            side="left", fill="x", expand=True)
    pos_vars[key] = (x, y, z)


# --- Photo pose controls ---
photo_frame = ttk.LabelFrame(main, text="Photo pose (optional, needs mediapipe + opencv-python)")
photo_frame.pack(fill="x", pady=(0, 8))
photo_status = ttk.Label(photo_frame, text="No photo loaded — sliders in control.")
photo_status.pack(anchor="w", padx=4, pady=(2, 4))


def do_load_photo():
    path = filedialog.askopenfilename(
        title="Choose a photo",
        filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp"), ("All files", "*.*")],
    )
    if not path:
        return
    try:
        quats = extract_pose_from_photo(path)
    except RuntimeError as e:
        messagebox.showerror("Pose extraction failed", str(e))
        return
    photo_override.clear()
    photo_override.update(quats)
    photo_status.config(text=f"Photo pose active: {len(quats)} bones overridden. "
                              f"Twist/roll is not recoverable from a photo (see docstring).")
    for name in PHOTO_COVERED_BONES:
        if name in bone_labelframes:
            bone_labelframes[name].config(text=f"{name}  [PHOTO]")


def do_clear_photo():
    photo_override.clear()
    photo_status.config(text="No photo loaded — sliders in control.")
    for name in PHOTO_COVERED_BONES:
        if name in bone_labelframes:
            bone_labelframes[name].config(text=name)


def do_load_animation():
    global animation, animation_elapsed, animation_started_at, animation_playing
    path = filedialog.askopenfilename(
        title="Choose a Unity AnimationClip",
        filetypes=[("Unity AnimationClip", "*.anim"), ("All files", "*.*")],
    )
    if not path:
        return
    try:
        loaded_animation = UnityAnimation(path)
    except (OSError, ValueError) as error:
        messagebox.showerror("Animation load failed", str(error))
        return
    animation = loaded_animation
    animation_elapsed = 0.0
    animation_started_at = time.perf_counter()
    animation_playing = True
    send_record_control(True, animation.sample_rate)
    animation_status.config(
        text=f"Playing {os.path.basename(path)}: {animation.duration:.2f}s @ "
             f"{animation.sample_rate:g} FPS, "
             f"{len(animation.rotation_tracks)} quaternion + "
             f"{len(animation.muscle_tracks)} muscle + "
             f"{len(animation.finger_tracks)} finger tracks"
    )
    animation_play_button.config(text="Pause")


def do_toggle_animation():
    global animation_elapsed, animation_started_at, animation_playing
    if animation is None:
        return
    now = time.perf_counter()
    if animation_playing:
        animation_elapsed = now - animation_started_at
        animation_playing = False
        send_record_control(False)
        animation_play_button.config(text="Play")
    else:
        animation_started_at = now - animation_elapsed
        animation_playing = True
        send_record_control(True, animation.sample_rate)
        animation_play_button.config(text="Pause")


def do_clear_animation():
    global animation, animation_elapsed, animation_started_at, animation_playing
    animation = None
    animation_elapsed = 0.0
    animation_started_at = None
    animation_playing = False
    send_record_control(False)
    animation_status.config(text="No animation loaded — sliders in control.")
    animation_play_button.config(text="Play")

def reset_all():
    for vars_tuple in rot_vars.values():
        for v in vars_tuple:
            v.set(0.0)
    for vars_tuple in pos_vars.values():
        for v in vars_tuple:
            v.set(0.0)
    photo_override.clear()

btn_row = ttk.Frame(photo_frame)
btn_row.pack(fill="x", padx=4, pady=(0, 4))
ttk.Button(btn_row, text="Load Photo...", command=do_load_photo).pack(side="left")
ttk.Button(btn_row, text="Clear Photo Pose", command=do_clear_photo).pack(side="left", padx=6)
ttk.Button(btn_row, text="Reset All", command=reset_all).pack(side="left", padx=6)

# --- Unity AnimationClip controls ---
animation_frame = ttk.LabelFrame(main, text="Unity animation (.anim)")
animation_frame.pack(fill="x", pady=(0, 8))
animation_status = ttk.Label(animation_frame, text="No animation loaded — sliders in control.")
animation_status.pack(anchor="w", padx=4, pady=(2, 4))
animation_btn_row = ttk.Frame(animation_frame)
animation_btn_row.pack(fill="x", padx=4, pady=(0, 4))
ttk.Button(animation_btn_row, text="Load Animation...", command=do_load_animation).pack(side="left")
animation_play_button = ttk.Button(animation_btn_row, text="Play", command=do_toggle_animation)
animation_play_button.pack(side="left", padx=6)
ttk.Button(animation_btn_row, text="Clear Animation", command=do_clear_animation).pack(side="left")

# --- Rotation sliders ---
ttk.Label(main, text="Rotations (-> /VMC/Ext/Bone/Pos, rotation only)",
          font=("", 10, "bold")).pack(anchor="w", pady=(4, 4))
for bone in ROTATION_BONES:
    add_rotation_row(main, bone)

# --- Position sliders ---
ttk.Label(main, text="Positions", font=("", 10, "bold")).pack(anchor="w", pady=(10, 4))
add_position_row(main, "Hips Bone/Pos (real SlimeVR: always 0 here — sanity check)",
                  "hips_bonepos", rng=1.0)
add_position_row(main, "WAIST Tra/Pos (the real root-motion channel)",
                  "waist_trapos", rng=1.0)



status = ttk.Label(main, text=f"Sending to {TARGET_IP}:{TARGET_PORT} @ {SEND_RATE_HZ} Hz")
status.pack(anchor="w", pady=(10, 0))


def tick():
    animation_rotations = {}
    animation_positions = {}
    if animation is not None:
        elapsed = (time.perf_counter() - animation_started_at
                   if animation_playing else animation_elapsed)
        animation_rotations, animation_positions, animation_muscles, animation_fingers = animation.sample(elapsed)
    else:
        animation_muscles = {}
        animation_fingers = {}

    for name, value in animation_muscles.items():
        send_anim_muscle(name, value)
    for name, (curl, spread) in animation_fingers.items():
        send_anim_finger(name, curl, spread)

    for bone in ROTATION_BONES:
        if bone in animation_rotations:
            qx, qy, qz, qw = animation_rotations[bone]
        elif bone in photo_override:
            qx, qy, qz, qw = photo_override[bone]
        else:
            pitch, yaw, roll = (v.get() for v in rot_vars[bone])
            qx, qy, qz, qw = euler_to_quat(pitch, yaw, roll)

        if bone == "Hips":
            if "hips_bonepos" in animation_positions:
                px, py, pz = animation_positions["hips_bonepos"]
            else:
                px, py, pz = (v.get() for v in pos_vars["hips_bonepos"])
        else:
            px, py, pz = 0.0, 0.0, 0.0
        send_bone_pos(bone, px, py, pz, qx, qy, qz, qw)

    wx, wy, wz = (v.get() for v in pos_vars["waist_trapos"])
    send_tra_pos("human://WAIST", wx, wy, wz, 0.0, 0.0, 0.0, -1.0)

    root.after(int(1000 / SEND_RATE_HZ), tick)


tick()
root.mainloop()
