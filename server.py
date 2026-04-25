from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.geocoder import geocode_city
from src.pipeline import GenerationResult, generate_model

app = FastAPI(title="city3dmodels local server")
app.mount("/web", StaticFiles(directory="web"), name="web")

executor = ThreadPoolExecutor(max_workers=1)
job_lock = Lock()
jobs: dict[str, dict] = {}


class GenerateRequest(BaseModel):
    city: str | None = None
    bbox: tuple[float, float, float, float] = Field(..., description="south,west,north,east")
    scale: int = 50000
    mode: str = "clip"
    crop_cm: tuple[float, float] | None = None
    tile_cm: tuple[float, float] | None = None
    base_mm: float = 1.0
    output_name: str | None = None
    min_buildings: int = 5
    verbose: bool = False


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s or "city"


def _job_output_dir(city: str | None, output_name: str | None) -> Path:
    name = output_name or city or "city"
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return Path("output") / "jobs" / f"{stamp}_{_slug(name)}"


@app.get("/")
def index():
    return FileResponse("web/index.html")


@app.get("/api/geocode")
def api_geocode(city: str):
    lat, lon = geocode_city(city)
    return {"city": city, "lat": lat, "lon": lon}


@app.post("/api/generate")
def api_generate(req: GenerateRequest):
    job_id = uuid4().hex[:12]
    output_dir = _job_output_dir(req.city, req.output_name)

    with job_lock:
        jobs[job_id] = {
            "status": "queued",
            "logs": [],
            "output_dir": str(output_dir),
            "result": None,
            "error": None,
        }

    def _logger(message: str) -> None:
        with job_lock:
            jobs[job_id]["logs"].append(message)

    def _run() -> None:
        with job_lock:
            jobs[job_id]["status"] = "running"
        try:
            south, west, north, east = req.bbox
            center_lat = (south + north) / 2.0
            center_lon = (west + east) / 2.0
            result = generate_model(
                city=req.city,
                center_lat=center_lat,
                center_lon=center_lon,
                bbox=req.bbox,
                scale=req.scale,
                output=str(output_dir),
                mode=req.mode,
                crop_cm=req.crop_cm,
                tile_cm=req.tile_cm,
                base_mm=req.base_mm,
                min_buildings=req.min_buildings,
                verbose=req.verbose,
                logger=_logger,
            )
            with job_lock:
                jobs[job_id]["status"] = "done"
                jobs[job_id]["result"] = result
        except Exception as exc:  # noqa: BLE001
            with job_lock:
                jobs[job_id]["status"] = "error"
                jobs[job_id]["error"] = str(exc)

    executor.submit(_run)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str):
    with job_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, detail="job not found")

        payload = {
            "job_id": job_id,
            "status": job["status"],
            "logs": job["logs"],
            "output_dir": job["output_dir"],
            "error": job["error"],
            "files": None,
        }
        result = job.get("result")

    if isinstance(result, GenerationResult):
        payload["files"] = {
            "obj": result.obj_files,
            "mtl": result.mtl_files,
            "zip": result.zip_path,
            "metadata": result.metadata_path,
            "logs": result.logs_path,
        }

    return payload


@app.get("/api/jobs/{job_id}/download")
def api_download(job_id: str):
    with job_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, detail="job not found")
        result = job.get("result")

    if not isinstance(result, GenerationResult) or not result.zip_path:
        raise HTTPException(400, detail="job not finished")

    return FileResponse(result.zip_path, filename=Path(result.zip_path).name, media_type="application/zip")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
