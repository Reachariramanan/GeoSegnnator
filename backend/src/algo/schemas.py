from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ComputeIndexRequest(BaseModel):
    image_path: str
    index_name: str
    params: Dict[str, Any] = Field(default_factory=dict)
    output_path: Optional[str] = None


class ComputeIndexResponse(BaseModel):
    output_path: str


class SegmentationRequest(BaseModel):
    image_path: str
    index_name: str
    seed_geojson: Dict[str, Any]
    seed_mode: str = "pixel"
    threshold: float = 0.7
    params: Dict[str, Any] = Field(default_factory=dict)
    output_path: Optional[str] = None


class SegmentationResponse(BaseModel):
    output_path: str


class KFoldRequest(BaseModel):
    image_path: str
    index_names: List[str]
    seed_geojson: Dict[str, Any]
    seed_mode: str = "pixel"
    threshold: float = 0.7


class KFoldResponse(BaseModel):
    best_index: str
    best_iou: float
    best_f1: float
    best_threshold: float
    index_scores: Dict[str, float]
    index_scores_f1: Dict[str, float] = Field(default_factory=dict)
    index_thresholds: Dict[str, float] = Field(default_factory=dict)
    model: Dict[str, Any]
    warning: Optional[str] = None


class SymbologyResponse(BaseModel):
    ramps: Dict[str, Any]
    index_defaults: Dict[str, Any]
    percentile_default: List[float]


class SymbologyStatsRequest(BaseModel):
    image_path: str
    index_name: str
    params: Dict[str, Any] = Field(default_factory=dict)
    percentile_low: float = 2.0
    percentile_high: float = 98.0


class SymbologyStatsResponse(BaseModel):
    min: float
    max: float
    p_low: float
    p_high: float


class RenderIndexRequest(BaseModel):
    image_path: str
    index_name: str
    params: Dict[str, Any] = Field(default_factory=dict)
    ramp_id: Optional[str] = None
    range_mode: str = "auto"
    range_min: Optional[float] = None
    range_max: Optional[float] = None
    percentile_low: float = 2.0
    percentile_high: float = 98.0


class RenderMaskRequest(BaseModel):
    mask_path: str
    ramp_id: str = "mask"


# Progressive segmentation schemas

class ProgressiveSegmentationRequest(BaseModel):
    image_path: str
    index_names: List[str] = Field(default_factory=lambda: ["ndvi", "evi", "savi"])
    seed_geojson: Dict[str, Any]
    seed_mode: str = "pixel"
    threshold: float = 0.7
    roi_geojson: Optional[Dict[str, Any]] = None
    roi_dimming: float = 0.3
    tile_size: int = 1024
    overlap: int = 128
    max_iterations: int = 10
    params: Dict[str, Any] = Field(default_factory=dict)
    output_path: Optional[str] = None


class ProgressiveSegmentationResponse(BaseModel):
    output_path: str
    segmentation_metadata: Dict[str, Any]
    formula_learning: Dict[str, Any]
    tile_layout: List[Dict[str, Any]]
    best_index: str
    total_tiles: int
    completed_tiles: int


class ROIMaskRequest(BaseModel):
    image_path: str
    roi_geojson: Dict[str, Any]
    seed_mode: str = "crs"
    buffer_pixels: int = 0


class ROIMaskResponse(BaseModel):
    mask_path: str
    mask_stats: Dict[str, Any]
    roi_area_pixels: int
    total_area_pixels: int


class TileProcessRequest(BaseModel):
    image_path: str
    tile_index: int
    tile_size: int = 1024
    overlap: int = 128
    index_name: str = "ndvi"
    seed_geojson: Optional[Dict[str, Any]] = None
    threshold: float = 0.7
    output_path: Optional[str] = None


class TileProcessResponse(BaseModel):
    tile_index: int
    output_path: Optional[str]
    mask_stats: Dict[str, Any]
    segmentation_metadata: Dict[str, Any]
    progress: float
