import tempfile
import zipfile
from pathlib import Path
from typing import Any

import geopandas as gpd
from pyproj import CRS
from shapely.geometry import mapping


class GeospatialProcessingError(ValueError):
    """Raised when an uploaded file cannot be safely read as geospatial data."""


def _json_safe(value: Any) -> Any:
    """Convert common pandas/numpy values to JSON-compatible Python values."""
    if value is None:
        return None
    try:
        # Handles NaN, pandas NA, numpy scalar types, timestamps, etc.
        import pandas as pd
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (ValueError, TypeError):
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (ValueError, TypeError):
            pass
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            return None
        return value
    return str(value)


def _safe_extract_zip(zip_path: str, destination: str) -> Path:
    """Extract a ZIP without allowing path traversal; return the first .shp."""
    try:
        with zipfile.ZipFile(zip_path) as archive:
            members = archive.infolist()
            if not members:
                raise GeospatialProcessingError("The ZIP archive is empty.")
            for member in members:
                target = (Path(destination) / member.filename).resolve()
                root = Path(destination).resolve()
                if target != root and root not in target.parents:
                    raise GeospatialProcessingError("ZIP contains an unsafe file path.")
                if member.file_size > 100 * 1024 * 1024:
                    raise GeospatialProcessingError("A file inside the ZIP exceeds the 100 MB limit.")
            archive.extractall(destination)
    except zipfile.BadZipFile as exc:
        raise GeospatialProcessingError("The uploaded .zip file is invalid.") from exc

    shapefiles = list(Path(destination).rglob("*.shp"))
    if not shapefiles:
        raise GeospatialProcessingError("The ZIP archive does not contain a .shp file.")
    if len(shapefiles) > 1:
        # Deterministic selection; users should upload one Shapefile dataset per ZIP.
        raise GeospatialProcessingError(
            "The ZIP contains multiple .shp files. Upload one Shapefile dataset per ZIP."
        )
    shp = shapefiles[0]
    if not list(shp.parent.glob(shp.stem + ".shx")) and not list(shp.parent.glob(shp.stem + ".SHX")):
        raise GeospatialProcessingError("The Shapefile is missing its required .shx index file.")
    return shp


def _read_geodataframe(file_path: str, extension: str) -> gpd.GeoDataFrame:
    try:
        if extension == ".zip":
            with tempfile.TemporaryDirectory(prefix="geo_extract_") as temp_dir:
                shp_path = _safe_extract_zip(file_path, temp_dir)
                gdf = gpd.read_file(shp_path)
                # Return a materialized frame before temporary extraction disappears.
                return gdf
        if extension == ".kml":
            # KML coordinates are geographic (longitude/latitude); GDAL's KML driver
            # is commonly available with GeoPandas/Fiona installations.
            try:
                return gpd.read_file(file_path, driver="KML")
            except Exception:
                return gpd.read_file(file_path)
    except GeospatialProcessingError:
        raise
    except Exception as exc:
        raise GeospatialProcessingError(
            "Could not read the geospatial file. Check that it is a valid KML or zipped Shapefile "
            "and that the required Shapefile sidecar files are present."
        ) from exc
    raise GeospatialProcessingError("Unsupported file type. Upload a .kml or .zip file.")


def _select_measurement_crs(gdf: gpd.GeoDataFrame) -> CRS:
    """Choose a local projected CRS in metres, normally the appropriate UTM zone."""
    if gdf.crs is None:
        raise GeospatialProcessingError(
            "The source CRS is missing. Provide a Shapefile .prj file or a KML with coordinates."
        )
    geographic = gdf.to_crs("EPSG:4326")
    try:
        estimated = geographic.estimate_utm_crs()
        if estimated:
            crs = CRS.from_user_input(estimated)
            if crs.is_projected:
                return crs
    except Exception:
        pass
    # Equal-area fallback for datasets too broad or unusual for UTM. Units are metres.
    return CRS.from_epsg(6933)


def process_geospatial_file(file_path: str, extension: str) -> dict[str, Any]:
    gdf = _read_geodataframe(file_path, extension)
    if gdf.empty:
        source_crs = gdf.crs.to_string() if gdf.crs else None
        return {"source_crs": source_crs, "feature_count": 0, "features": []}

    if gdf.crs is None and extension == ".kml":
        # KML coordinates are defined in WGS84 longitude/latitude.
        gdf = gdf.set_crs("EPSG:4326")
    if gdf.crs is None:
        raise GeospatialProcessingError(
            "The Shapefile has no CRS metadata. Include its .prj file."
        )

    source_crs = CRS.from_user_input(gdf.crs).to_string()
    measurement_crs = _select_measurement_crs(gdf)
    projected = gdf.to_crs(measurement_crs)

    features = []
    for index, (_, row) in enumerate(gdf.iterrows()):
        geom = row.geometry
        properties = {
            str(key): _json_safe(value)
            for key, value in row.drop(labels=[gdf.geometry.name]).to_dict().items()
        }
        geometry_json = mapping(geom) if geom is not None and not geom.is_empty else None
        geometry_type = geom.geom_type if geom is not None and not geom.is_empty else None
        measurement = None
        measurement_status = "NOT_REQUIRED"
        message = None

        if geometry_type in ("Polygon", "MultiPolygon"):
            projected_geom = projected.geometry.iloc[index]
            if projected_geom is not None and not projected_geom.is_empty:
                measurement = {
                    "area": round(float(projected_geom.area), 4),
                    "unit": "square_metres",
                    "crs": measurement_crs.to_string(),
                }
                measurement_status = "COMPLETED"
            else:
                measurement_status = "UNAVAILABLE"
                message = "Geometry is empty; area could not be calculated."
        elif geometry_type in ("LineString", "MultiLineString", "LinearRing"):
            projected_geom = projected.geometry.iloc[index]
            if projected_geom is not None and not projected_geom.is_empty:
                measurement = {
                    "length": round(float(projected_geom.length), 4),
                    "unit": "metres",
                    "crs": measurement_crs.to_string(),
                }
                measurement_status = "COMPLETED"
            else:
                measurement_status = "UNAVAILABLE"
                message = "Geometry is empty; length could not be calculated."
        elif geometry_type in ("Point", "MultiPoint"):
            measurement_status = "NOT_REQUIRED"
            message = "Point geometries do not require measurement."
        elif geometry_type is None:
            measurement_status = "UNAVAILABLE"
            message = "Feature has no geometry."
        else:
            measurement_status = "UNSUPPORTED"
            message = f"Measurement is not implemented for geometry type '{geometry_type}'."

        features.append({
            "feature_id": index,
            "geometry_type": geometry_type,
            "geometry": _json_safe(geometry_json),
            "crs": source_crs,
            "properties": properties,
            "measurement": measurement,
            "measurement_status": measurement_status,
            "message": message,
        })

    return {
        "source_crs": source_crs,
        "feature_count": len(features),
        "features": features,
    }
