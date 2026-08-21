"""Unity Humanoid raw-muscle to Blender pose conversion.

This module intentionally lives in the add-on: only Blender knows the bind map
and the armature rest pose. The normal VMC tracker path does not use it.
"""
import math
import re

from .bones import apply_bone, apply_local_bone


MUSCLE_AXES = {
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
    "Left Arm Down-Up": ("LeftUpperArm", 0),
    "Left Arm Front-Back": ("LeftUpperArm", 2),
    "Left Arm Twist In-Out": ("LeftUpperArm", 1),
    "Left Forearm Twist In-Out": ("LeftLowerArm", 2),
    "Left Hand Down-Up": ("LeftHand", 0),
    "Left Hand In-Out": ("LeftHand", 1),
    "Right Arm Down-Up": ("RightUpperArm", 0),
    "Right Arm Front-Back": ("RightUpperArm", 2),
    "Right Arm Twist In-Out": ("RightUpperArm", 1),
    "Right Forearm Twist In-Out": ("RightLowerArm", 2),
    "Right Hand Down-Up": ("RightHand", 0),
    "Right Hand In-Out": ("RightHand", 1),
}


def _euler_quaternion(x, y, z):
    x, y, z = (math.radians(value) for value in (x, y, z))
    cx, sx = math.cos(x / 2), math.sin(x / 2)
    cy, sy = math.cos(y / 2), math.sin(y / 2)
    cz, sz = math.cos(z / 2), math.sin(z / 2)
    return (
        sx * cy * cz - cx * sy * sz,
        cx * sy * cz + sx * cy * sz,
        cx * cy * sz - sx * sy * cz,
        cx * cy * cz + sx * sy * sz,
    )


def apply_pose(bone_cache, muscles, fingers):
    angles = {}
    for attribute, value in muscles.items():
        mapping = MUSCLE_AXES.get(attribute)
        if mapping is None:
            continue
        bone_name, axis = mapping
        angles.setdefault(bone_name, [0.0, 0.0, 0.0])[axis] += float(value) * 90.0

    for bone_name, (curl, spread) in fingers.items():
        angles[bone_name] = [math.degrees(curl), math.degrees(spread), 0.0]

    for bone_name, xyz in angles.items():
        apply_local_bone(bone_cache, bone_name, *_euler_quaternion(*xyz))


class UnityAnimationClip:
    """Dependency-free reader and sampler for Unity YAML AnimationClip files."""

    _attribute_re = re.compile(r"^\s+attribute: (.+?)\s*$")

    def __init__(self, path):
        self.path = path
        self.curves = {}
        self.duration = 0.0
        self.sample_rate = 30.0
        self.loop = False
        self.keep_original_orientation = False
        self.keep_position_y = False
        self.keep_position_xz = False
        self._read(path)

    def _read(self, path):
        attribute = None
        keys = []
        pending_time = None
        with open(path, "r", encoding="utf-8") as animation_file:
            for line in animation_file:
                match = re.match(r"^\s+m_StopTime: ([^\s]+)", line)
                if match:
                    self.duration = float(match.group(1))
                match = re.match(r"^\s+m_SampleRate: ([^\s]+)", line)
                if match and float(match.group(1)) > 0:
                    self.sample_rate = float(match.group(1))
                match = re.match(r"^\s+m_LoopTime: ([01])", line)
                if match:
                    self.loop = match.group(1) == "1"
                match = re.match(r"^\s+m_KeepOriginalPosition(Y|XZ): ([01])", line)
                if match:
                    if match.group(1) == "Y":
                        self.keep_position_y = match.group(2) == "1"
                    else:
                        self.keep_position_xz = match.group(2) == "1"
                match = re.match(r"^\s+m_KeepOriginalOrientation: ([01])", line)
                if match:
                    self.keep_original_orientation = match.group(1) == "1"

                match = self._attribute_re.match(line)
                if match:
                    if attribute and keys:
                        self.curves[attribute] = keys
                    attribute = match.group(1)
                    keys = []
                    pending_time = None
                    continue
                if attribute is None:
                    continue
                match = re.match(r"^\s+time: ([^\s]+)", line)
                if match:
                    pending_time = float(match.group(1))
                    continue
                match = re.match(r"^\s+value: ([^\s]+)", line)
                if match and pending_time is not None:
                    keys.append((pending_time, float(match.group(1))))
                    pending_time = None
        if attribute and keys:
            self.curves[attribute] = keys
        if not self.curves:
            raise ValueError("Unity AnimationClip contains no float curves")

    @staticmethod
    def _sample(keys, at_time):
        if not keys:
            return None
        if at_time <= keys[0][0]:
            return keys[0][1]
        if at_time >= keys[-1][0]:
            return keys[-1][1]
        for left, right in zip(keys, keys[1:]):
            if at_time <= right[0]:
                fraction = (at_time - left[0]) / (right[0] - left[0])
                return left[1] + (right[1] - left[1]) * fraction
        return keys[-1][1]

    def sample(self, elapsed):
        at_time = elapsed % self.duration if self.loop and self.duration else elapsed
        at_time = min(at_time, self.duration) if self.duration else 0.0
        muscles = {
            name: self._sample(keys, at_time)
            for name, keys in self.curves.items()
            if name in MUSCLE_AXES
        }
        fingers = {}
        for side in ("Left", "Right"):
            for finger in ("Thumb", "Index", "Middle", "Ring", "Little"):
                spread = self._sample(
                    self.curves.get(f"{side}Hand.{finger}.Spread", []), at_time
                ) or 0.0
                for index, joint in enumerate(("Proximal", "Intermediate", "Distal"), 1):
                    curl = self._sample(
                        self.curves.get(f"{side}Hand.{finger}.{index} Stretched", []),
                        at_time,
                    )
                    if curl is not None:
                        spread_value = spread if joint == "Proximal" else 0.0
                        if side == "Right":
                            spread_value = -spread_value
                        fingers[f"{side}{finger}{joint}"] = (curl, spread_value)

        root_rotation = []
        for component in "xyzw":
            value = self._sample(self.curves.get(f"RootQ.{component}", []), at_time)
            if value is None:
                root_rotation = []
                break
            root_rotation.append(value)
        if self.keep_original_orientation and root_rotation:
            root_rotation = [0.0, 0.0, 0.0, 1.0]
        root_position = []
        for component in "xyz":
            value = self._sample(self.curves.get(f"RootT.{component}", []), at_time)
            if value is None:
                root_position = []
                break
            root_position.append(value)
        if root_position:
            if self.keep_position_y:
                root_position[1] = 0.0
            if self.keep_position_xz:
                root_position[0] = root_position[2] = 0.0
        return root_rotation, root_position, muscles, fingers

    @property
    def has_root_transform(self):
        return not (
            self.keep_original_orientation
            and self.keep_position_y
            and self.keep_position_xz
        )


def apply_clip(bone_cache, clip, elapsed, use_muscles=False):
    root_rotation, root_position, muscles, fingers = clip.sample(elapsed)
    if clip.has_root_transform and root_rotation and root_position:
        apply_bone(bone_cache, "Hips", *root_position, *root_rotation)
    if use_muscles:
        apply_pose(bone_cache, muscles, fingers)


def apply_clip_to_armature(armature, bone_cache, clip, elapsed, use_muscles=False):
    """Apply a clip directly to the bound armature, without any VMC layer."""
    if armature is None or bone_cache is None or clip is None:
        return
    apply_clip(bone_cache, clip, elapsed, use_muscles=use_muscles)