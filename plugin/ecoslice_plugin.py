# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy"]
#
# [tool.orcaslicer.plugin]
# name = "EcoSlice"
# description = "AI-powered material, strength, and energy optimization for functional 3D printing."
# author = "Saira Julka"
# version = "0.2.0"
# ///

import math
import re
import numpy as np
import orca


# ============================================================
# ECO SLICE — ENGINEERING ANALYSIS
# ============================================================

def clamp(value, low, high):
    return max(low, min(high, value))


def analyze_mesh(mesh):
    """
    Extract geometry and calculate basic manufacturing risks.
    """

    vertices = np.asarray(mesh.vertices(), dtype=float)
    triangles = np.asarray(mesh.triangles(), dtype=np.int64)

    vertex_count = len(vertices)
    triangle_count = len(triangles)

    if triangle_count == 0:
        return {
            "vertices": vertex_count,
            "triangles": 0,
            "volume_mm3": 0,
            "dimensions_mm": (0, 0, 0),
            "manifold": False,
            "overhang": {},
        }

    # --------------------------------------------------------
    # Triangle vertices
    # --------------------------------------------------------

    p0 = vertices[triangles[:, 0]]
    p1 = vertices[triangles[:, 1]]
    p2 = vertices[triangles[:, 2]]

    # --------------------------------------------------------
    # Triangle normals
    # --------------------------------------------------------

    edges1 = p1 - p0
    edges2 = p2 - p0

    normals = np.cross(edges1, edges2)

    normal_lengths = np.linalg.norm(normals, axis=1)

    valid = normal_lengths > 1e-12

    normals[valid] /= normal_lengths[valid, None]

    # --------------------------------------------------------
    # Triangle areas
    # --------------------------------------------------------

    areas = 0.5 * normal_lengths

    total_surface_area = float(np.sum(areas))

    # --------------------------------------------------------
    # Overhang calculation
    #
    # Z is assumed to be the build direction.
    #
    # A downward-facing face has a negative Z normal.
    # --------------------------------------------------------

    z_normals = normals[:, 2]

    downward = z_normals < 0

    downward_area = float(np.sum(areas[downward]))

    # 45 degree overhang threshold
    threshold = math.cos(math.radians(45))

    critical = downward & (z_normals < -threshold)

    critical_area = float(np.sum(areas[critical]))

    # More permissive 60 degree region
    severe = downward & (z_normals < -math.cos(math.radians(60)))

    severe_area = float(np.sum(areas[severe]))

    overhang_ratio = (
        critical_area / total_surface_area
        if total_surface_area > 0
        else 0
    )

    # --------------------------------------------------------
    # Bounding box
    # --------------------------------------------------------

    mins = np.min(vertices, axis=0)
    maxs = np.max(vertices, axis=0)

    dimensions = maxs - mins

    # --------------------------------------------------------
    # Thin-feature heuristic
    #
    # This is NOT structural FEA.
    # It is a geometry warning.
    # --------------------------------------------------------

    smallest_dimension = float(np.min(dimensions))

    thin_feature_warning = smallest_dimension < 1.2

    # --------------------------------------------------------
    # Risk score
    # --------------------------------------------------------

    support_risk = clamp(
        overhang_ratio * 100 * 1.8
        + (severe_area / total_surface_area * 100 * 1.2
           if total_surface_area > 0 else 0),
        0,
        100
    )

    if support_risk < 20:
        risk_label = "LOW"
    elif support_risk < 50:
        risk_label = "MEDIUM"
    elif support_risk < 75:
        risk_label = "HIGH"
    else:
        risk_label = "VERY HIGH"

    return {
        "vertices": vertex_count,
        "triangles": triangle_count,
        "volume_mm3": float(mesh.volume()),
        "dimensions_mm": tuple(float(x) for x in dimensions),
        "manifold": bool(mesh.is_manifold()),
        "surface_area_mm2": total_surface_area,
        "downward_area_mm2": downward_area,
        "critical_overhang_area_mm2": critical_area,
        "severe_overhang_area_mm2": severe_area,
        "overhang_ratio": overhang_ratio,
        "support_risk": support_risk,
        "risk_label": risk_label,
        "thin_feature_warning": thin_feature_warning,
    }


