# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy"]
#
# [tool.orcaslicer.plugin]
# name = "EcoSlice"
# description = "AI-assisted material, energy, and strength optimization for functional 3D printing."
# author = "Saira Julka"
# version = "0.2.1"
# ///

from pathlib import Path
import traceback
import numpy as np
import orca


PLUGIN_VERSION = "0.2.1"

PLUGIN_DIR = Path(__file__).resolve().parent
UI_DIR = PLUGIN_DIR / "ui"


# ============================================================
# LOAD THE REAL ECO SLICE UI
# ============================================================

def load_ui():

    html_file = UI_DIR / "ecoslice.html"
    css_file = UI_DIR / "ecoslice.css"
    js_file = UI_DIR / "ecoslice.js"

    if not html_file.exists():
        raise FileNotFoundError(
            f"Missing {html_file}"
        )

    if not css_file.exists():
        raise FileNotFoundError(
            f"Missing {css_file}"
        )

    if not js_file.exists():
        raise FileNotFoundError(
            f"Missing {js_file}"
        )

    html = html_file.read_text(
        encoding="utf-8"
    )

    css = css_file.read_text(
        encoding="utf-8"
    )

    js = js_file.read_text(
        encoding="utf-8"
    )

    # We inject CSS/JS directly into the window.
    # This is much more reliable inside OrcaSlicer.

    html = html.replace(
        "</head>",
        f"""
<style>
{css}
</style>
</head>
""",
        1
    )

    html = html.replace(
        "</body>",
        f"""
<script>
{js}
</script>
</body>
""",
        1
    )

    return html


# ============================================================
# ECO SLICE ANALYZER
# ============================================================

