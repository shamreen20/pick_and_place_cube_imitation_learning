import math
import random  #  Imports random to generate random X/Y coordinates on the table.
from nova.types import Pose  #  Imports Pose type from NOVA, which represents a Cartesian pose as position plus orientation.

X_MIN = -520.2
X_MAX = 507.9
Y_MIN = -522.1
Y_MAX = -222.1  # Y_MIN + 300mm = 300mm deep (30 cm)
Z_TABLE_APPROACH = 430.0 #Defines Z height for an approach pose above the table (safe hovering height).
Z_DROP = 260.0 #Defines Z height for a drop pose on the table.
ORIENTATION = (3.1245, -0.0346, -0.0037) # Defines a fixed orientation (rotation vector) used for random approach/place poses.

# TCP delta taken from NOVA setup:
# OnRobot_Single pose = (0.0, 0.0, 0.0, 0, 0, 0)
# umi_gripper pose     = (-1.5724, 3.6754, 221.7036, 0, 0, 0)
# This delta is expressed in the flange frame and is rotated into world frame
# for each target pose orientation to preserve previous motion intent.
TCP_DELTA_FROM_ONROBOT_MM = (-1.5724206279, 3.6753509887, 221.7035558263) #Stores the TCP translation delta in millimeters as a 3D vector.


def rotate_vector_by_rotvec_mm(
    vector_mm: tuple[float, float, float], rotvec: tuple[float, float, float]
) -> tuple[float, float, float]:
    vx, vy, vz = vector_mm
    rx, ry, rz = rotvec
    theta = math.sqrt(rx * rx + ry * ry + rz * rz)  # Computes rotation magnitude theta as Euclidean norm of rotation vector.
    if theta < 1e-12:  #Checks near-zero rotation to avoid unstable normalization/division.
        return (vx, vy, vz)

    kx, ky, kz = rx / theta, ry / theta, rz / theta #Normalizes rotation axis components kx, ky, kz.
    cos_t = math.cos(theta) #Computes cosine of rotation angle.
    sin_t = math.sin(theta) #Computes sine of rotation angle.

    # Rodrigues rotation formula: v_rot = v*cos(theta) + (k x v)*sin(theta) + k*(k·v)*(1-cos(theta))
    k_cross_vx = ky * vz - kz * vy
    k_cross_vy = kz * vx - kx * vz
    k_cross_vz = kx * vy - ky * vx
    k_dot_v = kx * vx + ky * vy + kz * vz

    out_x = vx * cos_t + k_cross_vx * sin_t + kx * k_dot_v * (1.0 - cos_t)
    out_y = vy * cos_t + k_cross_vy * sin_t + ky * k_dot_v * (1.0 - cos_t)
    out_z = vz * cos_t + k_cross_vz * sin_t + kz * k_dot_v * (1.0 - cos_t)
    return (out_x, out_y, out_z)


def compensate_from_onrobot_pose(base_pose: Pose) -> Pose: # Starts function to convert a reference pose into a compensated pose for current TCP.
    orientation = (   # Begins extracting orientation from base pose.
        float(base_pose.orientation.x),
        float(base_pose.orientation.y),
        float(base_pose.orientation.z),
    )
    dx, dy, dz = rotate_vector_by_rotvec_mm(TCP_DELTA_FROM_ONROBOT_MM, orientation) # Rotates TCP delta into world frame using this pose orientation.
    return Pose(
        (
            float(base_pose.position.x) + dx,
            float(base_pose.position.y) + dy,
            float(base_pose.position.z) + dz,
            orientation[0], #Keeps orientation X unchanged.
            orientation[1], #Keeps orientation Y unchanged.
            orientation[2], #Keeps orientation Z unchanged.
        )
    )


HOME_POSE = compensate_from_onrobot_pose(
    Pose((-377.7, -362.7, 557.7, 3.1245, -0.0342, -0.0039))
)
TARGET_APPROACH = compensate_from_onrobot_pose(
    Pose((-377.7, -362.7, 450.0, 3.1245, -0.0343, -0.0037))
)
TARGET_PICK = compensate_from_onrobot_pose(
    Pose((-377.6, -362.7, 259.7, 3.1247, -0.0343, -0.0033))
)


def random_table_pose() -> tuple[Pose, Pose]:
    x = random.uniform(X_MIN, X_MAX)
    y = random.uniform(Y_MIN, Y_MAX)
    approach = compensate_from_onrobot_pose(Pose((x, y, Z_TABLE_APPROACH, *ORIENTATION)))  #Builds compensated approach pose at hover Z for sampled X/Y.
    place = compensate_from_onrobot_pose(Pose((x, y, Z_DROP, *ORIENTATION)))  #Builds compensated place pose at drop Z for sampled X/Y.
    return approach, place


def offset_z_down(pose: Pose, dz_mm: float) -> Pose:  #Starts helper to create a pose lowered by dz_mm in Z.


    return Pose(
        (
            float(pose.position.x),
            float(pose.position.y),
            float(pose.position.z) - dz_mm,  #Lowers Z by dz_mm (positive dz means move downward).
            float(pose.orientation.x),
            float(pose.orientation.y),
            float(pose.orientation.z),
        )
    )


"""This module is the single source of truth for spatial definitions. It defines workspace limits, performs TCP-aware pose compensation, provides calibrated fixed poses, generates bounded random target poses, and offers a utility for controlled Z-offset motions. Keeping all pose logic here ensures consistent kinematics behavior across the full pick-and-place workflow"""