# ============================================================
# USER INTENT PARSER
# ============================================================

def parse_intent(text):
    """
    Convert a natural-language description into engineering
    requirements.

    This is deliberately rule-based for the first MVP.
    Later this function can call a real LLM.
    """

    text_lower = text.lower()

    result = {
        "description": text,
        "priority": "balanced",
        "load_kg": None,
        "outdoor": False,
        "strength_priority": False,
        "appearance_priority": False,
        "vibration": False,
        "cantilever": False,
    }

    # --------------------------------------------------------
    # Priority
    # --------------------------------------------------------

    if (
        "strength matters more" in text_lower
        or "strength" in text_lower
        or "strong" in text_lower
        or "durability" in text_lower
    ):
        result["priority"] = "strength"
        result["strength_priority"] = True

    if (
        "appearance matters more" in text_lower
        or "appearance" in text_lower
        or "looks" in text_lower
    ):
        result["priority"] = "appearance"
        result["appearance_priority"] = True

    # --------------------------------------------------------
    # Environment
    # --------------------------------------------------------

    if (
        "outdoor" in text_lower
        or "outside" in text_lower
        or "weather" in text_lower
    ):
        result["outdoor"] = True

    # --------------------------------------------------------
    # Mechanical loading
    # --------------------------------------------------------

    if "vibration" in text_lower:
        result["vibration"] = True

    if (
        "cantilever" in text_lower
        or "cantilevered" in text_lower
    ):
        result["cantilever"] = True

    # --------------------------------------------------------
    # Load
    # --------------------------------------------------------

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(kg|kilogram|kilograms)",
        text_lower
    )

    if match:
        result["load_kg"] = float(match.group(1))

    return result


# ============================================================
# STRENGTH HEURISTIC
# ============================================================

def estimate_strength_confidence(
    geometry,
    intent,
    infill_percent,
    wall_count
):
    """
    This is NOT FEA.

    It is an MVP confidence heuristic that gives us a useful
    product demo while we build the real physics layer.
    """

    score = 50.0

    # More walls generally improve robustness.
    score += min(wall_count * 5, 20)

    # More infill generally improves bulk strength.
    score += min(infill_percent * 0.35, 20)

    # Thin geometry reduces confidence.
    if geometry["thin_feature_warning"]:
        score -= 15

    # Large support/overhang problems reduce confidence.
    score -= geometry["support_risk"] * 0.15

    # Strength-priority jobs should select more conservative
    # configurations.
    if intent["strength_priority"]:
        score += 8

    return clamp(score, 0, 99)


# ============================================================
# PRINT ESTIMATION
# ============================================================

def estimate_print(
    volume_mm3,
    infill_percent,
    wall_count,
    support_risk,
    printer_speed_factor=1.0
):
    """
    Rough planning estimate.

    This is NOT a replacement for OrcaSlicer's actual slicer
    time estimate.
    """

    # Convert mm³ to cm³.
    solid_volume_cm3 = volume_mm3 / 1000.0

    # Crude material utilization estimate.
    utilization = (
        0.18
        + infill_percent / 100.0 * 0.55
        + wall_count * 0.035
    )

    utilization = clamp(utilization, 0.18, 0.95)

    printed_volume = solid_volume_cm3 * utilization

    # Very rough print throughput assumption.
    cm3_per_hour = 7.0 * printer_speed_factor

    hours = printed_volume / cm3_per_hour

    # Support penalty.
    hours *= 1 + support_risk / 250

    grams = printed_volume * 1.24

    return {
        "material_g": grams,
        "time_hours": hours,
    }


# ============================================================
# OPTIMIZATION OPTIONS
# ============================================================

