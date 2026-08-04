"""Constants: VMC slot list, default port, timer frequency, OpenVR finger bone mapping."""

VMC_BONE_SLOTS = [
    "Hips", "Spine", "Chest", "Neck", "Head",
    "LeftShoulder", "LeftUpperArm", "LeftLowerArm", "LeftHand",
    "LeftUpperLeg", "LeftLowerLeg", "LeftFoot", "LeftToes",
    "RightShoulder", "RightUpperArm", "RightLowerArm", "RightHand",
    "RightUpperLeg", "RightLowerLeg", "RightFoot", "RightToes",
    "LeftEye", "RightEye", "Jaw",
    # Fingers — standard Unity Humanoid slots, 3 joints per finger.
    "LeftThumbProximal", "LeftThumbIntermediate", "LeftThumbDistal",
    "LeftIndexProximal", "LeftIndexIntermediate", "LeftIndexDistal",
    "LeftMiddleProximal", "LeftMiddleIntermediate", "LeftMiddleDistal",
    "LeftRingProximal", "LeftRingIntermediate", "LeftRingDistal",
    "LeftLittleProximal", "LeftLittleIntermediate", "LeftLittleDistal",
    "RightThumbProximal", "RightThumbIntermediate", "RightThumbDistal",
    "RightIndexProximal", "RightIndexIntermediate", "RightIndexDistal",
    "RightMiddleProximal", "RightMiddleIntermediate", "RightMiddleDistal",
    "RightRingProximal", "RightRingIntermediate", "RightRingDistal",
    "RightLittleProximal", "RightLittleIntermediate", "RightLittleDistal",
]

ROOT_HUMANOID_BONE = "Hips"   # which VMC bone drives root motion
RECEIVE_PORT_DEFAULT = 39539  # match the VMC output port in SlimeVR Server
FRAME_RATE = 60.0

# Indices of the standard 31-bone OpenVR hand skeleton (HandSkeletonBone_t).
# Metacarpal and Tip bones are skipped — Unity Humanoid doesn't have them.
OPENVR_FINGER_BONES = {
    3:  "ThumbProximal",
    4:  "ThumbIntermediate",
    5:  "ThumbDistal",
    7:  "IndexProximal",
    8:  "IndexIntermediate",
    9:  "IndexDistal",
    12: "MiddleProximal",
    13: "MiddleIntermediate",
    14: "MiddleDistal",
    17: "RingProximal",
    18: "RingIntermediate",
    19: "RingDistal",
    22: "LittleProximal",
    23: "LittleIntermediate",
    24: "LittleDistal",
}
