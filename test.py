import openvr
import time

openvr.init(openvr.VRApplication_Background)
vr = openvr.VRSystem()

try:
    while True:
        poses = vr.getDeviceToAbsoluteTrackingPose(
            openvr.TrackingUniverseStanding,
            0,
            openvr.k_unMaxTrackedDeviceCount
        )

        pose = poses[openvr.k_unTrackedDeviceIndex_Hmd]

        if pose.bPoseIsValid:
            m = pose.mDeviceToAbsoluteTracking

            x = m[0][3]
            y = m[1][3]
            z = m[2][3]

            print(f"HMD: X={x:.3f} Y={y:.3f} Z={z:.3f}")

        time.sleep(0.01)

finally:
    openvr.shutdown()