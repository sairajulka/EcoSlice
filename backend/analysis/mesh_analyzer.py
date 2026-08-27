import trimesh
import numpy as np


def load_mesh(file_path):
    mesh = trimesh.load_mesh(file_path)

    # Some STL files load as a Scene rather than a Mesh
    if isinstance(mesh, trimesh.Scene):
        mesh = trimesh.util.concatenate(
            [
                geometry
                for geometry in mesh.geometry.values()
                if isinstance(geometry, trimesh.Trimesh)
            ]
        )

    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError("Could not load a valid 3D mesh.")

    return mesh


def analyze_mesh(file_path):
    mesh = load_mesh(file_path)

    bounds = mesh.bounds

    dimensions = {
        "x_mm": float(bounds[1][0] - bounds[0][0]),
        "y_mm": float(bounds[1][1] - bounds[0][1]),
        "z_mm": float(bounds[1][2] - bounds[0][2]),
    }

    volume_mm3 = float(mesh.volume)
    surface_area_mm2 = float(mesh.area)

    return {
        "vertices": int(len(mesh.vertices)),
        "triangles": int(len(mesh.faces)),
        "volume_mm3": volume_mm3,
        "surface_area_mm2": surface_area_mm2,
        "dimensions": dimensions,
        "watertight": bool(mesh.is_watertight),
    }