def generate_options(geometry, intent):
    """
    Generate Eco / Balanced / Strength candidates.
    """

    # ----------------------------------------
    # ECO
    # ----------------------------------------

    eco_walls = 2
    eco_infill = 12

    # ----------------------------------------
    # BALANCED
    # ----------------------------------------

    balanced_walls = 3
    balanced_infill = 25

    # ----------------------------------------
    # STRENGTH
    # ----------------------------------------

    strength_walls = 5
    strength_infill = 45

    if intent["strength_priority"]:

        strength_walls = 6
        strength_infill = 55

        balanced_walls = 4
        balanced_infill = 30

    options = []

    configs = [
        (
            "Eco",
            eco_walls,
            eco_infill,
            "Minimize material and print time"
        ),
        (
            "Balanced",
            balanced_walls,
            balanced_infill,
            "Balance strength, material, and time"
        ),
        (
            "Maximum Strength",
            strength_walls,
            strength_infill,
            "Prioritize structural robustness"
        ),
    ]

    for name, walls, infill, description in configs:

        estimate = estimate_print(
            geometry["volume_mm3"],
            infill,
            walls,
            geometry["support_risk"]
        )

        confidence = estimate_strength_confidence(
            geometry,
            intent,
            infill,
            walls
        )

        # Energy proxy:
        #
        # This is an estimate, not a measurement.
        # Later we'll replace this with real power data.
        energy_kwh = (
            estimate["time_hours"] * 0.12
        )

        co2e = energy_kwh * 0.35

        options.append({
            "name": name,
            "walls": walls,
            "infill": infill,
            "description": description,
            "material_g": estimate["material_g"],
            "time_hours": estimate["time_hours"],
            "energy_kwh": energy_kwh,
            "co2e_kg": co2e,
            "strength_confidence": confidence,
        })

    return options


# ============================================================
# FULL MODEL ANALYSIS
# ============================================================

def analyze_model(model, intent_text):
    intent = parse_intent(intent_text)

    objects = model.objects()

    all_geometry = []

    for obj in objects:

        for volume in obj.volumes():

            mesh = volume.mesh()

            if mesh.is_empty():
                continue

            analysis = analyze_mesh(mesh)

            analysis["object_name"] = obj.name

            all_geometry.append(analysis)

    if not all_geometry:
        raise RuntimeError(
            "No printable mesh was found in the current model."
        )

    total_volume = sum(
        item["volume_mm3"]
        for item in all_geometry
    )

    total_triangles = sum(
        item["triangles"]
        for item in all_geometry
    )

    total_surface = sum(
        item["surface_area_mm2"]
        for item in all_geometry
    )

    total_overhang = sum(
        item["critical_overhang_area_mm2"]
        for item in all_geometry
    )

    overall_geometry = {
        "volume_mm3": total_volume,
        "triangles": total_triangles,
        "surface_area_mm2": total_surface,
        "critical_overhang_area_mm2": total_overhang,
        "support_risk": (
            total_overhang / total_surface * 100
            if total_surface > 0
            else 0
        ),
        "thin_feature_warning": any(
            item["thin_feature_warning"]
            for item in all_geometry
        ),
    }

    options = generate_options(
        overall_geometry,
        intent
    )

    return {
        "objects": all_geometry,
        "geometry": overall_geometry,
        "intent": intent,
        "options": options,
    }


# ============================================================
# HTML DASHBOARD
# ============================================================

