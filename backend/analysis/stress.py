import numpy as np


def estimate_stress_regions(mesh):
    """
    Simplified heuristic stress analysis.

    This is NOT a replacement for FEA.
    It identifies geometry that may deserve
    reinforcement.
    """

    vertices = mesh.vertices

    center = np.mean(vertices, axis=0)

    distances = np.linalg.norm(
        vertices - center,
        axis=1
    )

    # Normalize distance
    if distances.max() > 0:
        normalized = distances / distances.max()
    else:
        normalized = distances

    high_stress_vertices = np.where(
        normalized > 0.75
    )[0]

    return {
        "estimated_high_stress_vertices": int(
            len(high_stress_vertices)
        ),
        "total_vertices": int(len(vertices)),
        "stress_model": "geometry_heuristic_v1"
    }