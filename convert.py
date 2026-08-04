"""Coordinate conversion: VMC/Unity (Y-up, left-handed) -> Blender (Z-up, right-handed)."""

from mathutils import Vector, Quaternion


def convert_position(px, py, pz):
    return Vector((-px, -pz, py))


def convert_rotation(qx, qy, qz, qw):
    return Quaternion((qw, qx, qz, -qy))
