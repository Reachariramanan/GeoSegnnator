import { useEffect, useRef, useState, Dispatch, SetStateAction } from 'react'
import L from 'leaflet'
import { AppState, RasterMetadata, Seed } from '../App'
import styles from './Map.module.css'

interface MapProps {
  state: AppState
  setState: Dispatch<SetStateAction<AppState>>
}

function latLngToPixel(lat: number, lng: number, meta: RasterMetadata): { row: number; col: number } {
  const { bounds, width, height } = meta
  const xFrac = (lng - bounds.left) / (bounds.right - bounds.left)
  const yFrac = (bounds.top - lat) / (bounds.top - bounds.bottom)
  const col = Math.round(xFrac * (width - 1))
  const row = Math.round(yFrac * (height - 1))
  return { row, col }
}

function isInsideBounds(lat: number, lng: number, meta: RasterMetadata): boolean {
  const { bounds } = meta
  return lat >= bounds.bottom && lat <= bounds.top && lng >= bounds.left && lng <= bounds.right
}

function seedIcon(num: number, kind: 'pos' | 'neg' = 'pos'): L.DivIcon {
  const bgColor = kind === 'pos' ? '#22c55e' : '#ef4444'
  const borderColor = kind === 'pos' ? '#16a34a' : '#991b1b'
  return L.divIcon({
    className: 'seed-marker',
    html: `<div style="
      width: 22px; height: 22px;
      background: ${bgColor};
      border: 2px solid ${borderColor};
      border-radius: 50%;
      color: #fff;
      font-size: 11px;
      font-weight: 700;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 2px 6px rgba(0,0,0,0.6);
      font-family: -apple-system, sans-serif;
    ">${num}</div>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11],
  })
}

export default function Map({ state, setState }: MapProps) {
  const mapContainer = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const rasterOverlay = useRef<L.ImageOverlay | null>(null)
  const indexOverlay = useRef<L.ImageOverlay | null>(null)
  const maskOverlay = useRef<L.ImageOverlay | null>(null)
  const boundsRect = useRef<L.Rectangle | null>(null)
  const seedMarkers = useRef<L.Marker[]>([])
  const [status, setStatus] = useState<string>('')

  // Refs to avoid stale closures inside Leaflet event handlers
  const segEnabledRef = useRef(state.segmentationEnabled)
  const metadataRef = useRef(state.metadata)
  const seedKindRef = useRef(state.seedKind)
  useEffect(() => { segEnabledRef.current = state.segmentationEnabled }, [state.segmentationEnabled])
  useEffect(() => { metadataRef.current = state.metadata }, [state.metadata])
  useEffect(() => { seedKindRef.current = state.seedKind }, [state.seedKind])

  // Initialize map once
  useEffect(() => {
    if (!mapContainer.current || map.current) return

    map.current = L.map(mapContainer.current, {
      center: [20, 0],
      zoom: 2,
      worldCopyJump: true,
      zoomControl: true,    // zoom stays top-left (Leaflet default)
      attributionControl: true,
    })

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; OpenStreetMap &copy; CARTO',
      subdomains: 'abcd',
      maxZoom: 20,
    }).addTo(map.current)

    map.current.on('click', (e: L.LeafletMouseEvent) => {
      const enabled = segEnabledRef.current
      const meta = metadataRef.current
      if (!enabled) {
        setStatus('Enable seed-placement in the right panel to drop points')
        return
      }
      if (!meta) {
        setStatus('Load a raster first')
        return
      }
      const { lat, lng } = e.latlng
      if (!isInsideBounds(lat, lng, meta)) {
        setStatus('Clicked outside raster bounds')
        return
      }
      const { row, col } = latLngToPixel(lat, lng, meta)
      const kind = seedKindRef.current
      const newSeed: Seed = { lat, lng, row, col, kind }
      setState((s) => ({ ...s, seeds: [...s.seeds, newSeed] }))
      setStatus(`${kind === 'pos' ? 'Positive' : 'Negative'} seed added at row ${row}, col ${col}`)
    })

    return () => {
      if (map.current) {
        map.current.remove()
        map.current = null
      }
    }
  }, [])

  // Cursor reflects seed-placement mode
  useEffect(() => {
    if (!mapContainer.current) return
    mapContainer.current.style.cursor = state.segmentationEnabled ? 'crosshair' : ''
  }, [state.segmentationEnabled])

  // Render raster overlay when metadata changes
  useEffect(() => {
    if (!map.current || !state.metadata) return

    if (rasterOverlay.current) {
      map.current.removeLayer(rasterOverlay.current)
      rasterOverlay.current = null
    }
    if (boundsRect.current) {
      map.current.removeLayer(boundsRect.current)
      boundsRect.current = null
    }

    const b = state.metadata.bounds
    const validLat = (v: number) => v >= -90 && v <= 90
    const validLon = (v: number) => v >= -180 && v <= 180
    if (!validLat(b.bottom) || !validLat(b.top) || !validLon(b.left) || !validLon(b.right)) {
      setStatus(`Invalid bounds: lat[${b.bottom}, ${b.top}] lon[${b.left}, ${b.right}]`)
      return
    }

    const leafletBounds: L.LatLngBoundsExpression = [
      [b.bottom, b.left],
      [b.top, b.right],
    ]

    boundsRect.current = L.rectangle(leafletBounds, {
      color: '#888',
      weight: 2,
      fillOpacity: 0,
      dashArray: '5, 5',
      interactive: false,
    }).addTo(map.current)

    setStatus('Loading raster preview...')
    const previewUrl = `/api/preview.png?max_size=1024&cb=${Date.now()}`

    rasterOverlay.current = L.imageOverlay(previewUrl, leafletBounds, {
      opacity: state.rasterOpacity,
      interactive: false,
    }).addTo(map.current)

    rasterOverlay.current.on('load', () => {
      setStatus('')
      setTimeout(() => setStatus(''), 2000)
    })
    rasterOverlay.current.on('error', () => {
      setStatus('Failed to load raster preview')
      setTimeout(() => setStatus(''), 5000)
    })

    map.current.fitBounds(leafletBounds, { padding: [40, 40], maxZoom: 18 })
  }, [state.metadata])

  // Raster opacity slider sync
  useEffect(() => {
    if (rasterOverlay.current) rasterOverlay.current.setOpacity(state.rasterOpacity)
  }, [state.rasterOpacity])

  // Index / Band visualization overlay (above raster, below mask)
  useEffect(() => {
    if (!map.current || !state.metadata) return

    if (indexOverlay.current) {
      map.current.removeLayer(indexOverlay.current)
      indexOverlay.current = null
    }
    if (!state.indexPreviewUrl) return

    const b = state.metadata.bounds
    const leafletBounds: L.LatLngBoundsExpression = [
      [b.bottom, b.left],
      [b.top, b.right],
    ]
    indexOverlay.current = L.imageOverlay(state.indexPreviewUrl, leafletBounds, {
      opacity: state.indexLayerOpacity,
      interactive: false,
    }).addTo(map.current)
    // Keep mask above index
    if (maskOverlay.current) {
      maskOverlay.current.bringToFront()
    }
  }, [state.indexPreviewUrl, state.metadata])

  // Index overlay opacity slider sync
  useEffect(() => {
    if (indexOverlay.current) indexOverlay.current.setOpacity(state.indexLayerOpacity)
  }, [state.indexLayerOpacity])

  // Mask overlay sync (on top of raster)
  useEffect(() => {
    if (!map.current || !state.metadata) return

    // Tear down existing
    if (maskOverlay.current) {
      map.current.removeLayer(maskOverlay.current)
      maskOverlay.current = null
    }

    if (!state.maskUrl) return

    const b = state.metadata.bounds
    const leafletBounds: L.LatLngBoundsExpression = [
      [b.bottom, b.left],
      [b.top, b.right],
    ]
    maskOverlay.current = L.imageOverlay(state.maskUrl, leafletBounds, {
      opacity: state.maskOpacity,
      interactive: false,
    }).addTo(map.current)
  }, [state.maskUrl, state.metadata])

  // Mask opacity slider sync
  useEffect(() => {
    if (maskOverlay.current) maskOverlay.current.setOpacity(state.maskOpacity)
  }, [state.maskOpacity])

  // Sync seed markers with state
  useEffect(() => {
    if (!map.current) return
    seedMarkers.current.forEach((m) => map.current!.removeLayer(m))
    seedMarkers.current = []

    state.seeds.forEach((seed, idx) => {
      const marker = L.marker([seed.lat, seed.lng], { icon: seedIcon(idx + 1, seed.kind) })
        .addTo(map.current!)
        .bindTooltip(`Seed ${idx + 1} (${seed.kind === 'pos' ? 'positive' : 'negative'}): row ${seed.row}, col ${seed.col}`, { direction: 'top' })
      marker.on('click', (e) => {
        L.DomEvent.stopPropagation(e)
        setState((s) => ({ ...s, seeds: s.seeds.filter((_, i) => i !== idx) }))
      })
      seedMarkers.current.push(marker)
    })
  }, [state.seeds])

  const recenter = () => {
    if (!map.current || !state.metadata) return
    const b = state.metadata.bounds
    map.current.fitBounds([[b.bottom, b.left], [b.top, b.right]], { padding: [40, 40], maxZoom: 18 })
  }

  const toggleSeedMode = () => {
    setState((s) => ({ ...s, segmentationEnabled: !s.segmentationEnabled }))
  }

  return (
    <div className={styles.mapWrapper}>
      <div ref={mapContainer} className={styles.mapContainer} />

      {/* Bottom-left: coords */}
      {state.metadata && (
        <div className={styles.coordsBar}>
          <span>
            {state.metadata.bounds.left.toFixed(4)}, {state.metadata.bounds.bottom.toFixed(4)} → {state.metadata.bounds.right.toFixed(4)}, {state.metadata.bounds.top.toFixed(4)}
          </span>
        </div>
      )}

      {/* Top-center status pill */}
      {status && (
        <div className={styles.statusBar}>
          {status.includes('Loading') && <span style={{ marginRight: '6px' }}>⏳</span>}
          {status.includes('Failed') && <span style={{ marginRight: '6px' }}>❌</span>}
          {status}
        </div>
      )}

      {/* Bottom-right toolbar */}
      {state.metadata && (
        <div className={styles.toolbar}>
          <button
            className={`${styles.toolBtn} ${state.segmentationEnabled ? styles.toolBtnActive : ''}`}
            onClick={toggleSeedMode}
            title={state.segmentationEnabled ? 'Disable seed placement' : 'Enable seed placement'}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 11c1.657 0 3-1.343 3-3s-1.343-3-3-3-3 1.343-3 3 1.343 3 3 3z" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.5c0 5-7.5 12.5-7.5 12.5S4.5 13.5 4.5 8.5a7.5 7.5 0 1115 0z" />
            </svg>
            <span className={styles.toolLabel}>Seed</span>
            {state.seeds.length > 0 && <span className={styles.toolBadge}>{state.seeds.length}</span>}
          </button>

          <button
            className={styles.toolBtn}
            onClick={() => setState((s) => ({ ...s, seeds: [] }))}
            disabled={state.seeds.length === 0}
            title="Clear all seeds"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6M1 7h22M9 7V4a1 1 0 011-1h4a1 1 0 011 1v3" />
            </svg>
          </button>

          <div className={styles.toolDivider} />

          <button className={styles.toolBtn} onClick={recenter} title="Recenter on raster">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
            </svg>
          </button>

          {state.maskUrl && (
            <>
              <div className={styles.toolDivider} />
              <button
                className={styles.toolBtn}
                onClick={() => setState((s) => {
                  if (s.maskUrl) URL.revokeObjectURL(s.maskUrl)
                  return { ...s, maskUrl: null }
                })}
                title="Remove mask overlay"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                </svg>
                <span className={styles.toolLabel}>Mask</span>
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}
