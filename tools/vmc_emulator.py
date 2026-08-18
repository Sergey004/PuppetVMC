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


def send_tra_pos(name, px, py, pz, qx, qy, qz, qw):
    osc_client.send_message("/VMC/Ext/Tra/Pos", [name, px, py, pz, qx, qy, qz, qw])


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
# GUI
# ---------------------------------------------------------------------------

ROTATION_BONES = [
    "Hips", "Spine", "Head",
    "LeftUpperArm", "LeftLowerArm", "LeftHand",
    "RightUpperArm", "RightLowerArm", "RightHand",
    "LeftUpperLeg", "LeftLowerLeg", "RightUpperLeg", "RightLowerLeg",
]
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
    for bone in ROTATION_BONES:
        if bone in photo_override:
            qx, qy, qz, qw = photo_override[bone]
        else:
            pitch, yaw, roll = (v.get() for v in rot_vars[bone])
            qx, qy, qz, qw = euler_to_quat(pitch, yaw, roll)

        if bone == "Hips":
            px, py, pz = (v.get() for v in pos_vars["hips_bonepos"])
        else:
            px, py, pz = 0.0, 0.0, 0.0
        send_bone_pos(bone, px, py, pz, qx, qy, qz, qw)

    wx, wy, wz = (v.get() for v in pos_vars["waist_trapos"])
    send_tra_pos("human://WAIST", wx, wy, wz, 0.0, 0.0, 0.0, -1.0)

    root.after(int(1000 / SEND_RATE_HZ), tick)


tick()
root.mainloop()