HTML = r"""
<!DOCTYPE html>

<html>

<head>

<meta charset="UTF-8">

<style>

body {
    font-family: var(--orca-font);
    margin: 0;
    padding: 20px;
    color: var(--orca-fg);
    background: var(--orca-bg);
}

h1 {
    margin-top: 0;
}

.subtitle {
    color: var(--orca-muted);
    margin-bottom: 20px;
}

textarea {
    width: 100%;
    height: 90px;
    box-sizing: border-box;
    resize: vertical;
}

button {
    padding: 10px 16px;
    margin-top: 10px;
    cursor: pointer;
}

.grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
    margin-top: 20px;
}

.card {
    border: 1px solid var(--orca-border);
    border-radius: 10px;
    padding: 15px;
}

.card h3 {
    margin-top: 0;
}

.metric {
    margin: 8px 0;
}

.big {
    font-size: 26px;
    font-weight: bold;
}

.warning {
    padding: 12px;
    border: 1px solid var(--orca-border);
    border-radius: 8px;
    margin-top: 15px;
}

.option {
    border: 1px solid var(--orca-border);
    border-radius: 10px;
    padding: 16px;
}

.selected {
    border: 2px solid var(--orca-accent);
}

.small {
    color: var(--orca-muted);
    font-size: 13px;
}

.hidden {
    display: none;
}

</style>

</head>

<body>

<h1>EcoSlice</h1>

<div class="subtitle">
AI-assisted material, energy, and strength optimization
for functional 3D printing.
</div>

<h2>1. Describe the part</h2>

<textarea id="intent"
placeholder="Example: A garden hose holder. It supports 1 kg outdoors. Strength matters more than appearance."></textarea>

<br>

<button onclick="analyze()">
Analyze current OrcaSlicer model
</button>

<div id="status"></div>

<div id="results" class="hidden">

<h2>2. Geometry</h2>

<div class="grid">

<div class="card">
<div class="small">Volume</div>
<div class="big" id="volume"></div>
</div>

<div class="card">
<div class="small">Triangles</div>
<div class="big" id="triangles"></div>
</div>

<div class="card">
<div class="small">Support Risk</div>
<div class="big" id="risk"></div>
</div>

</div>

<div id="warnings"></div>

<h2>3. Engineering Intent</h2>

<div class="card">

<div>
Priority:
<strong id="priority"></strong>
</div>

<div>
Load:
<strong id="load"></strong>
</div>

<div>
Outdoor:
<strong id="outdoor"></strong>
</div>

<div>
Vibration:
<strong id="vibration"></strong>
</div>

</div>

<h2>4. Optimization Options</h2>

<div class="grid" id="options"></div>

<h2>5. What EcoSlice would change</h2>

<div class="card" id="explanation"></div>

</div>

<script>

function post(type, payload = {}) {

    window.orca.postMessage({
        type: type,
        ...payload
    });

}

function analyze() {

    const intent =
        document.getElementById("intent").value;

    document.getElementById("status").innerText =
        "Analyzing model...";

    post("analyze", {
        intent: intent
    });

}

function receive(data) {

    if (data.type === "result") {

        render(data.result);

    }

    if (data.type === "error") {

        document.getElementById("status").innerText =
            "Error: " + data.message;

    }

}

function render(result) {

    document
        .getElementById("results")
        .classList
        .remove("hidden");

    document.getElementById("status").innerText =
        "Analysis complete.";

    document.getElementById("volume").innerText =
        Math.round(
            result.geometry.volume_mm3
        ).toLocaleString() + " mm³";

    document.getElementById("triangles").innerText =
        result.geometry.triangles.toLocaleString();

    document.getElementById("risk").innerText =
        result.geometry.support_risk.toFixed(1) + "%";

    document.getElementById("priority").innerText =
        result.intent.priority;

    document.getElementById("load").innerText =
        result.intent.load_kg === null
            ? "Not specified"
            : result.intent.load_kg + " kg";

    document.getElementById("outdoor").innerText =
        result.intent.outdoor ? "Yes" : "No";

    document.getElementById("vibration").innerText =
        result.intent.vibration ? "Yes" : "No";

    let warning = "";

    if (result.geometry.support_risk > 50) {

        warning += `
        <div class="warning">
        ⚠️ High support risk detected.
        EcoSlice recommends evaluating orientation
        before generating supports.
        </div>
        `;

    }

    if (result.geometry.thin_feature_warning) {

        warning += `
        <div class="warning">
        ⚠️ Thin geometry detected.
        Consider additional walls or a stronger
        orientation.
        </div>
        `;

    }

    document.getElementById("warnings").innerHTML =
        warning;

    const container =
        document.getElementById("options");

    container.innerHTML = "";

    result.options.forEach((option, index) => {

        const card =
            document.createElement("div");

        card.className = "option";

        card.innerHTML = `

        <h3>${option.name}</h3>

        <div class="small">
        ${option.description}
        </div>

        <div class="metric">
        Walls:
        <strong>${option.walls}</strong>
        </div>

        <div class="metric">
        Infill:
        <strong>${option.infill}%</strong>
        </div>

        <div class="metric">
        Material:
        <strong>
        ${option.material_g.toFixed(1)} g
        </strong>
        </div>

        <div class="metric">
        Time:
        <strong>
        ${option.time_hours.toFixed(2)} h
        </strong>
        </div>

        <div class="metric">
        Energy:
        <strong>
        ${option.energy_kwh.toFixed(2)} kWh
        </strong>
        </div>

        <div class="metric">
        CO₂e proxy:
        <strong>
        ${option.co2e_kg.toFixed(2)} kg
        </strong>
        </div>

        <div class="metric">
        Strength confidence:
        <strong>
        ${option.strength_confidence.toFixed(0)}%
        </strong>
        </div>

        <button onclick="selectOption(${index})">
        Select
        </button>

        `;

        container.appendChild(card);

    });

}

function selectOption(index) {

    post("select_option", {
        index: index
    });

}

window.orca.onMessage(receive);

</script>

</body>

</html>
"""


