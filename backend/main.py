"""FastAPI entry point for GeoSegmenter tile server."""
from src.tile_server import app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
