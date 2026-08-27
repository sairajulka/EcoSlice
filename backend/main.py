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