# /// script
# dependencies = ["numpy"]
# ///

import json
import math
import traceback
from pathlib import Path

import numpy as np
import orca

PLUGIN_VERSION = "0.2.0"
# ============================================================
# EXTERNAL UI LOADER
# ============================================================

PLUGIN_DIR = Path(__file__).resolve().parent
UI_DIR = PLUGIN_DIR / "ui"


def load_ecoslice_ui():
    """
    Load the UI from:

        plugin/ui/ecoslice.html
        plugin/ui/ecoslice.css
        plugin/ui/ecoslice.js

    Then inject CSS and JS directly into the HTML so the
    OrcaSlicer plugin window can render everything as one page.
    """

    html_path = UI_DIR / "ecoslice.html"
    css_path = UI_DIR / "ecoslice.css"
    js_path = UI_DIR / "ecoslice.js"

    if not html_path.exists():
        raise RuntimeError(
            f"EcoSlice UI HTML not found: {html_path}"
        )

    if not css_path.exists():
        raise RuntimeError(
            f"EcoSlice CSS not found: {css_path}"
        )

    if not js_path.exists():
        raise RuntimeError(
            f"EcoSlice JavaScript not found: {js_path}"
        )

    html = html_path.read_text(encoding="utf-8")
    css = css_path.read_text(encoding="utf-8")
    js = js_path.read_text(encoding="utf-8")

    html = html.replace(
        "<!-- ECOSLICE_CSS -->",
        f"<style>\n{css}\n</style>"
    )

    html = html.replace(
        "<!-- ECOSLICE_JS -->",
        f"<script>\n{js}\n</script>"
    )

    return html

# ============================================================
# ECO SLICE ANALYSIS ENGINE
# ============================================================

