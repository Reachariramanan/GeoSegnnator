# Why Upload Takes Time - Loading Times Explained

## What Happens When You Upload a TIF

```
1. Browser → Upload file to /api/upload-raster
   ├─ File transfer (depends on file size)
   └─ Backend saves & reads metadata
   ✓ Response in ~100ms
   
2. Frontend receives response
   ├─ Sets loading=false
   ├─ Updates map bounds
   ├─ Shows "Loading raster preview..."
   └─ Requests /api/preview.png
   
3. Backend generates preview image
   ├─ Reprojection to WGS84
   ├─ Downsampling (1024×1024 by default)
   ├─ Converts to PNG
   └─ Returns image (~1-3 seconds)
   
4. Browser displays raster on map
   ├─ Shows "⏳ Loading raster preview..."
   └─ Once loaded: Status clears
   
5. [Background] Backend precomputes indices
   ├─ NDVI, NDBI, NDWI, EVI, etc. (26 total)
   ├─ Takes 5-30 seconds depending on file size
   └─ Results cached for instant filtering
```

## Expected Loading Times

### For Small File (4.8 MB - Sentinel-2 clip)
- **File upload:** < 0.5 seconds
- **Metadata read:** < 0.1 seconds
- **Preview generation:** 0.8-1.5 seconds
- **Map display:** Immediate
- **Index precomputation:** 3-5 seconds (background)
- **Total to see map:** ~2 seconds
- **Total until ready for segmentation:** ~5-7 seconds

### For Medium File (50-100 MB)
- **File upload:** 2-5 seconds
- **Metadata read:** < 0.1 seconds
- **Preview generation:** 2-4 seconds
- **Map display:** Immediate
- **Index precomputation:** 10-20 seconds (background)
- **Total to see map:** ~5-10 seconds
- **Total until ready for segmentation:** ~15-30 seconds

### For Large File (117 MB - mountain_road.tif)
- **File upload:** 5-10 seconds
- **Metadata read:** < 0.1 seconds
- **Preview generation:** 3-6 seconds
- **Map display:** Immediate
- **Index precomputation:** 20-60 seconds (background)
- **Total to see map:** ~10-15 seconds
- **Total until ready for segmentation:** ~30-75 seconds

## What You'll See During Loading

### Stage 1: Upload
```
[Right sidebar]
❌ No raster loaded
[Spinning indicator]
```

### Stage 2: Preview Generation (1-3 seconds)
```
[Map area]
⏳ Loading raster preview...

[You can't interact yet - map is rendering]
```

### Stage 3: Map Ready (success!)
```
[Map appears with raster]
[Status clears or shows "✓ Raster loaded"]

[Right sidebar]
✓ Index names available
✓ You can place seeds now
```

### Stage 4: Indices Computing (background)
```
[Right sidebar shows]
Precompute Progress:
  ✓ 5 / 26 indices ready
  
[You can use the app - filtering gets faster as more indices complete]
[Segmentation works even if not all indices are done]
```

## Why Is Preview Generation Slow?

The preview endpoint does several expensive operations:

1. **Read full raster from disk** (up to 117 MB)
2. **Reproject to WGS84** (geographic coordinates)
3. **Resample/downsample** to fit requested size
4. **Render as PNG** image

For a 759×638 pixel image (small), this takes 1.1 seconds.
For a 3000×2500 pixel image (large), this can take 5+ seconds.

## How to Speed Up

### Option 1: Upload Smaller Files
- Crop your raster to region of interest
- Use COG (Cloud-Optimized GeoTIFF) format
- Reduces preview generation time significantly

### Option 2: Reduce Preview Size
The preview is requested at `max_size=1024` by default.
Change in [Map.tsx:157](src/components/Map.tsx#L157) to smaller size:
```typescript
// Current: 1024×1024 (good balance)
// Faster: 512×512 (load in 0.3s, less detail)
// Slower: 2048×2048 (3-5s, more detail)
```

### Option 3: Optimize Backend
- Use GPU-accelerated reprojection (pyproj-async)
- Cache reprojected tiles
- Generate preview at upload time

## Performance Tips

✅ **Do This:**
- Use test files < 50 MB first
- Be patient during "Loading raster preview..." (it's working)
- Don't refresh while precomputing indices

❌ **Avoid This:**
- Uploading 1GB+ files on first try
- Clicking "Upload" multiple times
- Assuming app is broken if it takes 5+ seconds

## Healthy Signs (App is Working)

✓ Status shows "⏳ Loading raster preview..."
✓ Status bar shows progress
✓ `/index-cache-status` shows precompute progress
✓ Map appears after 5-15 seconds
✓ You can interact with the map immediately (before indices finish)

## Unhealthy Signs (Something is Wrong)

❌ Upload button does nothing for >60 seconds
❌ Browser console shows errors (F12)
❌ `/index-cache-status` shows errors
❌ Map never appears after 30 seconds
❌ Status stuck on "Loading raster preview..." forever

**If stuck:** Check browser console (F12 → Console) for errors, or restart backend.
