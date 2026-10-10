from typing import Any, Optional
from pydantic import BaseModel, Field


class FileInfo(BaseModel):
    id: str
    filename: str
    feature_count: int
    crs: Optional[str] = None
    status: str
    created_at: str


class MeasurementFeature(BaseModel):
    feature_id: int
    geometry_type: Optional[str] = None
    geometry: Optional[dict[str, Any]] = None
    crs: Optional[str] = None
    properties: dict[str, Any] = Field(default_factory=dict)
    measurement: Optional[dict[str, Any]] = None
    measurement_status: str
    message: Optional[str] = None


class MeasurementsResponse(BaseModel):
    file_id: str
    filename: str
    feature_count: int
    source_crs: Optional[str] = None
    features: list[MeasurementFeature]