class EcoAnalyzer:

    def __init__(self):
        self.last_snapshot = None

    def analyze_current_model(self):
        """
        Read the currently loaded OrcaSlicer model.

        IMPORTANT:
        OrcaSlicer's normal host API is read-only.
        We analyze a snapshot rather than modifying the model.
        """

        model = orca.host.model()

        objects = model.objects()

        if not objects:
            raise RuntimeError(
                "No model is loaded in OrcaSlicer."
            )

        all_vertices = []
        all_triangles = []

        object_reports = []

        vertex_offset = 0

        for object_index, obj in enumerate(objects):

            for volume_index, volume in enumerate(obj.volumes()):

                mesh = volume.mesh()

                if mesh.is_empty():
                    continue

                vertices = np.asarray(mesh.vertices())
                triangles = np.asarray(mesh.triangles())

                # ------------------------------------------------
                # Convert local mesh coordinates to world coords
                # ------------------------------------------------

                try:
                    instance = obj.instance(0)

                    world_matrix = (
                        instance.matrix() @ volume.matrix()
                    )

                    homogeneous = np.c_[
                        vertices.astype(np.float64),
                        np.ones(len(vertices))
                    ]

                    world_vertices = (
                        homogeneous @ world_matrix.T
                    )[:, :3]

                except Exception:
                    # Fallback to local coordinates
                    world_vertices = vertices.astype(
                        np.float64
                    )

                triangles_world = (
                    triangles.astype(np.int32)
                    + vertex_offset
                )

                all_vertices.append(world_vertices)
                all_triangles.append(triangles_world)

                vertex_offset += len(world_vertices)

                object_reports.append({
                    "name": getattr(
                        volume,
                        "name",
                        f"Object {object_index + 1}"
                    ),
                    "volume_mm3": float(mesh.volume()),
                    "triangles": int(mesh.triangle_count()),
                    "manifold": bool(mesh.is_manifold()),
                })

        if not all_vertices:
            raise RuntimeError(
                "The current OrcaSlicer model contains no mesh geometry."
            )

        vertices = np.vstack(all_vertices)
        triangles = np.vstack(all_triangles)

        # --------------------------------------------------------
        # Geometry statistics
        # --------------------------------------------------------

        minimum = vertices.min(axis=0)
        maximum = vertices.max(axis=0)

        dimensions = maximum - minimum

        volume_mm3 = 0.0

        for report in object_reports:
            volume_mm3 += report["volume_mm3"]

        # --------------------------------------------------------
        # Face normals
        # --------------------------------------------------------

        tri_vertices = vertices[triangles]

        edge_a = (
            tri_vertices[:, 1]
            - tri_vertices[:, 0]
        )

        edge_b = (
            tri_vertices[:, 2]
            - tri_vertices[:, 0]
        )

        normals = np.cross(edge_a, edge_b)

        normal_lengths = np.linalg.norm(
            normals,
            axis=1
        )

        normal_lengths[
            normal_lengths == 0
        ] = 1

        normals = (
            normals
            / normal_lengths[:, None]
        )

        # --------------------------------------------------------
        # Overhang analysis
        # --------------------------------------------------------

        # Z component tells us how downward-facing the face is.
        downward = -normals[:, 2]

        # Approximate overhang threshold:
        # 0.5 corresponds to roughly 60 degrees from horizontal.
        support_mask = downward > 0.5

        support_ratio = (
            float(np.mean(support_mask))
            if len(support_mask)
            else 0.0
        )

        support_risk = min(
            99.0,
            support_ratio * 100.0
        )

        # --------------------------------------------------------
        # Heuristic stress map
        #
        # THIS IS NOT FEA.
        #
        # It is a visualization heuristic based on:
        # - downward-facing geometry
        # - height
        # - local geometry
        #
        # Actual FEA/PINN comes later.
        # --------------------------------------------------------

        face_centers = tri_vertices.mean(axis=1)

        z_min = minimum[2]
        z_max = maximum[2]

        z_range = max(
            0.001,
            z_max - z_min
        )

        normalized_height = (
            face_centers[:, 2] - z_min
        ) / z_range

        stress = (
            0.55 * downward
            + 0.25 * normalized_height
            + 0.20 * np.abs(normals[:, 0])
        )

        stress = np.clip(
            stress,
            0,
            1
        )

        # --------------------------------------------------------
        # Support points
        # --------------------------------------------------------

        support_points = self.generate_support_points(
            vertices,
            triangles,
            normals,
            support_mask
        )

        # --------------------------------------------------------
        # Optimization estimates
        # --------------------------------------------------------

        profiles = self.generate_profiles(
            volume_mm3,
            support_risk,
            dimensions
        )

        # --------------------------------------------------------
        # Sample mesh for browser performance
        # --------------------------------------------------------

        sampled_triangles = self.sample_mesh(
            vertices,
            triangles,
            stress,
            max_triangles=4500
        )

        result = {
            "version": PLUGIN_VERSION,

            "geometry": {
                "volume_mm3": round(volume_mm3, 2),

                "triangles": int(
                    len(triangles)
                ),

                "dimensions_mm": [
                    round(float(x), 2)
                    for x in dimensions
                ],

                "support_risk": round(
                    support_risk,
                    1
                ),

                "manifold": all(
                    r["manifold"]
                    for r in object_reports
                )
            },

            "objects": object_reports,

            "mesh": sampled_triangles,

            "profiles": profiles,

            "changes": self.generate_changes(
                support_risk,
                stress
            ),

            "analysis": {
                "overhang_faces": int(
                    np.sum(support_mask)
                ),

                "stress_max": round(
                    float(stress.max()),
                    3
                ),

                "stress_mean": round(
                    float(stress.mean()),
                    3
                ),

                "support_points": len(
                    support_points
                )
            },

            "supports": support_points
        }

        self.last_snapshot = result

        return result

    # ==========================================================
    # SUPPORT GENERATION
    # ==========================================================

    def generate_support_points(
        self,
        vertices,
        triangles,
        normals,
        support_mask
    ):

        points = []

        if not np.any(support_mask):
            return points

        selected_triangles = np.where(
            support_mask
        )[0]

        # Don't try to display thousands of supports.
        # Pick representative regions.
        max_supports = 80

        if len(selected_triangles) > max_supports:

            indices = np.linspace(
                0,
                len(selected_triangles) - 1,
                max_supports
            ).astype(int)

            selected_triangles = (
                selected_triangles[indices]
            )

        for triangle_index in selected_triangles:

            tri = triangles[triangle_index]

            p = vertices[tri].mean(axis=0)

            # Project downward to approximate build plate.
            bottom_z = vertices[:, 2].min()

            bottom = np.array([
                p[0],
                p[1],
                bottom_z
            ])

            points.append({
                "top": [
                    round(float(p[0]), 2),
                    round(float(p[1]), 2),
                    round(float(p[2]), 2)
                ],

                "bottom": [
                    round(float(bottom[0]), 2),
                    round(float(bottom[1]), 2),
                    round(float(bottom[2]), 2)
                ]
            })

        return points

    # ==========================================================
    # MESH SAMPLING
    # ==========================================================

    def sample_mesh(
        self,
        vertices,
        triangles,
        stress,
        max_triangles=4500
    ):

        count = len(triangles)

        if count <= max_triangles:

            indices = np.arange(count)

        else:

            indices = np.linspace(
                0,
                count - 1,
                max_triangles
            ).astype(int)

        sampled_vertices = []
        sampled_stress = []

        for i in indices:

            tri = triangles[i]

            sampled_vertices.extend([
                vertices[tri[0]].tolist(),
                vertices[tri[1]].tolist(),
                vertices[tri[2]].tolist()
            ])

            value = float(stress[i])

            sampled_stress.extend([
                value,
                value,
                value
            ])

        return {
            "vertices": [
                [
                    round(float(v[0]), 2),
                    round(float(v[1]), 2),
                    round(float(v[2]), 2)
                ]
                for v in sampled_vertices
            ],

            "stress": [
                round(float(x), 3)
                for x in sampled_stress
            ]
        }

    # ==========================================================
    # OPTIMIZATION PROFILES
    # ==========================================================

    def generate_profiles(
        self,
        volume_mm3,
        support_risk,
        dimensions
    ):

        # Convert approximate plastic volume to grams.
        #
        # This is intentionally an estimate.
        # Later we should use actual filament density.
        base_material_g = (
            volume_mm3
            / 1000.0
            * 0.00124
        )

        complexity_factor = (
            1.0
            + support_risk / 200.0
        )

        base_material_g *= complexity_factor

        base_time = (
            0.25
            + volume_mm3 / 250000.0
        )

        base_time *= (
            1.0
            + support_risk / 150.0
        )

        profiles = []

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
                base_material_g
                * multiplier
            )

            time_hours = (
                base_time
                * multiplier
            )

            energy = (
                time_hours
                * 0.12
            )

            co2 = (
                energy
                * 0.38
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
                    time_hours,
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
                )
            })

        return profiles

    # ==========================================================
    # EXPLANATION ENGINE
    # ==========================================================

    def generate_changes(
        self,
        support_risk,
        stress
    ):

        changes = []

        if stress.max() > 0.8:

            changes.append({
                "severity": "critical",
                "title": "Reinforce high-stress regions",

                "body":
                    "EcoSlice identifies localized regions "
                    "that may benefit from additional wall "
                    "thickness or density."
            })

        if support_risk > 10:

            changes.append({
                "severity": "medium",
                "title": "Localize support material",

                "body":
                    "Only downward-facing regions above "
                    "the overhang threshold are candidates "
                    "for support."
            })

        changes.append({
            "severity": "medium",
            "title": "Use adaptive infill",

            "body":
                "Instead of applying one infill density "
                "to the entire model, EcoSlice recommends "
                "higher density near important load paths."
        })

        changes.append({
            "severity": "low",
            "title": "Optimize print orientation",

            "body":
                "EcoSlice can compare candidate orientations "
                "using overhang risk, support volume, and "
                "estimated print time."
        })

        return changes


# ============================================================
# HTML UI
# ============================================================

PAGE = r"""
<!DOCTYPE html>

<html>

<head>

<meta charset="utf-8">

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;

    background:
        #071216;

    color: #e8f7f4;

    overflow: hidden;
}

button,
textarea,
select {
    font-family: inherit;
}

button {
    cursor: pointer;
}

#app {
    display: grid;

    grid-template-columns:
        215px
        1fr;

    height: 100vh;
}

/* =========================================================
   SIDEBAR
   ========================================================= */

.sidebar {

    border-right:
        1px solid
        rgba(255,255,255,.08);

    padding: 24px 16px;

    background:
        #061014;
}

.logo {

    display: flex;

    align-items: center;

    gap: 10px;

    margin-bottom: 32px;
}

.logo-mark {

    width: 38px;
    height: 38px;

    border-radius: 12px;

    display: flex;

    align-items: center;
    justify-content: center;

    background:
        #3dd9b5;

    color: #03100e;

    font-weight: 900;
}

.logo-name {

    font-weight: 800;
    font-size: 18px;
}

.logo-sub {

    color: #6d8985;

    font-size: 10px;

    margin-top: 2px;
}

.nav {

    display: flex;

    flex-direction: column;

    gap: 8px;
}

.nav-item {

    padding: 12px;

    border-radius: 10px;

    color: #718984;

    font-size: 13px;
}

.nav-item.active {

    background:
        rgba(61,217,181,.10);

    color:
        #3dd9b5;

    border:
        1px solid
        rgba(61,217,181,.15);
}

.sidebar-bottom {

    position: absolute;

    bottom: 20px;

    left: 16px;

    color: #607773;

    font-size: 11px;
}

/* =========================================================
   MAIN
   ========================================================= */

.main {

    display: flex;

    flex-direction: column;

    min-width: 0;
}

.topbar {

    height: 66px;

    border-bottom:
        1px solid
        rgba(255,255,255,.07);

    display: flex;

    align-items: center;

    justify-content: space-between;

    padding: 0 24px;
}

.page-title {

    font-size: 14px;

    font-weight: 700;
}

.status {

    display: flex;

    align-items: center;

    gap: 8px;

    font-size: 11px;

    color: #7f9995;
}

.status-dot {

    width: 7px;
    height: 7px;

    border-radius: 50%;

    background: #3dd9b5;
}

/* =========================================================
   CONTENT
   ========================================================= */

.content {

    flex: 1;

    display: grid;

    grid-template-columns:
        minmax(450px, 1fr)
        390px;

    gap: 16px;

    padding: 16px;

    min-height: 0;
}

/* =========================================================
   MODEL
   ========================================================= */

.model-panel {

    position: relative;

    min-width: 0;

    min-height: 0;

    background:
        #09181d;

    border:
        1px solid
        rgba(255,255,255,.08);

    border-radius: 16px;

    overflow: hidden;
}

.model-header {

    height: 58px;

    display: flex;

    align-items: center;

    justify-content: space-between;

    padding: 0 18px;

    border-bottom:
        1px solid
        rgba(255,255,255,.06);
}

.model-name {

    font-weight: 700;
}

.model-sub {

    font-size: 10px;

    color: #66817d;

    margin-top: 3px;
}

.mode-buttons {

    display: flex;

    gap: 5px;
}

.mode {

    border:
        1px solid
        rgba(255,255,255,.09);

    background:
        rgba(255,255,255,.03);

    color: #78918d;

    padding:
        7px 10px;

    border-radius: 7px;

    font-size: 10px;
}

.mode.active {

    color: #3dd9b5;

    border-color:
        rgba(61,217,181,.35);

    background:
        rgba(61,217,181,.08);
}

#viewport {

    position: absolute;

    top: 58px;
    bottom: 92px;

    left: 0;
    right: 0;

    overflow: hidden;

    background:
        radial-gradient(
            circle at 50% 45%,
            rgba(34,101,104,.28),
            transparent 55%
        );
}

#canvas {

    width: 100%;
    height: 100%;

    display: block;
}

.viewport-hint {

    position: absolute;

    left: 16px;
    bottom: 104px;

    color: #607d78;

    font-size: 10px;
}

/* =========================================================
   MODEL STATS
   ========================================================= */

.model-stats {

    position: absolute;

    bottom: 0;

    left: 0;
    right: 0;

    height: 92px;

    display: grid;

    grid-template-columns:
        repeat(4,1fr);

    border-top:
        1px solid
        rgba(255,255,255,.07);

    background:
        rgba(5,16,20,.96);
}

.stat {

    padding:
        18px;

    border-right:
        1px solid
        rgba(255,255,255,.06);
}

.stat-label {

    font-size: 9px;

    color: #5f7774;

    text-transform:
        uppercase;

    letter-spacing:
        .08em;
}

.stat-value {

    margin-top: 7px;

    font-size: 13px;

    font-weight: 700;
}

/* =========================================================
   RIGHT PANEL
   ========================================================= */

.right {

    overflow-y: auto;

    padding-right: 2px;
}

.card {

    background:
        #0b1b20;

    border:
        1px solid
        rgba(255,255,255,.08);

    border-radius: 14px;

    padding: 16px;

    margin-bottom: 12px;
}

.eyebrow {

    font-size: 9px;

    color: #3dd9b5;

    font-weight: 800;

    letter-spacing:
        .14em;

    text-transform:
        uppercase;
}

h2 {

    margin:
        6px 0 6px;

    font-size: 18px;
}

.description {

    color: #78918d;

    font-size: 11px;

    line-height: 1.5;

    margin-bottom: 12px;
}

textarea {

    width: 100%;

    height: 95px;

    resize: none;

    border:
        1px solid
        rgba(255,255,255,.08);

    border-radius: 10px;

    background:
        #071318;

    color: #d9eeea;

    padding: 12px;

    outline: none;

    font-size: 11px;
}

textarea:focus {

    border-color:
        rgba(61,217,181,.5);
}

.primary {

    width: 100%;

    margin-top: 10px;

    border: none;

    border-radius: 10px;

    padding: 13px;

    background:
        linear-gradient(
            135deg,
            #3dd9b5,
            #55d6e5
        );

    color: #04100f;

    font-weight: 900;

    font-size: 12px;
}

/* =========================================================
   ENGINEERING CONTROLS
   ========================================================= */

.section-title {

    display: flex;

    justify-content: space-between;

    align-items: center;

    margin-bottom: 12px;

    font-size: 12px;

    font-weight: 800;
}

.badge {

    padding:
        4px 7px;

    border-radius: 6px;

    font-size: 8px;

    background:
        rgba(61,217,181,.08);

    color:
        #3dd9b5;
}

.control {

    display: flex;

    justify-content: space-between;

    align-items: center;

    padding: 10px 0;

    border-bottom:
        1px solid
        rgba(255,255,255,.05);
}

.control:last-child {

    border-bottom: none;
}

.control-name {

    font-size: 11px;
}

.control-value {

    color: #718b87;

    font-size: 10px;
}

/* =========================================================
   PROFILE CARDS
   ========================================================= */

.profile {

    border:
        1px solid
        rgba(255,255,255,.08);

    border-radius: 11px;

    padding: 12px;

    margin-top: 8px;

    background:
        rgba(255,255,255,.015);
}

.profile.recommended {

    border-color:
        rgba(61,217,181,.38);

    background:
        rgba(61,217,181,.04);
}

.profile-top {

    display: flex;

    justify-content: space-between;

    align-items: center;
}

.profile-name {

    font-size: 13px;

    font-weight: 800;
}

.profile-tag {

    font-size: 8px;

    color: #3dd9b5;

    font-weight: 800;
}

.profile-description {

    color: #718985;

    font-size: 10px;

    margin: 5px 0 10px;
}

.metrics {

    display: grid;

    grid-template-columns:
        repeat(3,1fr);

    gap: 6px;
}

.metric {

    background:
        #071318;

    padding: 8px;

    border-radius: 7px;
}

.metric-label {

    font-size: 8px;

    color: #58706d;
}

.metric-value {

    margin-top: 4px;

    font-size: 11px;

    font-weight: 700;
}

.select-profile {

    width: 100%;

    margin-top: 9px;

    padding: 8px;

    border-radius: 7px;

    background:
        transparent;

    color: #9db5b1;

    border:
        1px solid
        rgba(255,255,255,.08);

    font-size: 10px;
}

.profile.recommended
.select-profile {

    border-color:
        rgba(61,217,181,.35);

    color:
        #3dd9b5;
}

/* =========================================================
   CHANGES
   ========================================================= */

.change {

    display: flex;

    gap: 10px;

    padding: 9px 0;

    border-bottom:
        1px solid
        rgba(255,255,255,.05);
}

.change-dot {

    width: 7px;
    height: 7px;

    border-radius: 50%;

    margin-top: 4px;

    flex-shrink: 0;
}

.change-dot.critical {

    background: #ff756f;
}

.change-dot.medium {

    background: #e8c95c;
}

.change-dot.low {

    background: #3dd9b5;
}

.change-title {

    font-size: 10px;

    font-weight: 800;
}

.change-body {

    margin-top: 3px;

    color: #718984;

    font-size: 9px;

    line-height: 1.45;
}

/* =========================================================
   SUPPORT LEGEND
   ========================================================= */

.legend {

    display: flex;

    gap: 14px;

    font-size: 9px;

    color: #6f8884;
}

.legend-item {

    display: flex;

    gap: 5px;

    align-items: center;
}

.legend-dot {

    width: 7px;
    height: 7px;

    border-radius: 50%;
}

</style>

</head>

<body>

<div id="app">

    <aside class="sidebar">

        <div class="logo">

            <div class="logo-mark">
                E
            </div>

            <div>
                <div class="logo-name">
                    EcoSlice
                </div>

                <div class="logo-sub">
                    FUNCTIONAL PRINTING
                </div>
            </div>

        </div>

        <div class="nav">

            <div class="nav-item active">
                ◈ Workspace
            </div>

            <div class="nav-item">
                ◇ Analysis
            </div>

            <div class="nav-item">
                ◇ Compare
            </div>

            <div class="nav-item">
                ◇ Validation
            </div>

        </div>

        <div class="sidebar-bottom">

            <div>
                ● Prototype v0.2
            </div>

            <div style="margin-top:6px">
                AI manufacturing copilot
            </div>

        </div>

    </aside>


    <main class="main">

        <header class="topbar">

            <div class="page-title">
                EcoSlice Optimizer
            </div>

            <div class="status">

                <span class="status-dot"></span>

                Connected to OrcaSlicer

            </div>

        </header>


        <div class="content">


            <!-- ============================================
                 MODEL VIEW
                 ============================================ -->

            <section class="model-panel">

                <div class="model-header">

                    <div>

                        <div
                            class="model-name"
                            id="modelName"
                        >
                            Current OrcaSlicer Model
                        </div>

                        <div
                            class="model-sub"
                            id="modelSub"
                        >
                            Waiting for analysis
                        </div>

                    </div>


                    <div class="mode-buttons">

                        <button
                            class="mode active"
                            onclick="setMode('solid')"
                        >
                            Solid
                        </button>

                        <button
                            class="mode"
                            onclick="setMode('stress')"
                        >
                            Stress
                        </button>

                        <button
                            class="mode"
                            onclick="setMode('supports')"
                        >
                            Supports
                        </button>

                    </div>

                </div>


                <div id="viewport">

                    <canvas id="canvas"></canvas>

                    <div class="viewport-hint">

                        Drag to rotate · Scroll to zoom

                    </div>

                </div>


                <div class="model-stats">

                    <div class="stat">

                        <div class="stat-label">
                            Dimensions
                        </div>

                        <div
                            class="stat-value"
                            id="dimensions"
                        >
                            —
                        </div>

                    </div>


                    <div class="stat">

                        <div class="stat-label">
                            Volume
                        </div>

                        <div
                            class="stat-value"
                            id="volume"
                        >
                            —
                        </div>

                    </div>


                    <div class="stat">

                        <div class="stat-label">
                            Triangles
                        </div>

                        <div
                            class="stat-value"
                            id="triangles"
                        >
                            —
                        </div>

                    </div>


                    <div class="stat">

                        <div class="stat-label">
                            Support Risk
                        </div>

                        <div
                            class="stat-value"
                            id="supportRisk"
                        >
                            —
                        </div>

                    </div>

                </div>

            </section>


            <!-- ============================================
                 RIGHT SIDEBAR
                 ============================================ -->

            <section class="right">


                <!-- INTENT -->

                <div class="card">

                    <div class="eyebrow">
                        DESIGN INTENT
                    </div>

                    <h2>
                        What does this part need to do?
                    </h2>

                    <div class="description">

                        Describe the real-world job of the
                        part. EcoSlice uses this to influence
                        the optimization strategy.

                    </div>

                    <textarea
                        id="intent"
                        placeholder="Example: This is a bike-light mount attached to a tube. It carries a 1 kg light outdoors and experiences vibration while riding."
                    ></textarea>

                    <button
                        class="primary"
                        onclick="analyze()"
                    >
                        Analyze & Optimize
                    </button>

                </div>


                <!-- ENGINEERING -->

                <div class="card">

                    <div class="section-title">

                        <span>
                            ENGINEERING ANALYSIS
                        </span>

                        <span class="badge">
                            LIVE MODEL
                        </span>

                    </div>

                    <div class="control">

                        <span class="control-name">
                            Overhang analysis
                        </span>

                        <span
                            class="control-value"
                            id="overhang"
                        >
                            —
                        </span>

                    </div>

                    <div class="control">

                        <span class="control-name">
                            Stress map
                        </span>

                        <span
                            class="control-value"
                            id="stress"
                        >
                            —
                        </span>

                    </div>

                    <div class="control">

                        <span class="control-name">
                            Support regions
                        </span>

                        <span
                            class="control-value"
                            id="supportCount"
                        >
                            —
                        </span>

                    </div>

                    <div class="control">

                        <span class="control-name">
                            Watertight
                        </span>

                        <span
                            class="control-value"
                            id="watertight"
                        >
                            —
                        </span>

                    </div>

                </div>


                <!-- PROFILES -->

                <div class="card">

                    <div class="section-title">

                        <span>
                            OPTIMIZATION OPTIONS
                        </span>

                    </div>

                    <div id="profiles">

                        <div class="description">
                            Analyze the model to generate
                            optimization profiles.
                        </div>

                    </div>

                </div>


                <!-- CHANGES -->

                <div class="card">

                    <div class="section-title">

                        <span>
                            WHAT ECOSLICE WOULD CHANGE
                        </span>

                    </div>

                    <div id="changes">

                        <div class="description">
                            No recommendations yet.
                        </div>

                    </div>

                </div>


                <!-- LEGEND -->

                <div class="card">

                    <div class="section-title">

                        <span>
                            VISUALIZATION
                        </span>

                    </div>

                    <div class="legend">

                        <div class="legend-item">

                            <span
                                class="legend-dot"
                                style="background:#3dd9b5"
                            ></span>

                            Lower stress

                        </div>

                        <div class="legend-item">

                            <span
                                class="legend-dot"
                                style="background:#e8c95c"
                            ></span>

                            Medium

                        </div>

                        <div class="legend-item">

                            <span
                                class="legend-dot"
                                style="background:#ff756f"
                            ></span>

                            Higher stress

                        </div>

                    </div>

                </div>


            </section>

        </div>

    </main>

</div>


<script>

/* ==========================================================
   STATE
   ========================================================== */

let DATA = null;

let MODE = "solid";

let rotationX = -0.45;
let rotationY = 0.65;

let zoom = 1;

let dragging = false;

let lastMouseX = 0;
let lastMouseY = 0;


/* ==========================================================
   CANVAS
   ========================================================== */

const canvas =
    document.getElementById("canvas");

const ctx =
    canvas.getContext("2d");


function resizeCanvas() {

    const rect =
        canvas.getBoundingClientRect();

    canvas.width =
        Math.max(1, rect.width * devicePixelRatio);

    canvas.height =
        Math.max(1, rect.height * devicePixelRatio);

    ctx.setTransform(
        devicePixelRatio,
        0,
        0,
        devicePixelRatio,
        0,
        0
    );

    draw();

}


window.addEventListener(
    "resize",
    resizeCanvas
);


resizeCanvas();


/* ==========================================================
   MOUSE ROTATION
   ========================================================== */

canvas.addEventListener(
    "mousedown",
    function(event) {

        dragging = true;

        lastMouseX =
            event.clientX;

        lastMouseY =
            event.clientY;

    }
);


window.addEventListener(
    "mouseup",
    function() {

        dragging = false;

    }
);


window.addEventListener(
    "mousemove",
    function(event) {

        if (!dragging)
            return;

        const dx =
            event.clientX - lastMouseX;

        const dy =
            event.clientY - lastMouseY;

        rotationY += dx * 0.01;

        rotationX += dy * 0.01;

        lastMouseX =
            event.clientX;

        lastMouseY =
            event.clientY;

        draw();

    }
);


canvas.addEventListener(
    "wheel",
    function(event) {

        event.preventDefault();

        zoom *=
            event.deltaY > 0
                ? 0.9
                : 1.1;

        zoom =
            Math.max(
                0.4,
                Math.min(4, zoom)
            );

        draw();

    },
    { passive:false }
);


/* ==========================================================
   MODE
   ========================================================== */

function setMode(mode) {

    MODE = mode;

    document
        .querySelectorAll(".mode")
        .forEach(
            button =>
                button.classList.remove("active")
        );

    event.target.classList.add("active");

    draw();

}


/* ==========================================================
   ROTATION
   ========================================================== */

function rotatePoint(point) {

    let [x,y,z] = point;

    // X rotation

    let cosX =
        Math.cos(rotationX);

    let sinX =
        Math.sin(rotationX);

    let y1 =
        y * cosX - z * sinX;

    let z1 =
        y * sinX + z * cosX;

    y = y1;
    z = z1;

    // Y rotation

    let cosY =
        Math.cos(rotationY);

    let sinY =
        Math.sin(rotationY);

    let x1 =
        x * cosY + z * sinY;

    let z2 =
        -x * sinY + z * cosY;

    x = x1;
    z = z2;

    return [x,y,z];

}


/* ==========================================================
   DRAW MODEL
   ========================================================== */

function draw() {

    const rect =
        canvas.getBoundingClientRect();

    const width =
        rect.width;

    const height =
        rect.height;

    ctx.clearRect(
        0,
        0,
        width,
        height
    );

    if (!DATA ||
        !DATA.mesh ||
        !DATA.mesh.vertices.length) {

        drawEmptyState();

        return;
    }

    const vertices =
        DATA.mesh.vertices;

    const stresses =
        DATA.mesh.stress;

    let points =
        vertices.map(
            rotatePoint
        );

    let maxDimension = 1;

    points.forEach(
        p => {

            maxDimension =
                Math.max(
                    maxDimension,
                    Math.abs(p[0]),
                    Math.abs(p[1]),
                    Math.abs(p[2])
                );

        }
    );

    const scale =
        Math.min(width,height)
        / (maxDimension * 2.5)
        * zoom;

    function project(p) {

        return [
            width / 2 + p[0] * scale,
            height / 2 - p[1] * scale
        ];

    }


    // ------------------------------------------------------
    // Draw grid
    // ------------------------------------------------------

    ctx.save();

    ctx.strokeStyle =
        "rgba(61,217,181,.08)";

    ctx.lineWidth = 1;

    const gridSize = 50;

    for (
        let x = 0;
        x < width;
        x += gridSize
    ) {

        ctx.beginPath();

        ctx.moveTo(x,0);

        ctx.lineTo(x,height);

        ctx.stroke();

    }

    for (
        let y = 0;
        y < height;
        y += gridSize
    ) {

        ctx.beginPath();

        ctx.moveTo(0,y);

        ctx.lineTo(width,y);

        ctx.stroke();

    }

    ctx.restore();


    // ------------------------------------------------------
    // Draw triangles
    // ------------------------------------------------------

    for (
        let i = 0;
        i < vertices.length;
        i += 3
    ) {

        if (
            i + 2 >= vertices.length
        )
            break;

        const p1 =
            project(points[i]);

        const p2 =
            project(points[i + 1]);

        const p3 =
            project(points[i + 2]);


        let color =
            "rgba(55,116,121,.60)";


        if (MODE === "stress") {

            const stress =
                stresses[i] || 0;

            color =
                stressColor(
                    stress
                );

        }


        ctx.beginPath();

        ctx.moveTo(
            p1[0],
            p1[1]
        );

        ctx.lineTo(
            p2[0],
            p2[1]
        );

        ctx.lineTo(
            p3[0],
            p3[1]
        );

        ctx.closePath();

        ctx.fillStyle =
            color;

        ctx.fill();


        ctx.strokeStyle =
            "rgba(110,220,220,.08)";

        ctx.stroke();

    }


    // ------------------------------------------------------
    // SUPPORTS
    // ------------------------------------------------------

    if (
        MODE === "supports"
        &&
        DATA.supports
    ) {

        DATA.supports.forEach(
            support => {

                const top =
                    project(
                        rotatePoint(
                            support.top
                        )
                    );

                const bottom =
                    project(
                        rotatePoint(
                            support.bottom
                        )
                    );

                ctx.strokeStyle =
                    "#f4d34f";

                ctx.lineWidth = 3;

                ctx.beginPath();

                ctx.moveTo(
                    top[0],
                    top[1]
                );

                ctx.lineTo(
                    bottom[0],
                    bottom[1]
                );

                ctx.stroke();


                ctx.fillStyle =
                    "#f4d34f";

                ctx.beginPath();

                ctx.arc(
                    top[0],
                    top[1],
                    3,
                    0,
                    Math.PI * 2
                );

                ctx.fill();

            }
        );

    }

}


/* ==========================================================
   STRESS COLOR
   ========================================================== */

function stressColor(value) {

    value =
        Math.max(
            0,
            Math.min(
                1,
                value
            )
        );

    if (value < 0.5) {

        const t =
            value * 2;

        return `
            rgb(
                ${Math.round(61 + 180*t)},
                ${Math.round(217 - 80*t)},
                ${Math.round(181 - 110*t)}
            )
        `;

    }

    const t =
        (value - 0.5) * 2;

    return `
        rgb(
            ${Math.round(241)},
            ${Math.round(137 - 60*t)},
            ${Math.round(101 - 70*t)}
        )
    `;

}


/* ==========================================================
   EMPTY
   ========================================================== */

function drawEmptyState() {

    const rect =
        canvas.getBoundingClientRect();

    const width =
        rect.width;

    const height =
        rect.height;

    ctx.textAlign =
        "center";

    ctx.fillStyle =
        "#54706d";

    ctx.font =
        "14px sans-serif";

    ctx.fillText(
        "Load a model in OrcaSlicer",
        width / 2,
        height / 2
    );

}


/* ==========================================================
   UPDATE UI
   ========================================================== */

function updateUI(data) {

    DATA = data;

    const geometry =
        data.geometry;

    document.getElementById(
        "dimensions"
    ).textContent =
        geometry.dimensions_mm
            .map(
                x => x.toFixed(1)
            )
            .join(" × ")
        + " mm";


    document.getElementById(
        "volume"
    ).textContent =
        geometry.volume_mm3.toLocaleString()
        + " mm³";


    document.getElementById(
        "triangles"
    ).textContent =
        geometry.triangles.toLocaleString();


    document.getElementById(
        "supportRisk"
    ).textContent =
        geometry.support_risk
        + "%";


    document.getElementById(
        "modelName"
    ).textContent =
        data.objects?.[0]?.name
        || "Current OrcaSlicer Model";


    document.getElementById(
        "modelSub"
    ).textContent =
        "EcoSlice analysis complete";


    document.getElementById(
        "overhang"
    ).textContent =
        data.analysis.overhang_faces.toLocaleString()
        + " faces";


    document.getElementById(
        "stress"
    ).textContent =
        Math.round(
            data.analysis.stress_max * 100
        )
        + "% max";


    document.getElementById(
        "supportCount"
    ).textContent =
        data.analysis.support_points
        + " regions";


    document.getElementById(
        "watertight"
    ).textContent =
        geometry.manifold
            ? "YES"
            : "NO";


    renderProfiles(
        data.profiles
    );


    renderChanges(
        data.changes
    );


    draw();

}


/* ==========================================================
   PROFILES
   ========================================================== */

function renderProfiles(
    profiles
) {

    const container =
        document.getElementById(
            "profiles"
        );

    container.innerHTML = "";

    profiles.forEach(
        profile => {

            const recommended =
                profile.id === "balanced";

            const card =
                document.createElement(
                    "div"
                );

            card.className =
                "profile"
                + (
                    recommended
                        ? " recommended"
                        : ""
                );


            card.innerHTML = `

                <div class="profile-top">

                    <div class="profile-name">
                        ${profile.name}
                    </div>

                    <div class="profile-tag">
                        ${profile.tag}
                    </div>

                </div>

                <div class="profile-description">

                    ${
                        profile.id === "eco"
                        ? "Minimize material and print time."
                        : profile.id === "balanced"
                        ? "Balance strength, material, and time."
                        : "Prioritize structural robustness."
                    }

                </div>

                <div class="metrics">

                    <div class="metric">

                        <div class="metric-label">
                            MATERIAL
                        </div>

                        <div class="metric-value">
                            ${profile.material_g} g
                        </div>

                    </div>

                    <div class="metric">

                        <div class="metric-label">
                            TIME
                        </div>

                        <div class="metric-value">
                            ${profile.time_h} h
                        </div>

                    </div>

                    <div class="metric">

                        <div class="metric-label">
                            ENERGY
                        </div>

                        <div class="metric-value">
                            ${profile.energy_kwh} kWh
                        </div>

                    </div>

                    <div class="metric">

                        <div class="metric-label">
                            CO₂e
                        </div>

                        <div class="metric-value">
                            ${profile.co2_kg} kg
                        </div>

                    </div>

                    <div class="metric">

                        <div class="metric-label">
                            WALLS
                        </div>

                        <div class="metric-value">
                            ${profile.walls}
                        </div>

                    </div>

                    <div class="metric">

                        <div class="metric-label">
                            INFILL
                        </div>

                        <div class="metric-value">
                            ${profile.infill}%
                        </div>

                    </div>

                </div>

                <div class="metric" style="margin-top:7px">

                    <div class="metric-label">
                        STRENGTH CONFIDENCE
                    </div>

                    <div class="metric-value">
                        ${profile.confidence}%
                    </div>

                </div>

                <button
                    class="select-profile"
                    onclick="selectProfile('${profile.id}')"
                >
                    ${
                        recommended
                        ? "Recommended"
                        : "Select"
                    }
                </button>

            `;

            container.appendChild(
                card
            );

        }
    );

}


/* ==========================================================
   CHANGES
   ========================================================== */

function renderChanges(
    changes
) {

    const container =
        document.getElementById(
            "changes"
        );

    container.innerHTML = "";

    changes.forEach(
        change => {

            const row =
                document.createElement(
                    "div"
                );

            row.className =
                "change";

            row.innerHTML = `

                <span
                    class="change-dot ${change.severity}"
                ></span>

                <div>

                    <div class="change-title">
                        ${change.title}
                    </div>

                    <div class="change-body">
                        ${change.body}
                    </div>

                </div>

            `;

            container.appendChild(
                row
            );

        }
    );

}


/* ==========================================================
   ACTIONS
   ========================================================== */

function analyze() {

    const intent =
        document.getElementById(
            "intent"
        ).value;


    if (
        window.orca
        &&
        window.orca.postMessage
    ) {

        window.orca.postMessage({

            type: "analyze",

            intent: intent

        });

    }

}


function selectProfile(
    profileId
) {

    if (
        window.orca
        &&
        window.orca.postMessage
    ) {

        window.orca.postMessage({

            type: "select_profile",

            profile:
                profileId

        });

    }

}


/* ==========================================================
   ORCA MESSAGE BRIDGE
   ========================================================== */

if (
    window.orca
    &&
    window.orca.onMessage
) {

    window.orca.onMessage(
        function(data) {

            if (
                data.type === "analysis"
            ) {

                updateUI(
                    data.data
                );

            }

        }
    );

}

</script>

</body>
</html>
"""


