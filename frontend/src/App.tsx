import { useEffect, useState } from 'react'
import axios from 'axios'
import Map from './components/Map'
import LeftSidebar from './components/LeftSidebar'
import RightSidebar from './components/RightSidebar'
import styles from './App.module.css'

export interface Seed {
  lat: number
  lng: number
  row: number
  col: number
  kind: 'pos' | 'neg'
}

export interface RasterMetadata {
  crs: string
  bounds: { left: number; bottom: number; right: number; top: number }
  width: number
  height: number
  bands: number
  dtype: string
}

export interface IndexInfo {
  name: string
  display_name: string
  required_bands: string[]
  status: string
  note: string | null
  params: Record<string, any>
}

export interface RampStop {
  pos: number
  color: string
  alpha: number
}

export interface RampDef {
  name: string
  stops: RampStop[]
}

export interface IndexDefault {
  ramp: string
  range_mode: 'auto' | 'fixed' | 'percentile'
  range?: [number, number]
}

export interface IndexCacheStatus {
  path: string | null
  total: number
  done: number
  in_progress: boolean
  ready: string[]
  errors: { name: string; message: string }[]
}

export interface TrainScore {
  name: string
  iou: number
  f1: number
  suggested_threshold: number | null
  error?: string
}

export const CUSTOM_RAMP_KEY = '__custom__'

export type ViewMode = 'rgb' | 'index' | 'band'
export type RangeMode = 'auto' | 'fixed' | 'percentile'

export interface AppState {
  rasterPath: string | null
  metadata: RasterMetadata | null

  // Seed placement
  segmentationEnabled: boolean
  seedKind: 'pos' | 'neg'
  seeds: Seed[]

  // Layers
  rasterOpacity: number
  maskUrl: string | null
  maskOpacity: number

  // Analysis settings
  indices: IndexInfo[]
  selectedIndex: string
  threshold: number
  useProgressive: boolean

  // Symbology
  ramps: Record<string, RampDef>
  selectedRamp: string                // ramp id, or CUSTOM_RAMP_KEY
  customRamp: RampStop[] | null
  indexDefaults: Record<string, IndexDefault>
  rangeMode: RangeMode

  // Visualization layer
  viewMode: ViewMode
  selectedBand: number                // 1..bands
  indexPreviewUrl: string | null
  indexLayerOpacity: number

  // Precompute progress
  indexCacheStatus: IndexCacheStatus | null

  // Best-filter ranking
  trainRanking: TrainScore[] | null

  // Status
  loading: boolean
  busyTask: string | null   // 'segment', 'train', 'load', 'render', null
  error: string | null
}

const API_BASE = '/api'

export default function App() {
  const [state, setState] = useState<AppState>({
    rasterPath: null,
    metadata: null,
    segmentationEnabled: false,
    seedKind: 'pos',
    seeds: [],
    rasterOpacity: 1,
    maskUrl: null,
    maskOpacity: 0.7,
    indices: [],
    selectedIndex: 'ndvi',
    threshold: 0.4,
    useProgressive: false,
    ramps: {},
    selectedRamp: 'diverging',
    customRamp: null,
    indexDefaults: {},
    rangeMode: 'auto',
    viewMode: 'rgb',
    selectedBand: 1,
    indexPreviewUrl: null,
    indexLayerOpacity: 0.85,
    indexCacheStatus: null,
    trainRanking: null,
    loading: false,
    busyTask: null,
    error: null,
  })

  // Load the indices catalog on mount (cached by the browser; cheap)
  useEffect(() => {
    axios.get(`${API_BASE}/indices`)
      .then((res) => setState((s) => ({ ...s, indices: res.data })))
      .catch((err) => console.warn('Could not fetch /indices', err))
  }, [])

  // Load ramp presets + per-index defaults once on mount
  useEffect(() => {
    axios.get(`${API_BASE}/ramps`)
      .then((res) => setState((s) => ({
        ...s,
        ramps: res.data.ramps || {},
        indexDefaults: res.data.defaults || {},
      })))
      .catch((err) => console.warn('Could not fetch /ramps', err))
  }, [])

  // Poll index-cache status while a raster is loaded.
  // Fast (1.5s) while in_progress, slow (15s) when idle, paused if no raster.
  useEffect(() => {
    if (!state.rasterPath) return
    let cancelled = false
    const fetchStatus = () =>
      axios.get(`${API_BASE}/index-cache-status`)
        .then((res) => {
          if (cancelled) return res.data
          setState((s) => ({ ...s, indexCacheStatus: res.data }))
          return res.data
        })
        .catch(() => null)
    fetchStatus()
    let timer: ReturnType<typeof setTimeout> | null = null
    const tick = async () => {
      const status = await fetchStatus()
      if (cancelled) return
      const delay = status && status.in_progress ? 1500 : 15000
      timer = setTimeout(tick, delay)
    }
    timer = setTimeout(tick, 1500)
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [state.rasterPath])

  // When raster changes, revoke any stale index preview blob URL
  useEffect(() => {
    return () => {
      // cleanup on unmount only — per-change cleanup is handled inline at the
      // point where indexPreviewUrl is replaced
    }
  }, [])

  return (
    <div className={styles.container}>
      <LeftSidebar state={state} setState={setState} />
      <div className={styles.mapArea}>
        <Map state={state} setState={setState} />
      </div>
      <RightSidebar state={state} setState={setState} />
      {state.error && (
        <div className={styles.error} onClick={() => setState((s) => ({ ...s, error: null }))}>
          {state.error}
        </div>
      )}
    </div>
  )
}
