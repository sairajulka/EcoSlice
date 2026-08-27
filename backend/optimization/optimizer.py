BASE_SETTINGS = {
    "eco": {
        "walls": 2,
        "infill": 10,
        "support": "minimal"
    },

    "balanced": {
        "walls": 3,
        "infill": 25,
        "support": "normal"
    },

    "strength": {
        "walls": 4,
        "infill": 50,
        "support": "maximum"
    }
}


def estimate_print(
    volume_mm3,
    walls,
    infill,
    support_factor
):
    """
    Very rough first-pass estimates.

    These are NOT slicer-accurate.
    """

    # Approximate PLA/PETG-like density.
    density_g_cm3 = 1.24

    volume_cm3 = volume_mm3 / 1000

    base_mass = (
        volume_cm3
        * density_g_cm3
    )

    material_factor = (
        0.25
        + (walls * 0.12)
        + (infill / 100) * 0.55
        + support_factor
    )

    material_g = (
        base_mass
        * material_factor
    )

    # Very rough estimate
    print_minutes = (
        material_g * 2.2
        + 15
    )

    energy_kwh = (
        print_minutes / 60
    ) * 0.12

    return {
        "material_g": round(material_g, 2),
        "print_time_min": round(print_minutes, 1),
        "energy_kwh": round(energy_kwh, 3)
    }


def generate_options(
    volume_mm3,
    overhang_percentage,
    stress_data,
    intent
):

    results = {}

    for name, settings in BASE_SETTINGS.items():

        if settings["support"] == "minimal":
            support_factor = (
                overhang_percentage / 100
            ) * 0.03

        elif settings["support"] == "normal":
            support_factor = (
                overhang_percentage / 100
            ) * 0.06

        else:
            support_factor = (
                overhang_percentage / 100
            ) * 0.10

        estimate = estimate_print(
            volume_mm3,
            settings["walls"],
            settings["infill"],
            support_factor
        )

        # Simplified confidence model
        confidence = 50

        confidence += (
            settings["walls"] * 5
        )

        confidence += (
            settings["infill"] * 0.4
        )

        if intent["strength_required"]:
            confidence += 10

        confidence = min(
            round(confidence),
            99
        )

        results[name] = {
            **settings,
            **estimate,
            "strength_confidence": confidence
        }

    return results