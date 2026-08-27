from fastapi import FastAPI

app = FastAPI(
    title="EcoSlice API",
    version="0.1.0"
)


@app.get("/")
def root():
    return {
        "name": "EcoSlice",
        "version": "0.1.0",
        "status": "running"
    }
import os
import uuid

from fastapi import (
    FastAPI,
    UploadFile,
    File,
    Form,
    HTTPException
)

from analysis.mesh_analyzer import (
    load_mesh,
    analyze_mesh
)

from analysis.overhang import (
    calculate_overhangs
)

from analysis.orientation import (
    find_best_orientations
)

from analysis.stress import (
    estimate_stress_regions
)

from ai.intent_parser import (
    parse_intent
)

from optimization.optimizer import (
    generate_options
)


app = FastAPI(
    title="EcoSlice API",
    version="0.1.0"
)


UPLOAD_DIR = "../uploads"

os.makedirs(
    UPLOAD_DIR,
    exist_ok=True
)


@app.get("/")
def root():

    return {
        "name": "EcoSlice",
        "version": "0.1.0",
        "status": "running"
    }


@app.post("/analyze")
async def analyze(
    file: UploadFile = File(...),
    prompt: str = Form(...)
):

    if not file.filename.lower().endswith(
        (".stl", ".obj", ".ply")
    ):
        raise HTTPException(
            status_code=400,
            detail="Please upload an STL, OBJ, or PLY file."
        )

    file_id = str(uuid.uuid4())

    filename = (
        f"{file_id}_{file.filename}"
    )

    file_path = os.path.join(
        UPLOAD_DIR,
        filename
    )

    with open(
        file_path,
        "wb"
    ) as output:

        output.write(
            await file.read()
        )

    try:

        mesh = load_mesh(
            file_path
        )

        geometry = analyze_mesh(
            file_path
        )

        overhang = calculate_overhangs(
            mesh
        )

        orientations = find_best_orientations(
            mesh
        )

        stress = estimate_stress_regions(
            mesh
        )

        intent = parse_intent(
            prompt
        )

        options = generate_options(
            geometry["volume_mm3"],
            overhang["overhang_percentage"],
            stress,
            intent
        )

        return {
            "success": True,
            "file": filename,
            "geometry": geometry,
            "overhang": overhang,
            "stress": stress,
            "intent": intent,
            "orientations": orientations,
            "options": options
        }

    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )