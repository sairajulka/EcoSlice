# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy"]
#
# [tool.orcaslicer.plugin]
# name = "EcoSlice"
# description = "AI-assisted material, energy, and strength optimization for functional 3D printing."
# author = "Saira Julka"
# version = "0.2.2"
# ///

import json
import math
import re
import traceback
from pathlib import Path

import numpy as np
import orca


PLUGIN_VERSION = "0.2.2"


# ============================================================
# HELPERS
# ============================================================

def clamp(value, low, high):
    return max(low, min(high, value))


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


# ============================================================
# INTENT PARSER
# ============================================================

def parse_intent(text):
    text = text or ""
    lower = text.lower()

    priority = "balanced"

    if any(word in lower for word in [
        "strength",
        "strong",
        "durability",
        "load bearing",
        "structural",
    ]):
        priority = "strength"

    if any(word in lower for word in [
        "appearance",
        "looks",
        "cosmetic",
    ]):
        priority = "appearance"

    load_kg = None

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(kg|kilogram|kilograms)",
        lower,
    )

    if match:
        load_kg = float(match.group(1))

    outdoor = any(
        word in lower
        for word in [
            "outdoor",
            "outside",
            "weather",
            "rain",
        ]
    )

    vibration = any(
        word in lower
        for word in [
            "vibration",
            "vibrating",
            "shock",
            "impact",
        ]
    )

    cantilever = any(
        word in lower
        for word in [
            "cantilever",
            "cantilevered",
        ]
    )

    return {
        "description": text,
        "priority": priority,
        "load_kg": load_kg,
        "outdoor": outdoor,
        "vibration": vibration,
        "cantilever": cantilever,
        "strength_priority": priority == "strength",
        "appearance_priority": priority == "appearance",
    }


# ============================================================
# MESH ANALYSIS
# ============================================================

def analyze_mesh(mesh):

    vertices = np.asarray(
        mesh.vertices(),
        dtype=np.float64,
    )

    triangles = np.asarray(
        mesh.triangles(),
        dtype=np.int64,
    )

    if len(vertices) == 0 or len(triangles) == 0:
        return None

    p0 = vertices[triangles[:, 0]]
    p1 = vertices[triangles[:, 1]]
    p2 = vertices[triangles[:, 2]]

    edge_a = p1 - p0
    edge_b = p2 - p0

    normals = np.cross(edge_a, edge_b)

    normal_lengths = np.linalg.norm(
        normals,
        axis=1,
    )

    valid = normal_lengths > 1e-12

    normalized_normals = np.zeros_like(normals)

    normalized_normals[valid] = (
        normals[valid]
        / normal_lengths[valid, None]
    )

    areas = 0.5 * normal_lengths

    surface_area = float(
        np.sum(areas)
    )

    # --------------------------------------------------------
    # Overhang detection
    # --------------------------------------------------------

    z_normal = normalized_normals[:, 2]

    downward = z_normal < 0

    # Faces whose normals point substantially downward.
    critical = (
        downward
        & (
            z_normal
            < -math.cos(math.radians(45))
        )
    )

    severe = (
        downward
        & (
            z_normal
            < -math.cos(math.radians(60))
        )
    )

    critical_area = float(
        np.sum(areas[critical])
    )

    severe_area = float(
        np.sum(areas[severe])
    )

    overhang_ratio = (
        critical_area / surface_area
        if surface_area > 0
        else 0
    )

    severe_ratio = (
        severe_area / surface_area
        if surface_area > 0
        else 0
    )

    support_risk = clamp(
        (
            overhang_ratio * 100 * 1.8
            + severe_ratio * 100 * 1.2
        ),
        0,
        99,
    )

    if support_risk < 20:
        risk_label = "LOW"
    elif support_risk < 50:
        risk_label = "MEDIUM"
    elif support_risk < 75:
        risk_label = "HIGH"
    else:
        risk_label = "VERY HIGH"

    # --------------------------------------------------------
    # Bounding box
    # --------------------------------------------------------

    minimum = vertices.min(axis=0)
    maximum = vertices.max(axis=0)

    dimensions = maximum - minimum

    smallest_dimension = float(
        np.min(dimensions)
    )

    thin_feature_warning = (
        smallest_dimension < 1.2
    )

    # --------------------------------------------------------
    # Volume
    # --------------------------------------------------------

    try:
        volume = float(mesh.volume())
    except Exception:

        try:
            volume = abs(
                float(
                    np.sum(
                        np.einsum(
                            "ij,ij->i",
                            p0,
                            np.cross(p1, p2),
                        )
                    )
                    / 6.0
                )
            )
        except Exception:
            volume = 0.0

    try:
        manifold = bool(
            mesh.is_manifold()
        )
    except Exception:
        manifold = True

    return {
        "vertices": int(len(vertices)),
        "triangles": int(len(triangles)),
        "volume_mm3": volume,
        "dimensions_mm": [
            float(x)
            for x in dimensions
        ],
        "surface_area_mm2": surface_area,
        "critical_overhang_area_mm2":
            critical_area,
        "severe_overhang_area_mm2":
            severe_area,
        "overhang_ratio":
            overhang_ratio,
        "support_risk":
            support_risk,
        "risk_label":
            risk_label,
        "thin_feature_warning":
            thin_feature_warning,
        "manifold":
            manifold,
        "vertices_raw":
            vertices,
        "triangles_raw":
            triangles,
        "normals_raw":
            normalized_normals,
    }


# ============================================================
# STRESS HEURISTIC
# ============================================================

def calculate_stress(
    vertices,
    triangles,
    normals,
):

    triangle_vertices = vertices[triangles]

    centers = triangle_vertices.mean(
        axis=1
    )

    z_min = float(vertices[:, 2].min())
    z_max = float(vertices[:, 2].max())

    z_range = max(
        0.001,
        z_max - z_min,
    )

    normalized_height = (
        centers[:, 2] - z_min
    ) / z_range

    downward = np.clip(
        -normals[:, 2],
        0,
        1,
    )

    stress = (
        0.55 * downward
        + 0.25 * normalized_height
        + 0.20 * np.abs(normals[:, 0])
    )

    return np.clip(
        stress,
        0,
        1,
    )


# ============================================================
# SUPPORT GENERATION
# ============================================================

def generate_supports(
    vertices,
    triangles,
    normals,
    max_supports=80,
):

    downward = (
        -normals[:, 2]
    )

    support_mask = (
        downward > 0.5
    )

    indices = np.where(
        support_mask
    )[0]

    if len(indices) == 0:
        return []

    if len(indices) > max_supports:

        sample_indices = np.linspace(
            0,
            len(indices) - 1,
            max_supports,
        ).astype(int)

        indices = indices[
            sample_indices
        ]

    bottom_z = float(
        vertices[:, 2].min()
    )

    supports = []

    for triangle_index in indices:

        triangle = triangles[
            triangle_index
        ]

        point = vertices[
            triangle
        ].mean(axis=0)

        bottom = np.array([
            point[0],
            point[1],
            bottom_z,
        ])

        supports.append({
            "top": [
                round(float(point[0]), 2),
                round(float(point[1]), 2),
                round(float(point[2]), 2),
            ],
            "bottom": [
                round(float(bottom[0]), 2),
                round(float(bottom[1]), 2),
                round(float(bottom[2]), 2),
            ],
        })

    return supports


# ============================================================
# BROWSER MESH SAMPLING
# ============================================================

def sample_mesh(
    vertices,
    triangles,
    stress,
    max_triangles=4500,
):

    triangle_count = len(
        triangles
    )

    if triangle_count == 0:
        return {
            "vertices": [],
            "stress": [],
        }

    if triangle_count <= max_triangles:

        indices = np.arange(
            triangle_count
        )

    else:

        indices = np.linspace(
            0,
            triangle_count - 1,
            max_triangles,
        ).astype(int)

    output_vertices = []
    output_stress = []

    for index in indices:

        triangle = triangles[index]

        output_vertices.extend([
            vertices[triangle[0]].tolist(),
            vertices[triangle[1]].tolist(),
            vertices[triangle[2]].tolist(),
        ])

        value = float(
            stress[index]
        )

        output_stress.extend([
            value,
            value,
            value,
        ])

    return {
        "vertices": [
            [
                round(float(x), 2)
                for x in vertex
            ]
            for vertex in output_vertices
        ],
        "stress": [
            round(float(x), 3)
            for x in output_stress
        ],
    }


