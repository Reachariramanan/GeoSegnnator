# Upload Still Slow? Diagnostic Checklist

## Quick Check (30 seconds)

- [ ] Browser shows status "⏳ Loading raster preview..."
- [ ] Status bar is visible and updating
- [ ] Browser console (F12) has no red errors
- [ ] It's been less than 10 seconds

→ **If all checked:** Just wait, it's normal!

## Something Seems Stuck (> 20 seconds)

### Check 1: Browser Console
```
Open: F12 (Developer Tools)
Go to: Console tab
Look for: Red error messages
```

**If you see errors like:**
- `POST /api/upload-raster 500` → Backend crashed
- `Connection refused` → Backend not running
- `Timeout` → Taking too long

→ **Skip to "Backend is Down" section below**

### Check 2: Backend Health
```bash
curl http://localhost:8000/indices
```

**Expected:** JSON list of index names
**If stuck/error:** Backend is down

### Check 3: File Size
```bash
ls -lh ~/your-file.tif
```

**Expected timing by size:**
- < 10 MB: < 5 seconds total
- 10-50 MB: 5-15 seconds total
- 50-100 MB: 15-30 seconds total
- > 100 MB: 30+ seconds total

→ **If within range:** Just wait

## Backend is Down

### Step 1: Restart Backend
```bash
# Kill old process
pkill -f "tile_server"

# Start new one
cd /home/hariramanan/NTRO/rd/backend
python -m uvicorn src.tile_server:app --host 0.0.0.0 --port 8000 &
```

### Step 2: Verify It Started
```bash
sleep 2
curl http://localhost:8000/indices
```

→ Should get JSON back

### Step 3: Reload Browser
```
F5 or Ctrl+R
```

## Still Having Issues?

### Full System Reset
```bash
# Kill everything
pkill -f "uvicorn.*tile_server"
pkill -f "vite.*5173"

# Wait
sleep 3

# Restart both
bash /home/hariramanan/NTRO/rd/start-all.sh
```

### Test with Sample File
```bash
# Use the guaranteed working test file
cd /home/hariramanan/NTRO/rd

# In browser, upload:
data/20210321_044121_69_245c_3B_AnalyticMS_SR_8b_clip.tif

# This 4.8 MB file MUST load in < 5 seconds
```

### If Sample Works But Yours Doesn't

Your TIF file might be:
1. **Corrupted** → Test with gdalinfo
2. **In wrong format** → Should be GeoTIFF with georeferencing
3. **Too large** → Try cropping to smaller region

```bash
# Test your file
gdalinfo /path/to/your/file.tif

# Should print metadata, not errors
```

## Normal Progression

### Small file (4.8 MB) - What you should see:
```
T+0s:  Click upload
T+0.5s: Spinner shows
T+1s:  Status: "⏳ Loading raster preview..."
T+2s:  Map appears with raster
T+3s:  Status clears
T+5s:  All indices cached, ready to segment
```

### Large file (117 MB) - What you should see:
```
T+0s:  Click upload
T+0.5s: Spinner shows
T+2s:  Status: "⏳ Loading raster preview..."
T+7s:  Map appears with raster
T+8s:  Status clears
T+30s: All indices cached, ready to segment
       (Can use app while indices compute)
```

## If Everything Fails

Last resort:
```bash
# Check what's running
ps aux | grep -E "uvicorn|vite" | grep -v grep

# Stop everything manually
pkill uvicorn
pkill vite
pkill node

# Start clean
cd /home/hariramanan/NTRO/rd
bash start-all.sh

# Wait 10 seconds for services to be ready
sleep 10

# Test again
curl http://localhost:8000/indices
```

## Key Ports to Verify

```bash
# Frontend should be on 5173
lsof -i :5173

# Backend should be on 8000
lsof -i :8000

# If either is missing, services didn't start
```

## When to Assume It's Broken

Stop waiting and troubleshoot if:
- **No status message changes for 30+ seconds**
- **Browser console shows red errors**
- **curl http://localhost:8000/indices fails**
- **File is < 100MB but takes > 60 seconds**

Otherwise, it's probably just precomputing indices (which can take time).