# ============================================================
# ORCA PLUGIN
# ============================================================

class EcoSliceScript(
    orca.script.ScriptPluginCapabilityBase
):

    def __init__(self):

        self.window = None

        self.analyzer = EcoAnalyzer()

    def get_name(self):

        return "EcoSlice Optimizer"

    def execute(self):

        try:

            # Open the persistent interactive window.
            self.window = (
                orca.host.ui.create_window(
                    html=load_ecoslice_ui(),
                    title="EcoSlice — AI Manufacturing Copilot",
                    width=1380,
                    height=900,
                    on_message=self.on_message,
                    on_close=self.on_close
                )
            )

            # Immediately analyze the currently
            # loaded model.

            data = (
                self.analyzer
                .analyze_current_model()
            )

            self.window.post({
                "type": "analysis",
                "data": data
            })

            return orca.ExecutionResult.success(
                "EcoSlice optimizer opened."
            )

        except Exception as exc:

            traceback.print_exc()

            return orca.ExecutionResult.failure(
                orca.PluginResult.RecoverableError,
                str(exc)
            )

    def on_message(self, data):

        """
        Called by JavaScript.

        This is intentionally kept simple.
        """

        if not data:
            return

        message_type = data.get(
            "type"
        )

        if message_type == "analyze":

            try:

                result = (
                    self.analyzer
                    .analyze_current_model()
                )

                if self.window:

                    self.window.post({
                        "type": "analysis",
                        "data": result
                    })

            except Exception as exc:

                traceback.print_exc()

                if self.window:

                    self.window.post({
                        "type": "error",
                        "message": str(exc)
                    })

        elif message_type == "select_profile":

            profile = data.get(
                "profile"
            )

            print(
                "EcoSlice selected profile:",
                profile
            )

            # IMPORTANT:
            #
            # We do NOT modify OrcaSlicer here yet.
            #
            # The normal host API is read-only.
            #
            # This becomes the next slicing-pipeline stage.

    def on_close(self):

        self.window = None


# ============================================================
# PACKAGE REGISTRATION
# ============================================================

@orca.plugin
class EcoSlicePlugin(
    orca.base
):

    def register_capabilities(self):

        orca.register_capability(
            EcoSliceScript
        )