# ============================================================
# OPTIMIZATION PROFILES
# ============================================================

def generate_profiles(
    volume_mm3,
    support_risk,
    intent,
):

    definitions = [
        (
            "eco",
            "Eco",
            "MINIMUM RESOURCE",
            2,
            12,
            0.72,
            0.71,
        ),
        (
            "balanced",
            "Balanced",
            "RECOMMENDED",
            4,
            30,
            1.00,
            0.87,
        ),
        (
            "maximum",
            "Maximum Strength",
            "STRUCTURAL",
            6,
            55,
            1.43,
            0.96,
        ),
    ]

    # Strength-focused jobs should favor
    # the stronger profiles.
    if intent.get(
        "strength_priority",
        False,
    ):

        definitions = [
            (
                "eco",
                "Eco",
                "LOW RESOURCE",
                2,
                12,
                0.72,
                0.67,
            ),
            (
                "balanced",
                "Balanced",
                "RECOMMENDED",
                4,
                30,
                1.00,
                0.87,
            ),
            (
                "maximum",
                "Maximum Strength",
                "BEST STRENGTH",
                6,
                55,
                1.43,
                0.96,
            ),
        ]

    # Approximate PLA density.
    density = 1.24

    # Approximate amount of printed material
    # relative to solid volume.
    complexity_factor = (
        1.0
        + support_risk / 200.0
    )

    profiles = []

    for (
        profile_id,
        name,
        tag,
        walls,
        infill,
        multiplier,
        confidence,
    ) in definitions:

        utilization = (
            0.18
            + infill / 100.0 * 0.55
            + walls * 0.035
        )

        utilization = clamp(
            utilization,
            0.18,
            0.95,
        )

        material_cm3 = (
            volume_mm3 / 1000.0
        ) * utilization

        material_g = (
            material_cm3
            * density
            * complexity_factor
            * multiplier
        )

        base_time = (
            0.20
            + volume_mm3 / 250000.0
        )

        time_hours = (
            base_time
            * multiplier
            * (
                1
                + support_risk / 150
            )
        )

        energy_kwh = (
            time_hours * 0.12
        )

        co2_kg = (
            energy_kwh * 0.38
        )

        profiles.append({
            "id": profile_id,
            "name": name,
            "tag": tag,
            "description": {
                "eco":
                    "Minimize material and print time.",
                "balanced":
                    "Balance strength, material, and time.",
                "maximum":
                    "Prioritize structural robustness.",
            }[profile_id],
            "walls": walls,
            "infill": infill,
            "material_g":
                round(material_g, 2),
            "time_h":
                round(time_hours, 2),
            "energy_kwh":
                round(energy_kwh, 2),
            "co2_kg":
                round(co2_kg, 3),
            "confidence":
                round(confidence * 100),
        })

    return profiles


# ============================================================
# COMPLETE ANALYSIS
# ============================================================

