# Deployment Guide

## Local Development

### Prerequisites
- Python 3.10+
- Node.js 16+ (frontend)
- GDAL/PROJ libraries (for rasterio)
- CUDA 11.x or 12.x (optional, for GPU)

### Windows Setup (GDAL)

**Option 1: conda (recommended)**
```bash
conda install gdal
```

**Option 2: pip with wheels**
```bash
pip install rasterio --only-binary :all:
```

**Option 3: OSGeo4W**
- Download OSGeo4W installer
- Install GDAL + Python bindings
- Add to PATH

### Backend Setup

```bash
cd backend
python -m venv venv

# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate

pip install -r requirements.txt

# Install GPU support (optional)
pip install cupy-cuda11x  # NVIDIA CUDA 11.x
# or
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Access at `http://localhost:5173`

### Run Full Stack

**Terminal 1: Backend**
```bash
cd backend
source venv/bin/activate  # Windows: venv\Scripts\activate
python -m uvicorn src.tile_server:app --reload --port 8000 --host 0.0.0.0
```

**Terminal 2: Frontend**
```bash
cd frontend
npm run dev
```

**Open browser:** `http://localhost:5173`

---

## Docker Deployment

### Backend Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install GDAL dependencies
RUN apt-get update && apt-get install -y \
    gdal-bin \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

ENV GDAL_CONFIG=/usr/bin/gdal-config

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Optional: CUDA support
# FROM nvidia/cuda:11.8.0-runtime-ubuntu22.04
# RUN pip install cupy-cuda11x

COPY backend/src ./src

CMD ["uvicorn", "src.tile_server:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Docker Compose

```yaml
version: '3.8'

services:
  backend:
    build:
      context: .
      dockerfile: backend.Dockerfile
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
    environment:
      - DEBUG=false
    command: uvicorn src.tile_server:app --host 0.0.0.0 --port 8000

  frontend:
    build:
      context: frontend
      dockerfile: Dockerfile
    ports:
      - "5173:5173"
    environment:
      - VITE_API_BASE=http://localhost:8000
```

### Build & Run

```bash
docker-compose up -d

# View logs
docker-compose logs -f backend

# Stop
docker-compose down
```

---

## Cloud Deployment (AWS/GCP/Azure)

### AWS Lambda (Tile Endpoint)

```python
# serverless.yml
service: geosegmenter

provider:
  name: aws
  runtime: python3.11
  region: us-west-2

functions:
  tile:
    handler: handler.tile
    memorySize: 3008
    timeout: 60
    environment:
      RASTER_PATH: s3://bucket/cog.tif
    events:
      - http:
          path: tiles/{z}/{x}/{y}.png
          method: get

plugins:
  - serverless-python-requirements

package:
  individually: true
```

### GCP Cloud Run

```bash
gcloud builds submit --tag gcr.io/PROJECT/geosegmenter

gcloud run deploy geosegmenter \
  --image gcr.io/PROJECT/geosegmenter \
  --platform managed \
  --region us-central1 \
  --memory 4Gi \
  --allow-unauthenticated
```

### S3/GCS with COG

```python
import rasterio
import rasterio.env

# AWS S3
with rasterio.env.Env(GDAL_DISABLE_READDIR_ON_OPEN='YES'):
    with rasterio.open('s3://bucket/cog.tif') as src:
        data = src.read_window(window)

# GCS
with rasterio.open('gs://bucket/cog.tif') as src:
    data = src.read_window(window)
```

---

## Production Configuration

### Backend (FastAPI)

**`backend/main.py`**
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
import logging

app = FastAPI(title="GeoSegmenter", docs_url=None)

# Security middleware
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "*.example.com"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://example.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
```

### Reverse Proxy (Nginx)

```nginx
upstream backend {
    server backend:8000;
}

server {
    listen 80;
    server_name api.example.com;

    client_max_body_size 100M;

    location / {
        proxy_pass http://backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        
        # Cache tile requests (1 hour)
        proxy_cache tile_cache;
        proxy_cache_valid 200 1h;
        proxy_cache_key "$scheme$request_method$host$request_uri";
    }

    location /tiles {
        proxy_pass http://backend;
        
        # Strong caching for tiles
        add_header Cache-Control "public, max-age=3600";
    }
}

proxy_cache_path /var/cache/nginx/tiles levels=1:2 keys_zone=tile_cache:100m;
```

### Environment Variables

```bash
# .env
RASTER_PATH=/data/satellite.tif
TILE_CACHE_SIZE_MB=1000
MAX_REGION_SIZE_MB=500
ENABLE_GPU=true
GPU_TYPE=cuda  # cuda or cpu
LOG_LEVEL=info
CORS_ORIGINS=https://example.com,https://app.example.com
WORKERS=4
```

### Systemd Service (Linux)

```ini
# /etc/systemd/system/geosegmenter.service
[Unit]
Description=GeoSegmenter Tile Server
After=network.target

[Service]
Type=notify
User=geosegmenter
WorkingDirectory=/opt/geosegmenter
EnvironmentFile=/opt/geosegmenter/.env

ExecStart=/opt/geosegmenter/venv/bin/uvicorn \
    src.tile_server:app \
    --port 8000 \
    --workers 4

Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable geosegmenter
sudo systemctl start geosegmenter
sudo systemctl status geosegmenter
```

---

## Monitoring & Logging

### Prometheus Metrics

```python
from prometheus_client import Counter, Histogram, start_http_server

tile_requests = Counter('tile_requests_total', 'Total tile requests', ['status'])
tile_duration = Histogram('tile_duration_seconds', 'Tile render time')
cache_hits = Counter('cache_hits_total', 'Cache hits')

@app.get("/tiles/{z}/{x}/{y}.png")
async def get_tile(z: int, x: int, y: int):
    with tile_duration.time():
        # ... render logic ...
```

### Log Aggregation (ELK Stack)

**Logstash Config:**
```json
input {
  file {
    path => "/var/log/geosegmenter/*.log"
    codec => "json"
  }
}

filter {
  if [duration] {
    mutate { convert => { "duration" => "float" } }
  }
}

output {
  elasticsearch {
    hosts => ["elasticsearch:9200"]
    index => "geosegmenter-%{+YYYY.MM.dd}"
  }
}
```

### Health Checks

```python
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "1.0.0",
        "gpu_available": torch.cuda.is_available(),
    }