# ============================================================
# PLUGIN CAPABILITY
# ============================================================

class EcoSliceAnalysis(
    orca.script.ScriptPluginCapabilityBase
):

    def get_name(self):

        return "EcoSlice AI Optimizer"

    def execute(self):

        try:

            model = orca.host.model()

            result = analyze_model(
                model,
                "functional part"
            )

            message = (
                "EcoSlice analysis complete.\n\n"
                f"Volume: "
                f"{result['geometry']['volume_mm3']:.2f} mm³\n"
                f"Triangles: "
                f"{result['geometry']['triangles']}\n"
                f"Support risk: "
                f"{result['geometry']['support_risk']:.1f}%"
            )

            return orca.ExecutionResult.success(
                message
            )

        except Exception as exc:

            return orca.ExecutionResult.failure(
                orca.PluginResult.RecoverableError,
                f"EcoSlice analysis failed: {exc}"
            )

    def has_config_ui(self):

        return False


class EcoSliceDashboard(
    orca.script.ScriptPluginCapabilityBase
):

    def get_name(self):

        return "EcoSlice Dashboard"

    def execute(self):

        try:

            model = orca.host.model()

            result = analyze_model(
                model,
                "functional part"
            )

            html = HTML

            dialog_result = orca.host.ui.show_dialog(
                html=html,
                title="EcoSlice",
                width=1000,
                height=800
            )

            return orca.ExecutionResult.success(
                "EcoSlice dashboard opened."
            )

        except Exception as exc:

            return orca.ExecutionResult.failure(
                orca.PluginResult.RecoverableError,
                f"Could not open EcoSlice dashboard: {exc}"
            )


# ============================================================
# INTERACTIVE DASHBOARD
# ============================================================

class EcoSliceInteractive(
    orca.script.ScriptPluginCapabilityBase
):

    def get_name(self):

        return "EcoSlice Interactive Optimizer"

    def execute(self):

        try:

            self.window = orca.host.ui.create_window(
                html=HTML,
                title="EcoSlice AI Optimizer",
                on_message=self.on_message,
                on_close=self.on_close
            )

            return orca.ExecutionResult.success(
                "EcoSlice optimizer opened."
            )

        except Exception as exc:

            return orca.ExecutionResult.failure(
                orca.PluginResult.RecoverableError,
                f"Could not open EcoSlice: {exc}"
            )

    def on_message(self, data):

        try:

            message_type = data.get("type")

            if message_type == "analyze":

                model = orca.host.model()

                intent = data.get(
                    "intent",
                    "functional part"
                )

                result = analyze_model(
                    model,
                    intent
                )

                self.window.post({
                    "type": "result",
                    "result": result
                })

            elif message_type == "select_option":

                index = int(
                    data.get("index", 0)
                )

                print(
                    f"EcoSlice selected option {index}"
                )

                self.window.post({
                    "type": "status",
                    "message":
                        "Optimization selected. "
                        "Actual slicer-setting modification "
                        "will be added in the slicing-pipeline layer."
                })

        except Exception as exc:

            self.window.post({
                "type": "error",
                "message": str(exc)
            })

    def on_close(self):

        self.window = None


# ============================================================
# PLUGIN REGISTRATION
# ============================================================

@orca.plugin
class EcoSlicePlugin(orca.base):

    def register_capabilities(self):

        orca.register_capability(
            EcoSliceAnalysis
        )

        orca.register_capability(
            EcoSliceDashboard
        )

        orca.register_capability(
            EcoSliceInteractive
        )