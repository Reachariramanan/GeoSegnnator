# TIF Loading Keeps Spinning - Troubleshooting Guide

## Quick Diagnosis

### Step 1: Check Browser Console
1. Open DevTools: **F12**
2. Go to **Console** tab
3. Upload a TIF file
4. Look for red error messages

**Common errors you might see:**
- `POST /api/upload-raster 500` → Backend crash (see Step 2)
- `POST /api/upload-raster 404` → Wrong API endpoint
- `Network timeout` → File too large or backend hung

### Step 2: Check Backend Logs
If the console shows a 500 error, check the backend:

```bash
# Find the backend process
ps aux | grep uvicorn

# Check logs (if running with logging)
tail -100 /var/log/backend.log

# Or run backend in foreground to see logs:
cd /home/hariramanan/NTRO/rd/backend
python -m uvicorn src.tile_server:app --reload --host 0.0.0.0 --port 8000
```

### Step 3: Test the API Directly
```bash
# Test if backend is running
curl http://localhost:8000/indices

# You should get JSON back. If not, backend isn't running.
```

## Common Causes & Fixes

### Cause 1: TIF File is Corrupted
**Symptom:** Spinning forever, then times out after 60 seconds

**Solution:**
```bash
# Test the TIF with GDAL
gdalinfo /path/to/your/file.tif

# Should print metadata. If it errors, file is corrupted.
```

**Fix:** Use a valid GeoTIFF file. Test with the sample:
```bash
cp /home/hariramanan/NTRO/rd/data/sample.tif ~/test.tif
# Upload ~/test.tif in the UI
```

### Cause 2: TIF is Too Large
**Symptom:** Uploads fine, but hangs during "index precomputation"

**Details:** After uploading, backend starts computing spectral indices (NDVI, NDBI, etc.) in the background. For huge rasters (>1GB), this can take minutes.

**Solution:**
1. Wait longer (5-10 minutes)
2. Check backend logs to see progress
3. Or use a smaller raster

### Cause 3: Backend Crashed Silently
**Symptom:** Request hangs forever, browser console shows nothing

**Solution:**
```bash
# Kill old backend process
pkill -f "uvicorn.*tile_server"

# Restart it
cd /home/hariramanan/NTRO/rd/backend
python -m uvicorn src.tile_server:app --host 0.0.0.0 --port 8000
```

### Cause 4: Backend Not Running
**Symptom:** Upload button does nothing, no error message

**Solution:**
```bash
# Check if backend is running
curl http://localhost:8000/indices

# If no response, start it:
cd /home/hariramanan/NTRO/rd/backend
python -m uvicorn src.tile_server:app --host 0.0.0.0 --port 8000 &
```

### Cause 5: Frontend Pointing to Wrong API
**Symptom:** Console shows `404 /api/upload-raster`

**Solution:** Check [frontend/src/components/LeftSidebar.tsx](LeftSidebar.tsx):
```typescript
const API_BASE = '/api'  // This should point to your backend

// If backend is on different port/host, change to:
const API_BASE = 'http://localhost:8000/api'
```

## What Happens During Upload

```
1. User drops TIF file
   ↓
2. Frontend → POST /api/upload-raster (file data)
   ↓
3. Backend saves file to disk
   ↓
4. Backend reads metadata with GDAL
   ↓
5. Backend returns immediately with metadata
   ↓
6. Frontend sets loading=false (spinner stops) ✓
   ↓
7. [Background] Backend computes all spectral indices
   ↓
8. Frontend polls /index-cache-status to track progress
```

**If stuck at step 5-6:** Backend error (check logs)
**If stuck at step 7-8:** Index computation is slow (wait longer)

## Test With Sample File

The safest way to test:

```bash
cd /home/hariramanan/NTRO/rd

# Start backend
cd backend && python -m uvicorn src.tile_server:app --host 0.0.0.0 --port 8000 &

# Start frontend
cd frontend && npm run dev

# In browser, upload data/sample.tif
# Should load in <5 seconds
```

## Timeout Settings

The frontend now has **60-second timeout** for uploads. If it still hangs after 60 seconds, the backend is definitely hung or unreachable.

## File Size Recommendations

- **<100 MB:** Fast (<10 seconds)
- **100-500 MB:** Medium (30-60 seconds)
- **>500 MB:** Slow (2-5 minutes)

If your file is >1GB and precomputation takes forever, that's normal. The backend is computing indices on every pixel.

## Logs to Check

```bash
# Check system logs
journalctl -u your-service-name

# Check Python errors (if running in terminal)
# Look for "Failed to load raster" or "RasterReader error"

# Check if file was saved
ls -lh ~/data/*.tif
```

## Still Stuck?

Try these in order:

1. **Hard refresh browser** (Ctrl+Shift+R)
2. **Restart backend** (pkill uvicorn + restart)
3. **Check file** (gdalinfo file.tif)
4. **Check logs** (cat logs/backend.log)
5. **Use sample.tif** (cp data/sample.tif ~/test.tif)
