import json
import os
import uuid
from datetime import timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import UploadedFile
from .schemas import FileInfo, MeasurementsResponse
from .services.geospatial import GeospatialProcessingError, process_geospatial_file

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Geospatial File Measurement API",
    description=(
        "Upload a zipped Shapefile or KML, inspect its features, and calculate polygon areas "
        "and line lengths using a projected coordinate reference system."
    ),
    version="1.0.0",
)

STORAGE_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads")).resolve()
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
STORAGE_DIR.mkdir(parents=True, exist_ok=True)


def _file_info(record: UploadedFile) -> dict:
    created = record.created_at
    if created and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return {
        "id": record.id,
        "filename": record.filename,
        "feature_count": record.feature_count,
        "crs": record.source_crs,
        "status": record.status,
        "created_at": created.isoformat() if created else None,
    }


@app.get("/", tags=["Health"])
def health_check():
    return {"status": "ok", "service": "Geospatial File Measurement API"}


@app.post("/api/files/", response_model=FileInfo, status_code=status.HTTP_201_CREATED, tags=["Files"])
async def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    filename = Path(file.filename or "").name
    extension = Path(filename).suffix.lower()
    if extension not in (".zip", ".kml"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Upload a .zip containing a Shapefile or a .kml file.",
        )

    file_id = str(uuid.uuid4())
    suffix = extension
    destination = STORAGE_DIR / f"{file_id}{suffix}"
    total = 0
    try:
        with destination.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit.",
                    )
                out.write(chunk)

        if total == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        result = process_geospatial_file(str(destination), extension)
        record = UploadedFile(
            id=file_id,
            filename=filename,
            stored_path=str(destination),
            source_crs=result["source_crs"],
            feature_count=result["feature_count"],
            status="COMPLETED",
            features_json=json.dumps(result["features"], ensure_ascii=False, allow_nan=False),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return _file_info(record)

    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except GeospatialProcessingError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="File processing failed unexpectedly.") from exc
    finally:
        await file.close()


@app.get("/api/files/{file_id}/", response_model=FileInfo, tags=["Files"])
def get_file_info(file_id: str, db: Session = Depends(get_db)):
    record = db.get(UploadedFile, file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found.")
    return _file_info(record)


@app.get(
    "/api/files/{file_id}/measurements/",
    response_model=MeasurementsResponse,
    tags=["Measurements"],
)
def get_measurements(file_id: str, db: Session = Depends(get_db)):
    record = db.get(UploadedFile, file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found.")
    return {
        "file_id": record.id,
        "filename": record.filename,
        "feature_count": record.feature_count,
        "source_crs": record.source_crs,
        "features": json.loads(record.features_json),
    }


@app.exception_handler(404)
async def not_found_handler(_request, _exc):
    # FastAPI's normal 404 behavior remains useful; this handler standardizes generic 404s.
    return JSONResponse(status_code=404, content={"detail": "Resource not found."})
