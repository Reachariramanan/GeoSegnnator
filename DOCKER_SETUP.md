# GeoSegmenter Docker Setup

## Container Status

Both services are running in a Docker container named **`Geosegmenter`**:

- **Backend (geosegmenter-backend)**: FastAPI tile server
  - Port: `8090` (mapped from container port 8080)
  - API Docs: http://localhost:8090/docs
  - Health: ✅ Running

- **Frontend (geosegmenter-frontend)**: React/Vite SPA
  - Port: `3000` (mapped from container port 5173)
  - URL: http://localhost:3000
  - Health: ✅ Running

## Quick Start

```bash
# Start containers
cd /home/hariramanan/NTRO/rd
docker-compose up -d

# Stop containers
docker-compose down

# View logs
docker-compose logs -f

# Access the app
# - Frontend: http://localhost:3000
# - Backend API Docs: http://localhost:8090/docs
```

## Network Access

From external machine (e.g., `192.168.200.23`):
- Frontend: `http://192.168.200.23:3000`
- Backend API: `http://192.168.200.23:8090`

## Files Created/Modified

- `Dockerfile.backend` - Python/FastAPI backend image
- `Dockerfile.frontend` - Node/Vite frontend image
- `docker-compose.yml` - Orchestration file
- `backend/main.py` - FastAPI entry point
- `frontend/src/vite-env.d.ts` - TypeScript Vite types
- `frontend/tsconfig.json` - Updated with vite/client types

## Architecture

```
geosegmenter-net (bridge network)
├── geosegmenter-backend (Python 3.11, FastAPI)
│   └── Port 8090:8080
└── geosegmenter-frontend (Node 20, Vite)
    └── Port 3000:5173
```

The frontend and backend communicate within the Docker network, with both exposed to the host machine.
