# Geospatial File Measurement API

A FastAPI backend that accepts a zipped Shapefile (`.zip`) or KML (`.kml`), extracts feature information, and calculates polygon area and line length using a projected coordinate reference system (CRS).

## Features

- Upload `.zip` files containing one Shapefile dataset or `.kml` files.
- Extract feature index, geometry type, geometry coordinates, CRS, and properties.
- Calculate polygon and multipolygon area in square metres.
- Calculate LineString and MultiLineString length in metres.
- Return a clear status for points and unsupported geometry types instead of crashing.
- Choose a projected CRS for measurement instead of calculating directly in longitude/latitude degrees.
- Persist file metadata and processed feature results in SQLite.
- Interactive API documentation through Swagger UI.

## Requirements

- Python 3.10+
- GDAL/KML driver support in the installed GeoPandas/Fiona stack for KML reading. KML driver availability depends on your operating system's geospatial packages.

## Run locally

### 1. Clone the repository

```bash
git clone https://github.com/YOUR-USERNAME/geospatial-file-measurement-api.git
cd geospatial-file-measurement-api
```

### 2. Create and activate a virtual environment

Windows PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

GeoPandas depends on native geospatial libraries. If installation fails, use a clean virtual environment and follow the GeoPandas installation guide for your operating system.

### 4. Start the server

```bash
uvicorn app.main:app --reload
```

The API runs at `http://127.0.0.1:8000`.

- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc
- Health check: http://127.0.0.1:8000/

SQLite database and uploaded files are created locally. By default, the database is `geospatial_api.db` and uploads are stored in `uploads/`.

## API endpoints

### 1. Upload and process a file

`POST /api/files/`

Content type: `multipart/form-data`

Form field: `file`

Accepted files:
- `.zip` containing exactly one `.shp` dataset. Include the associated `.shx`, `.dbf`, and `.prj` files where applicable.
- `.kml`

Example using curl:

```bash
curl -X POST "http://127.0.0.1:8000/api/files/" \
  -F "file=@./samples/survey.kml"
```

Example response (`201 Created`):

```json
{
  "id": "7b5d5b38-9fd8-4a7e-8f3f-ae8913acb442",
  "filename": "survey.kml",
  "feature_count": 2,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "created_at": "2026-10-09T08:00:00+00:00"
}
```

The ID and timestamp above are illustrative. The API returns generated values.

### 2. Get file information

`GET /api/files/{id}/`

Example:

```bash
curl "http://127.0.0.1:8000/api/files/7b5d5b38-9fd8-4a7e-8f3f-ae8913acb442/"
```

Returns filename, feature count, source CRS, processing status, and creation timestamp.

### 3. Get feature measurements

`GET /api/files/{id}/measurements/`

Example:

```bash
curl "http://127.0.0.1:8000/api/files/7b5d5b38-9fd8-4a7e-8f3f-ae8913acb442/measurements/"
```

Example response (coordinates abbreviated for readability):

```json
{
  "file_id": "7b5d5b38-9fd8-4a7e-8f3f-ae8913acb442",
  "filename": "survey.kml",
  "feature_count": 2,
  "source_crs": "EPSG:4326",
  "features": [
    {
      "feature_id": 0,
      "geometry_type": "Polygon",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[80.0, 16.0], [80.01, 16.0], [80.01, 16.01], [80.0, 16.0]]]
      },
      "crs": "EPSG:4326",
      "properties": {"name": "Plot A"},
      "measurement": {
        "area": 1190000.0,
        "unit": "square_metres",
        "crs": "EPSG:32644"
      },
      "measurement_status": "COMPLETED",
      "message": null
    },
    {
      "feature_id": 1,
      "geometry_type": "Point",
      "geometry": {"type": "Point", "coordinates": [80.005, 16.005]},
      "crs": "EPSG:4326",
      "properties": {"name": "Marker"},
      "measurement": null,
      "measurement_status": "NOT_REQUIRED",
      "message": "Point geometries do not require measurement."
    }
  ]
}
```

The measurement numbers and IDs in this sample are illustrative, not expected results for every input file.

### Common errors

