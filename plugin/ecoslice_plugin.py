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

import json
import math
import os
import traceback

import numpy as np
import orca


PLUGIN_VERSION = "0.2.1"


# ============================================================
# HELPERS
# ============================================================

def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def format_number(value, decimals=0):
    if decimals == 0:
        return f"{int(round(value)):,}"
    return f"{value:,.{decimals}f}"


def calculate_support_risk(vertices, triangles):
    """
    Lightweight geometry heuristic.

    This is NOT a physics simulation. It estimates how much geometry
    may require support based on downward-facing triangles.
    """

    if len(vertices) == 0 or len(triangles) == 0:
        return 0.0

    try:
        v = np.asarray(vertices, dtype=np.float64)
        t = np.asarray(triangles, dtype=np.int64)

        if len(t) > 100000:
            # Keep the UI responsive on high-poly meshes.
            step = max(1, len(t) // 100000)
            t = t[::step]

        p1 = v[t[:, 0]]
        p2 = v[t[:, 1]]
        p3 = v[t[:, 2]]

        a = p2 - p1
        b = p3 - p1

        normals = np.cross(a, b)

        lengths = np.linalg.norm(normals, axis=1)
        valid = lengths > 1e-12

        normals = normals[valid]
        lengths = lengths[valid]

        if len(normals) == 0:
            return 0.0

        normals = normals / lengths[:, None]

        # Z component tells us how downward-facing the surface is.
        downward = np.clip(-normals[:, 2], 0.0, 1.0)

        risk = float(np.mean(downward) * 100.0)

        return min(100.0, max(0.0, risk))

    except Exception:
        return 0.0


def parse_intent(text):
    """
    Simple local intent parser.

    Examples:
        "strength"
        "supports 1 kg"
        "outdoors"
        "vibration"
    """

    text = (text or "").lower()

    priority = "balanced"

    if any(word in text for word in [
        "strength",
        "strong",
        "load",
        "structural",
        "durable",
    ]):
        priority = "strength"

    elif any(word in text for word in [
        "lightweight",
        "light",
        "material",
        "eco",
        "sustainable",
        "cheap",
    ]):
        priority = "eco"

    load = "Not specified"

    import re

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(kg|kilogram|kilograms|g|gram|grams)",
        text,
    )

    if match:
        amount = match.group(1)
        unit = match.group(2)

        if unit.startswith("kg") or unit.startswith("kilogram"):
            load = f"{amount} kg"
        else:
            load = f"{amount} g"

    outdoor = any(word in text for word in [
        "outdoor",
        "outside",
        "weather",
        "rain",
        "sun",
    ])

    vibration = any(word in text for word in [
        "vibration",
        "vibrating",
        "shock",
        "impact",
    ])

    return {
        "priority": priority,
        "load": load,
        "outdoor": outdoor,
        "vibration": vibration,
    }


def make_optimization_options(volume_mm3, intent, support_risk):
    """
    Generate the three optimization recommendations.

    These are engineering heuristics for the prototype, not certified
    structural calculations.
    """

    priority = intent.get("priority", "balanced")

    # Approximate PLA density in g/mm³.
    density = 0.00124

    # Approximate printed material volume fractions.
    profiles = {
        "eco": {
            "walls": 2,
            "infill": 12,
            "factor": 0.30,
            "time_factor": 0.70,
            "strength": 71,
        },
        "balanced": {
            "walls": 4,
            "infill": 30,
            "factor": 0.46,
            "time_factor": 1.00,
            "strength": 87,
        },
        "maximum": {
            "walls": 6,
            "infill": 55,
            "factor": 0.66,
            "time_factor": 1.42,
            "strength": 96,
        },
    }

    # Increase support/material estimates for geometry with greater
    # support risk.
    support_multiplier = 1.0 + (support_risk / 100.0) * 0.15

    result = []

    for key, profile in profiles.items():

        material_volume = (
            volume_mm3
            * profile["factor"]
            * support_multiplier
        )

        material_g = material_volume * density

        # Prototype print-time model.
        time_hours = (
            max(0.15, material_g / 8.0)
            * profile["time_factor"]
        )

        energy_kwh = time_hours * 0.115

        co2_kg = energy_kwh * 0.38

        strength = profile["strength"]

        if priority == "strength":
            if key == "eco":
                strength -= 4
            elif key == "maximum":
                strength += 1

        result.append({
            "id": key,
            "name": {
                "eco": "Eco",
                "balanced": "Balanced",
                "maximum": "Maximum Strength",
            }[key],

            "description": {
                "eco": "Minimize material and print time",
                "balanced": "Balance strength, material, and time",
                "maximum": "Prioritize structural robustness",
            }[key],

            "walls": profile["walls"],
            "infill": profile["infill"],

            "material_g": round(material_g, 1),
            "time_h": round(time_hours, 2),
            "energy_kwh": round(energy_kwh, 2),
            "co2_kg": round(co2_kg, 2),
            "strength_confidence": min(99, max(1, strength)),
        })

    return result


