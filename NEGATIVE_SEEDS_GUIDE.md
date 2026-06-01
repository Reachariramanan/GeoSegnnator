# How to Place Negative Seeds

## Overview
You can now place both **positive** (road) and **negative** (non-road) seeds to improve training data quality and avoid the "only one class" error.

## Steps to Place Negative Seeds

1. **Enable seed placement**
   - Check "Place seeds on click" in the Seeds section of the right sidebar

2. **Choose seed type**
   - Two buttons appear: **"+ Road"** and **"− Non-Road"**
   - Select **"− Non-Road"** (the button will turn red)
   - Now your cursor will place negative seeds

3. **Click on the map**
   - Click on areas that are **NOT roads** (buildings, vegetation, water, etc.)
   - Negative seeds will appear as red numbered circles
   - Each seed shows a **✗** symbol in the sidebar list

4. **Place positive seeds**
   - Switch back to **"+ Road"** (green button)
   - Click on actual road pixels
   - Positive seeds appear as green numbered circles with **✓**

## Best Practices for Seed Placement

### Rule 1: Spatial Separation
- **Keep positive and negative seeds far apart**
- Don't place negative seeds in regions that connect to positive seed regions
- If they're in the same connected area, that region gets rejected

### Rule 2: Clear Examples
- **Positive seeds:** Place on obvious road pixels (center of roads, clear asphalt)
- **Negative seeds:** Place on obvious non-road pixels (buildings, vegetation, shadows)
- Avoid boundaries and ambiguous areas

### Rule 3: Variety
- Place multiple seeds across different areas
- Helps the algorithm learn the full range of road and non-road spectral values
- Example: 3-5 positive seeds on different road areas + 3-5 negative seeds on different non-road types

### Rule 4: Threshold Matters
- The threshold slider controls which pixels become "candidate" regions
- If all positive seeds fall outside candidate regions, they won't be included
- Try adjusting the threshold if training fails

## Troubleshooting

### Error: "Only one class in training labels"
This means the training mask has no road pixels. Common causes:

1. **All negative seeds are excluding positive seeds**
   - Solution: Place negative seeds far from positive seeds
   
2. **Threshold is too high/low**
   - Solution: Adjust the threshold slider before running training
   - Try values between 0.3-0.6 for most indices
   
3. **All seeds are in the same region**
   - Solution: Place positive and negative seeds in spatially distinct areas

### Visual Guide
```
GOOD: Seeds are spatially separated
┌─────────────────────────────┐
│  🟢🟢 (Road)    🔴🔴 (Non-road) │
│  [connected region]         │
│                            │
└─────────────────────────────┘

BAD: Seeds overlap in same region
┌─────────────────────────────┐
│  🟢🔴 (Same region) 🔴🟢  │
│  ❌ All get rejected!       │
└─────────────────────────────┘
```

## Workflow Example

1. Load a GeoTIFF raster
2. **Toggle "Apply Index Visualization"** to see spectral values
3. Enable seed placement → select "Road" mode
4. Place 3-4 positive seeds on clear road pixels
5. Switch to "Non-Road" mode
6. Place 3-4 negative seeds on clear non-road pixels (buildings, trees, etc.)
7. Click **"Search All Filters"** to run training
8. Check the results—if you see warnings, adjust seeds and retry

## What Gets Sent to Training?

The training API now receives seeds like:
```json
{
  "seeds": [
    {"row": 100, "col": 200, "kind": "pos"},
    {"row": 150, "col": 250, "kind": "pos"},
    {"row": 50, "col": 400, "kind": "neg"},
    {"row": 300, "col": 100, "kind": "neg"}
  ],
  "threshold": 0.5,
  "index_names": ["ndvi", "ndbi", "...]
}
```

The backend creates a mask from positive seeds, then excludes regions that also contain negative seeds.