class EcoAnalyzer:

    def __init__(self):

        self.last_snapshot = None

    def analyze_current_model(
        self,
        intent_text="",
    ):

        model = orca.host.model()

        if model is None:
            raise RuntimeError(
                "EcoSlice could not access the current OrcaSlicer model."
            )

        objects = model.objects()

        if not objects:
            raise RuntimeError(
                "No model is loaded in OrcaSlicer."
            )

        all_vertices = []
        all_triangles = []

        object_reports = []

        vertex_offset = 0

        total_volume = 0.0

        # --------------------------------------------------------
        # Extract all model geometry
        # --------------------------------------------------------

        for object_index, obj in enumerate(
            objects
        ):

            object_volume = 0.0
            object_triangles = 0

            try:
                object_name = obj.name
            except Exception:
                object_name = (
                    f"Object {object_index + 1}"
                )

            for volume_index, volume in enumerate(
                obj.volumes()
            ):

                mesh = volume.mesh()

                if mesh is None:
                    continue

                try:
                    if mesh.is_empty():
                        continue
                except Exception:
                    pass

                vertices = np.asarray(
                    mesh.vertices(),
                    dtype=np.float64,
                )

                triangles = np.asarray(
                    mesh.triangles(),
                    dtype=np.int64,
                )

                if (
                    len(vertices) == 0
                    or len(triangles) == 0
                ):
                    continue

                # --------------------------------------------
                # World coordinates
                # --------------------------------------------

                try:

                    instance = obj.instance(0)

                    world_matrix = (
                        instance.matrix()
                        @ volume.matrix()
                    )

                    homogeneous = np.c_[
                        vertices,
                        np.ones(
                            len(vertices)
                        ),
                    ]

                    world_vertices = (
                        homogeneous
                        @ np.asarray(
                            world_matrix,
                            dtype=np.float64,
                        ).T
                    )[:, :3]

                except Exception:

                    world_vertices = vertices

                triangles_global = (
                    triangles
                    + vertex_offset
                )

                all_vertices.append(
                    world_vertices
                )

                all_triangles.append(
                    triangles_global
                )

                vertex_offset += len(
                    world_vertices
                )

                try:
                    volume_value = float(
                        mesh.volume()
                    )
                except Exception:
                    volume_value = 0.0

                triangle_count = len(
                    triangles
                )

                object_volume += (
                    volume_value
                )

                object_triangles += (
                    triangle_count
                )

            total_volume += (
                object_volume
            )

            object_reports.append({
                "name": object_name,
                "volume_mm3":
                    round(
                        object_volume,
                        2,
                    ),
                "triangles":
                    object_triangles,
            })

        if not all_vertices:
            raise RuntimeError(
                "The current OrcaSlicer model contains no usable mesh geometry."
            )

        vertices = np.vstack(
            all_vertices
        )

        triangles = np.vstack(
            all_triangles
        )

        # --------------------------------------------------------
        # Overall dimensions
        # --------------------------------------------------------

        minimum = vertices.min(
            axis=0
        )

        maximum = vertices.max(
            axis=0
        )

        dimensions = (
            maximum - minimum
        )

        # --------------------------------------------------------
        # Normals
        # --------------------------------------------------------

        triangle_vertices = (
            vertices[triangles]
        )

        edge_a = (
            triangle_vertices[:, 1]
            - triangle_vertices[:, 0]
        )

        edge_b = (
            triangle_vertices[:, 2]
            - triangle_vertices[:, 0]
        )

        normals = np.cross(
            edge_a,
            edge_b,
        )

        lengths = np.linalg.norm(
            normals,
            axis=1,
        )

        lengths[
            lengths < 1e-12
        ] = 1

        normals = (
            normals
            / lengths[:, None]
        )

        # --------------------------------------------------------
        # Support analysis
        # --------------------------------------------------------

        downward = -normals[:, 2]

        support_mask = (
            downward > 0.5
        )

        support_ratio = (
            float(
                np.mean(
                    support_mask
                )
            )
            if len(support_mask)
            else 0.0
        )

        support_risk = min(
            99.0,
            support_ratio * 100.0,
        )

        # --------------------------------------------------------
        # Stress heuristic
        # --------------------------------------------------------

        stress = calculate_stress(
            vertices,
            triangles,
            normals,
        )

        # --------------------------------------------------------
        # Supports
        # --------------------------------------------------------

        supports = generate_supports(
            vertices,
            triangles,
            normals,
        )

        # --------------------------------------------------------
        # Intent
        # --------------------------------------------------------

        intent = parse_intent(
            intent_text
        )

        # --------------------------------------------------------
        # Profiles
        # --------------------------------------------------------

        profiles = generate_profiles(
            total_volume,
            support_risk,
            intent,
        )

        # --------------------------------------------------------
        # Browser mesh
        # --------------------------------------------------------

        browser_mesh = sample_mesh(
            vertices,
            triangles,
            stress,
            max_triangles=4500,
        )

        # --------------------------------------------------------
        # Recommendations
        # --------------------------------------------------------

        changes = []

        if support_risk > 20:

            changes.append({
                "severity": "medium",
                "title":
                    "Reduce support-heavy geometry",
                "body":
                    "EcoSlice identified downward-facing regions that may require support. Orientation and localized support placement could reduce material and print time.",
            })

        if support_risk > 50:

            changes.append({
                "severity": "critical",
                "title":
                    "Evaluate print orientation",
                "body":
                    "The current orientation produces substantial support risk. EcoSlice recommends testing alternative orientations before committing to the print.",
            })

        if stress.max() > 0.8:

            changes.append({
                "severity": "critical",
                "title":
                    "Reinforce high-stress regions",
                "body":
                    "The heuristic stress visualization identifies regions where additional walls or infill may improve robustness.",
            })

        changes.append({
            "severity": "low",
            "title":
                "Use targeted infill",
            "body":
                "Higher density can be reserved for important load paths rather than increasing infill throughout the entire part.",
        })

        changes.append({
            "severity": "low",
            "title":
                "Compare material and energy",
            "body":
                "EcoSlice compares estimated material, print time, energy, and CO₂e across optimization profiles.",
        })

        # --------------------------------------------------------
        # Final result
        # --------------------------------------------------------

        result = {
            "version":
                PLUGIN_VERSION,

            "geometry": {
                "volume_mm3":
                    round(
                        total_volume,
                        2,
                    ),

                "triangles":
                    int(
                        len(triangles)
                    ),

                "dimensions_mm": [
                    round(
                        float(x),
                        2,
                    )
                    for x in dimensions
                ],

                "support_risk":
                    round(
                        support_risk,
                        1,
                    ),

                "manifold":
                    True,
            },

            "objects":
                object_reports,

            "intent":
                intent,

            "mesh":
                browser_mesh,

            "supports":
                supports,

            "profiles":
                profiles,

            "changes":
                changes,

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
                        3,
                    ),

                "stress_mean":
                    round(
                        float(
                            stress.mean()
                        ),
                        3,
                    ),

                "support_points":
                    len(
                        supports
                    ),
            },
        }

        self.last_snapshot = result

        return result