# ============================================================
# MAIN ECOSLICE CAPABILITY
# ============================================================

class EcoSliceOptimizer(
    orca.script.ScriptPluginCapabilityBase
):

    def __init__(self):
        # IMPORTANT:
        # OrcaSlicer requires the typed base class initializer
        # to be called when overriding __init__.
        super().__init__()

        self.last_analysis = None

    def get_name(self):
        return "EcoSlice AI Optimizer"

    def on_load(self):
        """
        Called when the capability is loaded.
        """

        self.last_analysis = None

    def on_unload(self):
        """
        Called when the capability is unloaded.
        """

        self.last_analysis = None

    def execute(self):
        """
        Main entry point when the user clicks Run in the
        OrcaSlicer Plugins window.
        """

        try:
            model = orca.host.model()

            if model is None:
                return orca.ExecutionResult.failure(
                    orca.PluginResult.RecoverableError,
                    "EcoSlice could not access the current OrcaSlicer model."
                )

            objects = model.objects()

            if not objects:
                return orca.ExecutionResult.failure(
                    orca.PluginResult.RecoverableError,
                    "No model is currently loaded in OrcaSlicer."
                )

            total_volume = 0.0
            total_triangles = 0
            support_risks = []

            object_results = []

            for obj_index, obj in enumerate(objects):

                object_volume = 0.0
                object_triangles = 0

                for volume_index, volume in enumerate(obj.volumes()):

                    mesh = volume.mesh()

                    if mesh is None:
                        continue

                    vertices = np.asarray(
                        mesh.vertices(),
                        dtype=np.float64,
                    )

                    triangles = np.asarray(
                        mesh.triangles(),
                        dtype=np.int64,
                    )

                    triangle_count = len(triangles)

                    object_triangles += triangle_count

                    # Calculate volume using signed tetrahedra.
                    try:
                        if triangle_count > 150000:
                            step = max(
                                1,
                                triangle_count // 150000
                            )
                            calc_triangles = triangles[::step]
                        else:
                            calc_triangles = triangles

                        p1 = vertices[calc_triangles[:, 0]]
                        p2 = vertices[calc_triangles[:, 1]]
                        p3 = vertices[calc_triangles[:, 2]]

                        volume_value = np.sum(
                            np.einsum(
                                "ij,ij->i",
                                p1,
                                np.cross(p2, p3),
                            )
                        ) / 6.0

                        volume_value = abs(float(volume_value))

                    except Exception:
                        volume_value = 0.0

                    object_volume += volume_value

                    risk = calculate_support_risk(
                        vertices,
                        triangles,
                    )

                    support_risks.append(risk)

                total_volume += object_volume
                total_triangles += object_triangles

                object_results.append({
                    "index": obj_index + 1,
                    "volume_mm3": object_volume,
                    "triangles": object_triangles,
                })

            if not object_results:
                return orca.ExecutionResult.failure(
                    orca.PluginResult.RecoverableError,
                    "EcoSlice found no usable mesh geometry."
                )

            support_risk = (
                sum(support_risks) / len(support_risks)
                if support_risks
                else 0.0
            )

            analysis = {
                "plugin_version": PLUGIN_VERSION,

                "geometry": {
                    "volume_mm3": round(total_volume, 2),
                    "triangles": total_triangles,
                    "support_risk": round(
                        support_risk,
                        1,
                    ),
                },

                "objects": object_results,
            }

            self.last_analysis = analysis

            # ----------------------------------------------------
            # Create the user-facing result.
            # ----------------------------------------------------

            message = (
                "EcoSlice analysis complete.\n\n"
                f"Volume: {format_number(total_volume, 2)} mm³\n"
                f"Triangles: {format_number(total_triangles)}\n"
                f"Estimated support risk: {support_risk:.1f}%"
            )

            return orca.ExecutionResult.success(
                message,
                json.dumps(analysis),
            )

        except Exception as exc:

            traceback.print_exc()

            return orca.ExecutionResult.failure(
                orca.PluginResult.RecoverableError,
                f"EcoSlice analysis failed: {exc}",
            )


# ============================================================
# PLUGIN PACKAGE
# ============================================================

@orca.plugin
class EcoSlicePlugin(orca.base):

    def register_capabilities(self):

        orca.register_capability(
            EcoSliceOptimizer
        )