@app.get("/ready")
async def ready():
    if RASTER_PATH is None:
        return {"status": "not_ready"}, 503
    return {"status": "ready"}
```

---

## Performance Tuning

### Worker Processes

```bash
# CPU-bound: workers = 2 × cores + 1
# I/O-bound (tile reading): workers = 4 × cores

uvicorn src.tile_server:app --workers 8 --loop uvloop
```

### Memory Limits

```python
# Prevent runaway memory
import resource

def limit_memory():
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    resource.setrlimit(resource.RLIMIT_AS, (4 * 1024 * 1024 * 1024, hard))

limit_memory()
```

### GPU Memory Management

```python
import torch

# Pre-allocate GPU memory
torch.cuda.empty_cache()
torch.cuda.max_memory_allocated()

# Monitor
logger.info(f"GPU memory: {torch.cuda.memory_allocated() / 1e9:.1f}GB")
```

---

## Benchmarking

### Load Test (Locust)

```python
# locustfile.py
from locust import HttpUser, task, between
import random

class TileUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def get_tile(self):
        z = random.randint(8, 14)
        x = random.randint(0, 2**z - 1)
        y = random.randint(0, 2**z - 1)
        self.client.get(f"/tiles/{z}/{x}/{y}.png")
```

Run:
```bash
locust -f locustfile.py --host=http://localhost:8000
```

### Benchmarking Segmentation

```bash
python -m pytest backend/benchmarks/bench_segmentation.py -v --benchmark-only
```

---

## Troubleshooting

### GDAL/PROJ Issues

```bash
# Check GDAL config
gdalinfo --version

# Set PROJ database
export PROJ_LIB=/usr/share/proj

# Test rasterio
python -c "import rasterio; print(rasterio.__gdal_version__)"
```

### GPU Out of Memory

```python
# Reduce tile cache or segmentation batch size
cache = TileCache(max_size_mb=200)  # Was 500

# Or process smaller regions
MAX_REGION_MB = 200  # Was 500
```

### Slow Tile Reads

```bash
# Check if file is COG
gdalinfo -checksum input.tif | grep -i "blockx\|blocky"

# Should show internal tiling (512x512 or similar)
# If not, create COG version
gdal_translate -of COG -co COMPRESS=lzw -co BLOCKSIZE=512 input.tif output_cog.tif
```

---

## Scaling Strategy

### Vertical Scaling
1. Increase `--workers` (CPU cores)
2. Increase tile cache (`max_size_mb`)
3. Add GPU (if CPU-bound on segmentation)

### Horizontal Scaling
1. Deploy multiple backend instances
2. Use load balancer (Nginx, HAProxy)
3. Share tile cache via Redis:

```python
import redis

cache_backend = redis.Redis(host='redis', port=6379)

def get_tile(...):
    key = f"tile:{z}:{x}:{y}"
    cached = cache_backend.get(key)
    if cached:
        return cached
    # ... render ...
    cache_backend.setex(key, 3600, png_bytes)
    return png_bytes
```

---

## Rollback Plan

```bash
# Kubernetes rolling update
kubectl set image deployment/geosegmenter \
  geosegmenter=gcr.io/project/geosegmenter:v2

# Rollback if issues
kubectl rollout undo deployment/geosegmenter

# Docker Compose
docker-compose up -d --build
# To rollback:
docker-compose down
docker image rm geosegmenter:latest
docker-compose up -d  # Uses previous image
```