# ============================================================
# LOAD UI FILES
# ============================================================

def load_ui():

    plugin_dir = Path(
        __file__
    ).resolve().parent

    ui_dir = (
        plugin_dir
        / "ui"
    )

    html_path = (
        ui_dir
        / "ecoslice.html"
    )

    css_path = (
        ui_dir
        / "ecoslice.css"
    )

    js_path = (
        ui_dir
        / "ecoslice.js"
    )

    if not html_path.exists():
        raise RuntimeError(
            f"EcoSlice UI not found: {html_path}"
        )

    if not css_path.exists():
        raise RuntimeError(
            f"EcoSlice CSS not found: {css_path}"
        )

    if not js_path.exists():
        raise RuntimeError(
            f"EcoSlice JavaScript not found: {js_path}"
        )

    html = html_path.read_text(
        encoding="utf-8"
    )

    css = css_path.read_text(
        encoding="utf-8"
    )

    js = js_path.read_text(
        encoding="utf-8"
    )

    # --------------------------------------------------------
    # Inline CSS
    # --------------------------------------------------------

    html = re.sub(
        r'<link[^>]+href=["\']ecoslice\.css["\'][^>]*>',
        f"<style>\n{css}\n</style>",
        html,
        flags=re.IGNORECASE,
    )

    # --------------------------------------------------------
    # Inline JavaScript
    # --------------------------------------------------------

    html = re.sub(
        r'<script[^>]+src=["\']ecoslice\.js["\'][^>]*>\s*</script>',
        f"<script>\n{js}\n</script>",
        html,
        flags=re.IGNORECASE,
    )

    # Also handle a script tag without
    # whitespace between tags.

    html = re.sub(
        r'<script[^>]+src=["\']ecoslice\.js["\'][^>]*></script>',
        f"<script>\n{js}\n</script>",
        html,
        flags=re.IGNORECASE,
    )

    return html