- `400 Bad Request`: unsupported extension, invalid ZIP, missing Shapefile components/CRS, or unreadable geospatial file.
- `404 Not Found`: no file exists for the requested ID.
- `413 Request Entity Too Large`: upload exceeds the default 50 MB limit.
- `500 Internal Server Error`: unexpected processing error.

## Architecture

```text
Client
  |
  | POST /api/files/ (multipart upload)
  v
FastAPI route (app/main.py)
  |
  v
File validation + local storage
  |
  v
GeoPandas / Fiona reads KML or zipped Shapefile
  |
  v
CRS normalization and projected CRS selection
  |
  v
Shapely calculates polygon area / line length
  |
  v
Feature results serialized as JSON
  |
  v
SQLite stores metadata and processed features
  |
  +--> GET /api/files/{id}/
  +--> GET /api/files/{id}/measurements/
```

### Main files

- `app/main.py`: routes, upload validation, error handling, and API orchestration.
- `app/services/geospatial.py`: safe ZIP extraction, geospatial reading, CRS selection, and measurements.
- `app/models.py`: SQLite file metadata model.
- `app/database.py`: database engine and session management.
- `app/schemas.py`: response schemas.
- `tests/`: automated test suite (extend with representative real-world KML and Shapefile fixtures).

## Measurement and CRS strategy

Coordinates in EPSG:4326 are longitude/latitude degrees; area and length should not be calculated directly from those values.

The service converts the dataset to WGS84 to estimate a local UTM CRS, then transforms geometries to that projected CRS before measuring:
- Polygon / MultiPolygon: `geometry.area`, reported in square metres.
- LineString / MultiLineString: `geometry.length`, reported in metres.
- Point / MultiPoint: no measurement.
- Other geometry types: `UNSUPPORTED` with a message.

If a suitable UTM CRS cannot be estimated, the service falls back to EPSG:6933, a metre-based equal-area projection. This fallback is most appropriate for area calculations; very large or cross-zone line datasets may require a more specialized CRS strategy.

The reported feature geometry remains in the source CRS. The `measurement.crs` field tells clients which projected CRS was used for the measurement.

## Design decisions

- **FastAPI:** lightweight REST API framework with automatic OpenAPI and Swagger documentation.
- **GeoPandas and Shapely:** established Python tools for reading vector datasets and working with geometries.
- **SQLite:** keeps local setup simple while persisting processed results between application restarts. PostgreSQL/PostGIS would be a stronger choice for a multi-user production service.
- **Process on upload:** measurements are computed once during upload and stored, so the measurements endpoint is fast. For very large datasets, a background job queue would be preferable.
- **Local UTM CRS:** provides metre-based measurements for datasets covering a local area. Datasets spanning multiple UTM zones or continents may need per-feature CRS selection or a geodesic strategy.
- **ZIP safety:** extraction checks archive paths and individual member sizes to reduce path-traversal and oversized-member risks.

## Learning outcomes

This project provides practice with:
- Building REST endpoints and validating multipart file uploads.
- Handling errors and returning consistent JSON responses.
- Reading vector geospatial formats and inspecting feature attributes.
- Understanding coordinate reference systems and map projections.
- Performing area and length calculations with Shapely.
- Persisting API results with SQLAlchemy and SQLite.
- Structuring a backend into routes, schemas, models, and services.

## Future scope

- Add authentication, per-user file ownership, and rate limiting.
- Add PostgreSQL/PostGIS for scalable spatial queries.
- Move heavy processing to background jobs and add processing progress.
- Add file deletion and retention policies.
- Add configurable measurement units (hectares, acres, kilometres).
- Add stronger file-content validation, malware scanning, and archive-bomb protections.
- Add tests with real KML and zipped Shapefile fixtures, CI, Docker, and deployment configuration.
- Improve projection selection for global datasets and datasets spanning multiple UTM zones.

## Limitations

- Each ZIP must contain one Shapefile dataset.
- Shapefiles without a `.prj` file are rejected because their CRS cannot be safely inferred.
- KML reading depends on KML driver support in the installed GDAL/Fiona environment.
- This starter project stores uploaded files on local disk and is intended as a clear assessment submission, not a fully hardened public production deployment.

## License

Choose a license before publishing this repository (for example, MIT).