class EcoAnalyzer:

    def __init__(self):
        self.last_result = None

    def analyze(self):

        model = orca.host.model()

        objects = model.objects()

        if not objects:
            raise RuntimeError(
                "No model is loaded in OrcaSlicer."
            )

        all_vertices = []
        all_triangles = []

        reports = []

        vertex_offset = 0

        # ----------------------------------------------------
        # READ ORCASLICER MODEL
        # ----------------------------------------------------

        for object_index, obj in enumerate(objects):

            for volume_index, volume in enumerate(
                obj.volumes()
            ):

                mesh = volume.mesh()

                if mesh.is_empty():
                    continue

                vertices = np.asarray(
                    mesh.vertices(),
                    dtype=np.float64
                )

                triangles = np.asarray(
                    mesh.triangles(),
                    dtype=np.int32
                )

                if len(vertices) == 0:
                    continue

                # Convert model to world coordinates.
                try:

                    instance = obj.instance(0)

                    matrix = (
                        instance.matrix()
                        @ volume.matrix()
                    )

                    homogeneous = np.c_[
                        vertices,
                        np.ones(len(vertices))
                    ]

                    world_vertices = (
                        homogeneous
                        @ matrix.T
                    )[:, :3]

                except Exception:

                    world_vertices = vertices

                world_triangles = (
                    triangles
                    + vertex_offset
                )

                all_vertices.append(
                    world_vertices
                )

                all_triangles.append(
                    world_triangles
                )

                vertex_offset += len(
                    world_vertices
                )

                reports.append({
                    "name": getattr(
                        volume,
                        "name",
                        f"Object {object_index + 1}"
                    ),

                    "volume_mm3": float(
                        mesh.volume()
                    ),

                    "triangles": int(
                        mesh.triangle_count()
                    ),

                    "manifold": bool(
                        mesh.is_manifold()
                    )
                })

        if not all_vertices:

            raise RuntimeError(
                "No mesh geometry was found."
            )

        vertices = np.vstack(
            all_vertices
        )

        triangles = np.vstack(
            all_triangles
        )

        # ----------------------------------------------------
        # GEOMETRY
        # ----------------------------------------------------

        minimum = vertices.min(
            axis=0
        )

        maximum = vertices.max(
            axis=0
        )

        dimensions = (
            maximum - minimum
        )

        volume = sum(
            r["volume_mm3"]
            for r in reports
        )

        # ----------------------------------------------------
        # TRIANGLE NORMALS
        # ----------------------------------------------------

        tri_vertices = vertices[
            triangles
        ]

        edge_a = (
            tri_vertices[:, 1]
            - tri_vertices[:, 0]
        )

        edge_b = (
            tri_vertices[:, 2]
            - tri_vertices[:, 0]
        )

        normals = np.cross(
            edge_a,
            edge_b
        )

        lengths = np.linalg.norm(
            normals,
            axis=1
        )

        lengths[lengths == 0] = 1

        normals /= lengths[:, None]

        # ----------------------------------------------------
        # SUPPORT RISK
        # ----------------------------------------------------

        downward = -normals[:, 2]

        support_mask = (
            downward > 0.5
        )

        support_ratio = (
            float(
                np.mean(support_mask)
            )
            if len(support_mask)
            else 0
        )

        support_risk = min(
            99,
            support_ratio * 100
        )

        # ----------------------------------------------------
        # VISUAL STRESS HEURISTIC
        #
        # This is NOT FEA.
        # It is a visualization heuristic.
        # ----------------------------------------------------

        centers = tri_vertices.mean(
            axis=1
        )

        z_min = minimum[2]

        z_range = max(
            0.001,
            maximum[2] - z_min
        )

        height = (
            centers[:, 2] - z_min
        ) / z_range

        stress = (
            0.55
            * np.clip(
                downward,
                0,
                1
            )
            +
            0.25 * height
            +
            0.20
            * np.abs(
                normals[:, 0]
            )
        )

        stress = np.clip(
            stress,
            0,
            1
        )

        # ----------------------------------------------------
        # SUPPORT VISUALIZATION
        # ----------------------------------------------------

        supports = []

        support_indices = np.where(
            support_mask
        )[0]

        max_supports = 80

        if len(support_indices) > max_supports:

            indices = np.linspace(
                0,
                len(support_indices) - 1,
                max_supports
            ).astype(int)

            support_indices = (
                support_indices[indices]
            )

        bottom_z = float(
            vertices[:, 2].min()
        )

        for i in support_indices:

            triangle = triangles[i]

            top = vertices[
                triangle
            ].mean(axis=0)

            supports.append({
                "top": [
                    round(float(top[0]), 2),
                    round(float(top[1]), 2),
                    round(float(top[2]), 2)
                ],

                "bottom": [
                    round(float(top[0]), 2),
                    round(float(top[1]), 2),
                    round(bottom_z, 2)
                ]
            })

        # ----------------------------------------------------
        # SEND A LIGHTWEIGHT MESH TO THE UI
        # ----------------------------------------------------

        max_triangles = 4500

        if len(triangles) > max_triangles:

            indices = np.linspace(
                0,
                len(triangles) - 1,
                max_triangles
            ).astype(int)

        else:

            indices = np.arange(
                len(triangles)
            )

        browser_vertices = []
        browser_stress = []

        for i in indices:

            tri = triangles[i]

            browser_vertices.extend([
                vertices[tri[0]].tolist(),
                vertices[tri[1]].tolist(),
                vertices[tri[2]].tolist()
            ])

            s = float(
                stress[i]
            )

            browser_stress.extend([
                s,
                s,
                s
            ])

        # ----------------------------------------------------
        # OPTIMIZATION PROFILES
        # ----------------------------------------------------

        base_material = (
            volume / 1000
        ) * 0.00124

        base_material *= (
            1
            + support_risk / 200
        )

        base_time = (
            0.25
            + volume / 250000
        )

        base_time *= (
            1
            + support_risk / 150
        )

        definitions = [

            (
                "eco",
                "Eco",
                "MINIMUM RESOURCE",
                2,
                12,
                0.72,
                0.71
            ),

            (
                "balanced",
                "Balanced",
                "RECOMMENDED",
                4,
                30,
                1.00,
                0.87
            ),

            (
                "maximum",
                "Maximum Strength",
                "STRUCTURAL",
                6,
                55,
                1.43,
                0.96
            )
        ]

        profiles = []

        for (
            profile_id,
            name,
            tag,
            walls,
            infill,
            multiplier,
            confidence
        ) in definitions:

            material = (
                base_material
                * multiplier
            )

            time = (
                base_time
                * multiplier
            )

            energy = (
                time * 0.12
            )

            co2 = (
                energy * 0.38
            )

            profiles.append({

                "id": profile_id,

                "name": name,

                "tag": tag,

                "walls": walls,

                "infill": infill,

                "material_g": round(
                    material,
                    2
                ),

                "time_h": round(
                    time,
                    2
                ),

                "time_hours": round(
                    time,
                    2
                ),

                "energy_kwh": round(
                    energy,
                    2
                ),

                "co2_kg": round(
                    co2,
                    3
                ),

                "confidence": round(
                    confidence * 100
                ),

                "strength_confidence":
                    round(
                        confidence * 100
                    )
            })

        # ----------------------------------------------------
        # RECOMMENDATIONS
        # ----------------------------------------------------

        changes = []

        if float(
            stress.max()
        ) > 0.8:

            changes.append({
                "severity": "critical",

                "title":
                    "Reinforce high-stress regions",

                "body":
                    "EcoSlice identifies regions "
                    "that may benefit from additional "
                    "wall thickness or infill density."
            })

        if support_risk > 10:

            changes.append({
                "severity": "medium",

                "title":
                    "Localize support material",

                "body":
                    "Downward-facing regions above "
                    "the support threshold are shown "
                    "as support candidates."
            })

        changes.append({
            "severity": "medium",

            "title":
                "Compare print strategies",

            "body":
                "EcoSlice compares material, estimated "
                "print time, energy consumption, and "
                "structural confidence."
        })

        # ----------------------------------------------------
        # FINAL DATA SENT TO JAVASCRIPT
        # ----------------------------------------------------

        result = {

            "version":
                PLUGIN_VERSION,

            "objects":
                reports,

            "geometry": {

                "volume_mm3":
                    round(volume, 2),

                "triangles":
                    int(len(triangles)),

                "dimensions_mm": [
                    round(
                        float(x),
                        2
                    )
                    for x in dimensions
                ],

                "support_risk":
                    round(
                        support_risk,
                        1
                    ),

                "manifold":
                    all(
                        r["manifold"]
                        for r in reports
                    ),

                "thin_feature_warning":
                    float(
                        np.min(dimensions)
                    ) < 1.2
            },

            "analysis": {

                "overhang_faces":
                    int(
                        np.sum(
                            support_mask
                        )
                    ),

                "stress_max":
                    round(
                        float(
                            stress.max()
                        ),
                        3
                    ),

                "stress_mean":
                    round(
                        float(
                            stress.mean()
                        ),
                        3
                    ),

                "support_points":
                    len(supports)
            },

            "mesh": {

                "vertices": [
                    [
                        round(
                            float(v[0]),
                            2
                        ),
                        round(
                            float(v[1]),
                            2
                        ),
                        round(
                            float(v[2]),
                            2
                        )
                    ]
                    for v in browser_vertices
                ],

                "stress": [
                    round(
                        float(x),
                        3
                    )
                    for x in browser_stress
                ]
            },

            "supports":
                supports,

            "profiles":
                profiles,

            "changes":
                changes
        }

        self.last_result = result

        return result


