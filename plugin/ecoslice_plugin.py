# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy"]
#
# [tool.orcaslicer.plugin]
# name = "EcoSlice"
# description = "AI-assisted material, strength, and energy optimization for functional 3D printing."
# author = "Saira Julka"
# version = "0.1.0"
# ///

import orca
import numpy as np


def analyze_mesh(mesh):
    """
    Analyze one OrcaSlicer TriangleMesh.

    Returns basic geometry information that EcoSlice can
    use as the foundation for later optimization.
    """

    vertices = np.asarray(mesh.vertices())
    triangles = np.asarray(mesh.triangles())

    # Basic geometry
    vertex_count = len(vertices)
    triangle_count = len(triangles)

    volume = float(mesh.volume())
    manifold = bool(mesh.is_manifold())

    bbox = mesh.bounding_box()

    dimensions = tuple(float(x) for x in bbox.size)

    return {
        "vertices": vertex_count,
        "triangles": triangle_count,
        "volume_mm3": volume,
        "dimensions_mm": dimensions,
        "manifold": manifold,
    }


class EcoSliceAnalysis(orca.script.ScriptPluginCapabilityBase):

    def get_name(self):
        return "Analyze Current Model"

    def execute(self):

        try:
            model = orca.host.model()

            objects = model.objects()

            if not objects:
                return orca.ExecutionResult.success(
                    "EcoSlice: No model is currently loaded."
                )

            report_lines = [
                "ECO SLICE ANALYSIS",
                "==================",
                ""
            ]

            total_volume = 0.0
            total_triangles = 0
            object_count = 0

            for object_index, obj in enumerate(objects):

                object_count += 1

                report_lines.append(
                    f"Object {object_index + 1}"
                )

                report_lines.append(
                    f"Name: {obj.name}"
                )

                for volume_index, volume in enumerate(obj.volumes()):

                    mesh = volume.mesh()

                    if mesh.is_empty():
                        continue

                    result = analyze_mesh(mesh)

                    total_volume += result["volume_mm3"]
                    total_triangles += result["triangles"]

                    x, y, z = result["dimensions_mm"]

                    report_lines.append(
                        f"  Volume {volume_index + 1}"
                    )

                    report_lines.append(
                        f"    Dimensions: "
                        f"{x:.2f} × {y:.2f} × {z:.2f} mm"
                    )

                    report_lines.append(
                        f"    Volume: "
                        f"{result['volume_mm3']:.2f} mm³"
                    )

                    report_lines.append(
                        f"    Triangles: "
                        f"{result['triangles']}"
                    )

                    report_lines.append(
                        f"    Watertight/manifold: "
                        f"{result['manifold']}"
                    )

                    report_lines.append("")

            report_lines.append(
                "------------------"
            )

            report_lines.append(
                f"Objects analyzed: {object_count}"
            )

            report_lines.append(
                f"Total mesh volume: {total_volume:.2f} mm³"
            )

            report_lines.append(
                f"Total triangles: {total_triangles}"
            )

            report_lines.append("")
            report_lines.append(
                "EcoSlice successfully read the model "
                "directly from OrcaSlicer."
            )

            message = "\n".join(report_lines)

            print(message)

            return orca.ExecutionResult.success(message)

        except Exception as error:

            error_message = (
                "EcoSlice analysis failed:\n"
                f"{type(error).__name__}: {error}"
            )

            print(error_message)

            return orca.ExecutionResult.recoverable_error(
                error_message
            )


@orca.plugin
class EcoSlicePlugin(orca.base):

    def register_capabilities(self):

        orca.register_capability(
            EcoSliceAnalysis
        )