# ============================================================
# MAIN ORCASLICER CAPABILITY
# ============================================================

class EcoSliceOptimizer(
    orca.script.ScriptPluginCapabilityBase
):

    def __init__(self):

        # IMPORTANT:
        # OrcaSlicer requires the base capability
        # initializer to run when overriding __init__.
        super().__init__()

        self.window = None

        self.analyzer = (
            EcoAnalyzer()
        )

        self.selected_profile = None

    # --------------------------------------------------------
    # NAME
    # --------------------------------------------------------

    def get_name(self):

        return "EcoSlice Optimizer"

    # --------------------------------------------------------
    # OPEN UI
    # --------------------------------------------------------

    def execute(self):

        try:

            html = load_ui()

            self.window = (
                orca.host.ui.create_window(
                    html=html,
                    title=(
                        "EcoSlice — "
                        "AI Manufacturing Copilot"
                    ),
                    width=1380,
                    height=900,
                    on_message=(
                        self.on_message
                    ),
                    on_close=(
                        self.on_close
                    ),
                )
            )

            # ------------------------------------------------
            # Analyze immediately
            # ------------------------------------------------

            try:

                result = (
                    self.analyzer
                    .analyze_current_model(
                        ""
                    )
                )

                if self.window:

                    self.window.post({
                        "type": "analysis",
                        "data": result,
                    })

            except Exception as analysis_error:

                if self.window:

                    self.window.post({
                        "type": "error",
                        "message": str(
                            analysis_error
                        ),
                    })

            return (
                orca.ExecutionResult.success(
                    "EcoSlice optimizer opened."
                )
            )

        except Exception as exc:

            traceback.print_exc()

            return (
                orca.ExecutionResult.failure(
                    orca.PluginResult.RecoverableError,
                    (
                        "Could not open EcoSlice: "
                        f"{exc}"
                    ),
                )
            )

    # --------------------------------------------------------
    # JAVASCRIPT → PYTHON
    # --------------------------------------------------------

    def on_message(self, data):

        try:

            if not data:
                return

            message_type = data.get(
                "type"
            )

            # ==================================================
            # ANALYZE
            # ==================================================

            if message_type == "analyze":

                intent = data.get(
                    "intent",
                    "",
                )

                result = (
                    self.analyzer
                    .analyze_current_model(
                        intent
                    )
                )

                if self.window:

                    self.window.post({
                        "type": "analysis",
                        "data": result,
                    })

                return

            # ==================================================
            # SELECT PROFILE
            # ==================================================

            if message_type in (
                "select_profile",
                "select_option",
            ):

                profile = data.get(
                    "profile"
                )

                if profile is None:

                    index = int(
                        data.get(
                            "index",
                            0,
                        )
                    )

                    if (
                        self.analyzer.last_snapshot
                        and self.analyzer
                        .last_snapshot
                        .get("profiles")
                    ):

                        profiles = (
                            self.analyzer
                            .last_snapshot
                            ["profiles"]
                        )

                        if (
                            0 <= index
                            < len(profiles)
                        ):

                            profile = (
                                profiles[index]
                                .get("id")
                            )

                self.selected_profile = (
                    profile
                )

                print(
                    "EcoSlice selected profile:",
                    profile,
                )

                if self.window:

                    self.window.post({
                        "type": "status",
                        "message": (
                            "Optimization profile "
                            f"selected: {profile}. "
                            "Slicer-setting application "
                            "will be connected in the "
                            "slicing pipeline."
                        ),
                    })

                return

        except Exception as exc:

            traceback.print_exc()

            if self.window:

                try:

                    self.window.post({
                        "type": "error",
                        "message": str(exc),
                    })

                except Exception:
                    pass

    # --------------------------------------------------------
    # WINDOW CLOSED
    # --------------------------------------------------------

    def on_close(self):

        self.window = None


# ============================================================
# PLUGIN REGISTRATION
# ============================================================

@orca.plugin
class EcoSlicePlugin(
    orca.base
):

    def register_capabilities(self):

        orca.register_capability(
            EcoSliceOptimizer
        )