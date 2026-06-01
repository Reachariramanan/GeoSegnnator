#!/bin/bash
# Start both backend and frontend for GeoSegmenter

set -e

echo "🚀 Starting GeoSegmenter..."

# Start backend
echo "📡 Starting backend (port 8000)..."
cd /home/hariramanan/NTRO/rd/backend
python -m uvicorn src.tile_server:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Start frontend
echo "🎨 Starting frontend (port 5173)..."
cd /home/hariramanan/NTRO/rd/frontend
npm run dev &
FRONTEND_PID=$!

echo ""
echo "✅ Both services started!"
echo ""
echo "🌐 Frontend: http://localhost:5173/"
echo "📡 Backend:  http://localhost:8000/"
echo ""
echo "📂 Test TIF files:"
echo "  - /home/hariramanan/NTRO/rd/data/20210321_044121_69_245c_3B_AnalyticMS_SR_8b_clip.tif (4.8 MB)"
echo "  - /home/hariramanan/NTRO/rd/data/mountain_road.tif (117 MB)"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Wait for both processes
wait
