from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Integer, String, Text
from .database import Base


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id = Column(String(36), primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    stored_path = Column(String(1024), nullable=False)
    source_crs = Column(String(128), nullable=True)
    feature_count = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="PROCESSING")
    features_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc))
