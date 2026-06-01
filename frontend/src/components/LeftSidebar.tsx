import { useState, useRef, useEffect, Dispatch, SetStateAction } from 'react'
import axios from 'axios'
import { AppState, CUSTOM_RAMP_KEY, RampStop, ViewMode } from '../App'
import RampPicker from './RampPicker'
import styles from './Sidebar.module.css'

interface Props {
  state: AppState
  setState: Dispatch<SetStateAction<AppState>>
}

const API_BASE = '/api'

export default function LeftSidebar({ state, setState }: Props) {
  const [filePath, setFilePath] = useState('')
  const [isDragging, setIsDragging] = useState(false)
  const [cacheStats, setCacheStats] = useState<any>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const loadByPath = async (path: string) => {
    if (!path) {
      setState((s) => ({ ...s, error: 'Please provide a file path' }))
      return
    }
    setState((s) => ({ ...s, loading: true, busyTask: 'load', error: null, maskUrl: null }))
    try {
      const res = await axios.post(`${API_BASE}/load-raster`, { filepath: path }, {
        timeout: 60000,
      })
      setState((s) => ({
        ...s,
        rasterPath: res.data.path || path,
        metadata: res.data.metadata,
        seeds: [],
        loading: false,
        busyTask: null,
      }))
      setFilePath(res.data.path || path)
    } catch (err: any) {
      const errorMsg = err.response?.data?.detail
        || (err.code === 'ECONNABORTED' ? 'Request timeout (file not found or backend error?)' : 'Failed to load raster')
      setState((s) => ({
        ...s,
        error: errorMsg,
        loading: false,
        busyTask: null,
      }))
      console.error('Load error:', err)
    }
  }

  const uploadFile = async (file: File) => {
    setState((s) => ({ ...s, loading: true, busyTask: 'load', error: null, maskUrl: null }))
    const form = new FormData()
    form.append('file', file)
    try {
      const res = await axios.post(`${API_BASE}/upload-raster`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 60000,
      })
      setState((s) => ({
        ...s,
        rasterPath: res.data.path,
        metadata: res.data.metadata,
        seeds: [],
        loading: false,
        busyTask: null,
      }))
      setFilePath(res.data.path)
    } catch (err: any) {
      const errorMsg = err.response?.data?.detail
        || (err.code === 'ECONNABORTED' ? 'Request timeout (file too large?)' : 'Failed to upload raster')
      setState((s) => ({
        ...s,
        error: errorMsg,
        loading: false,
        busyTask: null,
      }))
      console.error('Upload error:', err)
    }
  }

  const fetchCacheStats = async () => {
    try {
      const res = await axios.get(`${API_BASE}/tile-cache-stats`)
      setCacheStats(res.data)
    } catch {/* ignore */}
  }

  // Refresh cache stats every 10s while a raster is loaded
  useEffect(() => {
    if (!state.metadata) return
    fetchCacheStats()
    const id = setInterval(fetchCacheStats, 10000)
    return () => clearInterval(id)
  }, [state.metadata])

  const clearCache = async () => {
    try {
      await axios.post(`${API_BASE}/clear-cache`)
      fetchCacheStats()
    } catch {/* ignore */}
  }

  const removeMask = () => setState((s) => ({ ...s, maskUrl: null }))

  const removeIndexLayer = () => setState((s) => {
    if (s.indexPreviewUrl) URL.revokeObjectURL(s.indexPreviewUrl)
    return { ...s, indexPreviewUrl: null, viewMode: 'rgb' }
  })

  const renderBand = async () => {
    if (!state.metadata) return
    setState((s) => ({ ...s, busyTask: 'render', error: null }))
    try {
      const body: any = {
        band: state.selectedBand,
        ramp: state.selectedRamp === CUSTOM_RAMP_KEY ? 'sequential' : state.selectedRamp,
        range_mode: state.rangeMode === 'auto' ? 'percentile' : state.rangeMode,
      }
      if (state.selectedRamp === CUSTOM_RAMP_KEY && state.customRamp) {
        body.custom_ramp = { stops: state.customRamp }
      }
      const res = await axios.post(`${API_BASE}/render/band`, body, { responseType: 'blob' })
      const url = URL.createObjectURL(res.data)
      setState((s) => {
        if (s.indexPreviewUrl) URL.revokeObjectURL(s.indexPreviewUrl)
        return { ...s, indexPreviewUrl: url, viewMode: 'band', busyTask: null }
      })
    } catch (err: any) {
      let detail = 'Render failed'
      if (err.response?.data instanceof Blob) {
        try { detail = JSON.parse(await err.response.data.text()).detail || detail } catch {}
      } else if (err.response?.data?.detail) {
        detail = err.response.data.detail
      }
      setState((s) => ({ ...s, busyTask: null, error: detail }))
    }
  }

  return (
    <aside className={styles.sidebar}>
      <div className={styles.header}>
        <h1 className={styles.title}>GeoSegmenter</h1>
        <p className={styles.subtitle}>Spectral Raster Analysis</p>
      </div>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Dataset</h2>

        <div
          className={`${styles.dropZone} ${isDragging ? styles.dragActive : ''}`}
          onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setIsDragging(false)
            const f = e.dataTransfer.files[0]
            if (f) uploadFile(f)
          }}
          onClick={() => fileInputRef.current?.click()}
        >
          <svg className={styles.dropIcon} viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
          </svg>
          <p className={styles.dropText}>Drop GeoTIFF</p>
          <p className={styles.dropSubtext}>or click to browse</p>
          <input
            ref={fileInputRef}
            type="file"
            accept=".tif,.tiff,.TIF,.TIFF"
            onChange={(e) => {
              const f = e.currentTarget.files?.[0]
              if (f) uploadFile(f)
            }}
            style={{ display: 'none' }}
          />
        </div>

        <input
          type="text"
          placeholder="Or paste file path..."
          value={filePath}
          onChange={(e) => setFilePath(e.target.value)}
          className={styles.pathInput}
        />

        <button
          onClick={() => loadByPath(filePath)}
          disabled={state.loading || !filePath}
          className={styles.btn}
        >
          {state.busyTask === 'load' ? (<><span className={styles.spinner} />Loading...</>) : 'Load from Path'}
        </button>

        {state.rasterPath && (
          <div className={styles.fileChip}>
            <span className={styles.fileIcon}>📄</span>
            <span className={styles.fileName}>{state.rasterPath.split(/[/\\]/).pop()}</span>
          </div>
        )}
      </section>

      {state.metadata && state.indexCacheStatus && state.indexCacheStatus.total > 0 && (
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>Index precompute</h2>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: 11, color: '#bbb' }}>
            <span>
              {state.indexCacheStatus.done}/{state.indexCacheStatus.total} ready
            </span>
            <span style={{ color: state.indexCacheStatus.in_progress ? '#f2d492' : '#7bc47f' }}>
              {state.indexCacheStatus.in_progress ? 'computing…' : 'done'}
            </span>
          </div>
          <div style={{ height: 6, background: '#2a2a2a', borderRadius: 3, overflow: 'hidden' }}>
            <div
              style={{
                width: `${(100 * state.indexCacheStatus.done) / Math.max(1, state.indexCacheStatus.total)}%`,
                height: '100%',
                background: state.indexCacheStatus.in_progress ? '#f2d492' : '#7bc47f',
                transition: 'width 0.25s ease',
              }}
            />
          </div>
          {state.indexCacheStatus.errors && state.indexCacheStatus.errors.length > 0 && (
            <p style={{ marginTop: 6, fontSize: 10, color: '#d88' }}>
              {state.indexCacheStatus.errors.length} failed: {state.indexCacheStatus.errors.map(e => e.name).join(', ')}
            </p>
          )}
        </section>
      )}

      {state.metadata && (
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>Layers</h2>

          <div className={styles.layerRow}>
            <div className={styles.layerHeader}>
              <span className={styles.layerName}>Base Raster</span>
              <span className={styles.layerBadge}>{state.metadata.bands}-band</span>
            </div>
            <div className={styles.opacityRow}>
              <label className={styles.opacityLabel}>Opacity</label>
              <input
                type="range" min="0" max="100"
                value={state.rasterOpacity * 100}
                onChange={(e) => setState((s) => ({ ...s, rasterOpacity: Number(e.target.value) / 100 }))}
              />
              <span className={styles.opacityValue}>{Math.round(state.rasterOpacity * 100)}%</span>
            </div>
          </div>

          {state.indexPreviewUrl && (
            <div className={styles.layerRow}>
              <div className={styles.layerHeader}>
                <span className={styles.layerName}>
                  {state.viewMode === 'band' ? `Band ${state.selectedBand}` : `Index: ${state.selectedIndex.toUpperCase()}`}
                </span>
                <button className={styles.removeBtn} onClick={removeIndexLayer} title="Remove">×</button>
              </div>
              <div className={styles.opacityRow}>
                <label className={styles.opacityLabel}>Opacity</label>
                <input
                  type="range" min="0" max="100"
                  value={state.indexLayerOpacity * 100}
                  onChange={(e) => setState((s) => ({ ...s, indexLayerOpacity: Number(e.target.value) / 100 }))}
                />
                <span className={styles.opacityValue}>{Math.round(state.indexLayerOpacity * 100)}%</span>
              </div>
            </div>
          )}

          {state.maskUrl ? (
            <div className={styles.layerRow}>
              <div className={styles.layerHeader}>
                <span className={styles.layerName}>Segmentation Mask</span>
                <button className={styles.removeBtn} onClick={removeMask} title="Remove mask">×</button>
              </div>
              <div className={styles.opacityRow}>
                <label className={styles.opacityLabel}>Opacity</label>
                <input
                  type="range" min="0" max="100"
                  value={state.maskOpacity * 100}
                  onChange={(e) => setState((s) => ({ ...s, maskOpacity: Number(e.target.value) / 100 }))}
                />
                <span className={styles.opacityValue}>{Math.round(state.maskOpacity * 100)}%</span>
              </div>
            </div>
          ) : (
            <p className={styles.placeholder}>No segmentation yet. Place seeds and run from the right panel.</p>
          )}
        </section>
      )}

      {state.metadata && (
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>View — Single Band</h2>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <label style={{ fontSize: 11, color: '#bbb' }}>Band</label>
            <input
              type="number"
              min={1}
              max={state.metadata.bands}
              value={state.selectedBand}
              onChange={(e) => {
                const v = Math.max(1, Math.min(state.metadata!.bands, Number(e.target.value) || 1))
                setState((s) => ({ ...s, selectedBand: v }))
              }}
              style={{
                width: 56,
                background: '#2a2a2a',
                color: '#e0e0e0',
                border: '1px solid #4a4a4a',
                borderRadius: 4,
                padding: '4px 6px',
                fontSize: 12,
              }}
            />
            <span style={{ fontSize: 10, color: '#888' }}>of {state.metadata.bands}</span>
          </div>
          <RampPicker
            ramps={state.ramps}
            selectedRamp={state.selectedRamp}
            customRamp={state.customRamp}
            onChange={(rampId, customStops) => setState((s) => ({
              ...s,
              selectedRamp: rampId,
              customRamp: customStops ?? s.customRamp,
            }))}
          />
          <button
            onClick={renderBand}
            disabled={state.busyTask !== null}
            className={styles.btn}
          >
            {state.busyTask === 'render' ? (<><span className={styles.spinner} />Rendering…</>) : 'Render Band'}
          </button>
        </section>
      )}

      <div className={styles.footer}>
        <div className={styles.footerRow}>
          <span className={styles.footerLabel}>Tile cache</span>
          <span className={styles.footerValue}>
            {cacheStats ? `${cacheStats.num_tiles} • ${cacheStats.size_mb.toFixed(1)} MB` : '—'}
          </span>
        </div>
        <button onClick={clearCache} className={styles.btnGhost} disabled={!cacheStats || cacheStats.num_tiles === 0}>
          Clear cache
        </button>
      </div>
    </aside>
  )
}
