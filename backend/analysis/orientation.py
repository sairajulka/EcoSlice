import copy
import numpy as np

from .overhang import calculate_overhangs


def rotation_matrix_x(angle_degrees):
    angle = np.radians(angle_degrees)

    return np.array([
        [1, 0, 0, 0],
        [0, np.cos(angle), -np.sin(angle), 0],
        [0, np.sin(angle), np.cos(angle), 0],
        [0, 0, 0, 1]
    ])


def rotation_matrix_y(angle_degrees):
    angle = np.radians(angle_degrees)

    return np.array([
        [np.cos(angle), 0, np.sin(angle), 0],
        [0, 1, 0, 0],
        [-np.sin(angle), 0, np.cos(angle), 0],
        [0, 0, 0, 1]
    ])


def rotation_matrix_z(angle_degrees):
    angle = np.radians(angle)

    return np.array([
        [np.cos(angle), -np.sin(angle), 0, 0],
        [np.sin(angle), np.cos(angle), 0, 0],
        [0, 0, 1, 0],
        [0, 0, 0, 1]
    ])


def evaluate_orientation(mesh, x, y, z):
    test_mesh = copy.deepcopy(mesh)

    matrix = (
        rotation_matrix_z(z)
        @ rotation_matrix_y(y)
        @ rotation_matrix_x(x)
    )

    test_mesh.apply_transform(matrix)

    overhang = calculate_overhangs(test_mesh)

    dimensions = test_mesh.extents

    return {
        "x_rotation": x,
        "y_rotation": y,
        "z_rotation": z,
        "overhang_percentage": overhang["overhang_percentage"],
        "height_mm": float(dimensions[2]),
        "volume_mm3": float(test_mesh.volume),
    }


def find_best_orientations(mesh):
    candidates = []

    angles = [0, 45, 90, 135]

    for x in angles:
        for y in angles:
            for z in [0, 90]:

                result = evaluate_orientation(
                    mesh,
                    x,
                    y,
                    z
                )

                candidates.append(result)

    candidates.sort(
        key=lambda item: (
            item["overhang_percentage"],
            item["height_mm"]
        )
    )

    return candidates[:5]