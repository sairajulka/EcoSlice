import numpy as np
import trimesh


def calculate_overhangs(mesh, threshold_degrees=55):
    """
    Finds triangles whose surface orientation suggests
    they may require support.

    This is a simplified first-pass analysis.
    """

    normals = mesh.face_normals

    # Z component of each normal
    z_components = np.clip(normals[:, 2], -1.0, 1.0)

    angles = np.degrees(np.arccos(np.abs(z_components)))

    overhang_faces = angles > threshold_degrees

    count = int(np.sum(overhang_faces))
    total = len(mesh.faces)

    percentage = 0.0

    if total > 0:
        percentage = (count / total) * 100

    return {
        "threshold_degrees": threshold_degrees,
        "overhang_faces": count,
        "total_faces": total,
        "overhang_percentage": round(percentage, 2),
    }