# ============================================================
# THE ONE ECO SLICE CAPABILITY
# ============================================================

class EcoSliceOptimizer(
    orca.script.ScriptPluginCapabilityBase
):

    def __init__(self):

        self.window = None

        self.analyzer = (
            EcoAnalyzer()
        )

    def get_name(self):

        return "EcoSlice Optimizer"

    def execute(self):

        try:

            page = load_ui()

            self.window = (
                orca.host.ui.create_window(
                    html=page,

                    title=(
                        "EcoSlice — "
                        "AI Manufacturing Copilot"
                    ),

                    width=1380,

                    height=900,

                    on_message=
                        self.on_message,

                    on_close=
                        self.on_close
                )
            )

            # Automatically analyze the
            # current OrcaSlicer model.

            result = (
                self.analyzer.analyze()
            )

            self.window.post({

                "type":
                    "analysis",

                "data":
                    result
            })

            return (
                orca.ExecutionResult.success(
                    "EcoSlice Optimizer opened."
                )
            )

        except Exception as exc:

            traceback.print_exc()

            return (
                orca.ExecutionResult.failure(
                    orca.PluginResult.RecoverableError,
                    f"EcoSlice failed: {exc}"
                )
            )

    def on_message(self, data):

        if not data:
            return

        message_type = data.get(
            "type"
        )

        # ----------------------------------------------------
        # ANALYZE
        # ----------------------------------------------------

        if message_type == "analyze":

            try:

                if self.window:

                    self.window.post({
                        "type":
                            "status",

                        "message":
                            "Analyzing current model..."
                    })

                result = (
                    self.analyzer.analyze()
                )

                if self.window:

                    self.window.post({

                        "type":
                            "analysis",

                        "data":
                            result
                    })

            except Exception as exc:

                traceback.print_exc()

                if self.window:

                    self.window.post({

                        "type":
                            "error",

                        "message":
                            str(exc)
                    })

        # ----------------------------------------------------
        # SELECT PROFILE
        # ----------------------------------------------------

        elif message_type == "select_profile":

            profile = data.get(
                "profile",
                "balanced"
            )

            print(
                "EcoSlice selected:",
                profile
            )

            if self.window:

                self.window.post({

                    "type":
                        "status",

                    "message":
                        f"{profile.title()} "
                        "profile selected."
                })

        # ----------------------------------------------------
        # OPTIMIZE
        # ----------------------------------------------------

        elif message_type == "optimize":

            profile = data.get(
                "profile",
                "balanced"
            )

            print(
                "EcoSlice optimization:",
                profile
            )

            if self.window:

                self.window.post({

                    "type":
                        "status",

                    "message":
                        "Optimization profile selected. "
                        "Ready for slicing."
                })

    def on_close(self):

        self.window = None


# ============================================================
# REGISTER ONLY THIS CAPABILITY
# ============================================================

@orca.plugin
class EcoSlicePlugin(orca.base):

    def register_capabilities(self):

        orca.register_capability(
            EcoSliceOptimizer
        )