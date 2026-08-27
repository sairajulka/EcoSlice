import re


def parse_intent(prompt):
    prompt_lower = prompt.lower()

    result = {
        "priority": "balanced",
        "load_kg": None,
        "outdoor": False,
        "strength_required": False,
        "stiffness_required": False,
    }

    # Detect kilograms
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*kg",
        prompt_lower
    )

    if match:
        result["load_kg"] = float(match.group(1))

    # Environment
    if "outdoor" in prompt_lower:
        result["outdoor"] = True

    # Strength
    if any(
        word in prompt_lower
        for word in [
            "strength",
            "strong",
            "load",
            "heavy"
        ]
    ):
        result["strength_required"] = True

    # Stiffness
    if any(
        word in prompt_lower
        for word in [
            "stiff",
            "rigid",
            "flex"
        ]
    ):
        result["stiffness_required"] = True

    # Priority
    if any(
        word in prompt_lower
        for word in [
            "strength is more important",
            "maximum strength",
            "strongest"
        ]
    ):
        result["priority"] = "strength"

    elif any(
        word in prompt_lower
        for word in [
            "minimum material",
            "least material",
            "eco",
            "lightweight"
        ]
    ):
        result["priority"] = "eco"

    return result