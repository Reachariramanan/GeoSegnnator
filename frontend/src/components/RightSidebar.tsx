import { Dispatch, SetStateAction, useState } from 'react'
import axios from 'axios'
import { AppState, CUSTOM_RAMP_KEY, RangeMode, TrainScore } from '../App'
import RampPicker from './RampPicker'
import styles from './Sidebar.module.css'

interface Props {
  state: AppState
  setState: Dispatch<SetStateAction<AppState>>
}

const API_BASE = '/api'

type SortKey = 'name' | 'iou' | 'f1' | 'suggested_threshold'

export default function RightSidebar({ state, setState }: Props) {
  const [trainResult, setTrainResult] = useState<any>(null)
  const [sortKey, setSortKey] = useState<SortKey>('iou')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const supportedIndices = state.indices.filter(
    (i) => i.status === 'supported' || i.status === 'supported_approx'
  )

  const runSegmentation = async () => {
    if (!state.metadata) {
      setState((s) => ({ ...s, error: 'Load a raster first' }))
      return
    }
    if (state.seeds.length === 0) {
      setState((s) => ({ ...s, error: 'Place at least one seed first' }))
      return
    }
    setState((s) => ({ ...s, busyTask: 'segment', error: null }))
    const url = state.useProgressive ? '/segment/progressive' : '/segment/index'
    const body = {
      index_name: state.selectedIndex,
      threshold: state.threshold,
      seeds: state.seeds.map((s) => ({ row: s.row, col: s.col, kind: s.kind })),
      max_size: 2048,
      ...(state.useProgressive ? { max_iterations: 10, roi_dimming: 0.3 } : {}),
    }
    try {
      const res = await axios.post(`${API_BASE}${url}`, body, { responseType: 'blob' })
      const blobUrl = URL.createObjectURL(res.data)
      setState((s) => {
        // Revoke the previous blob URL to free memory
        if (s.maskUrl) URL.revokeObjectURL(s.maskUrl)
        return { ...s, maskUrl: blobUrl, busyTask: null }
      })
    } catch (err: any) {
      let detail = 'Segmentation failed'
      // axios with responseType:'blob' returns errors as a Blob — extract the JSON
      if (err.response?.data instanceof Blob) {
        try {
          const text = await err.response.data.text()
          detail = JSON.parse(text).detail || text
        } catch { /* keep default */ }
      } else if (err.response?.data?.detail) {
        detail = err.response.data.detail
      }
      setState((s) => ({ ...s, busyTask: null, error: detail }))
    }
  }

  const runTraining = async () => {
    if (!state.metadata || state.seeds.length === 0) {
      setState((s) => ({ ...s, error: 'Load a raster and place seeds first' }))
      return
    }
    setState((s) => ({ ...s, busyTask: 'train', error: null }))
    try {
      const res = await axios.post(`${API_BASE}/train/formula`, {
        index_names: supportedIndices.map((i) => i.name),
        threshold: state.threshold,
        seeds: state.seeds.map((s) => ({ row: s.row, col: s.col, kind: s.kind })),
      })
      setTrainResult(res.data)
      const ranking: TrainScore[] = Array.isArray(res.data.per_index_scores)
        ? res.data.per_index_scores
        : []
      setState((s) => ({ ...s, busyTask: null, trainRanking: ranking.length > 0 ? ranking : null }))
    } catch (err: any) {
      setState((s) => ({
        ...s,
        busyTask: null,
        error: err.response?.data?.detail || 'Training failed',
      }))
    }
  }

  const renderIndex = async () => {
    if (!state.metadata) return
    setState((s) => ({ ...s, busyTask: 'render', error: null }))
    try {
      const body: any = {
        index_name: state.selectedIndex,
        ramp: state.selectedRamp === CUSTOM_RAMP_KEY ? null : state.selectedRamp,
        range_mode: state.rangeMode,
      }
      if (state.selectedRamp === CUSTOM_RAMP_KEY && state.customRamp) {
        body.custom_ramp = { stops: state.customRamp }
      }
      const res = await axios.post(`${API_BASE}/render/index`, body, { responseType: 'blob' })
      const url = URL.createObjectURL(res.data)
      setState((s) => {
        if (s.indexPreviewUrl) URL.revokeObjectURL(s.indexPreviewUrl)
        return { ...s, indexPreviewUrl: url, viewMode: 'index', busyTask: null }
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

  const applyRanking = (row: TrainScore) => {
    setState((s) => ({
      ...s,
      selectedIndex: row.name,
      threshold: row.suggested_threshold != null && isFinite(row.suggested_threshold)
        ? Math.max(-1, Math.min(1, row.suggested_threshold))
        : s.threshold,
    }))
  }

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir(key === 'name' ? 'asc' : 'desc')
    }
  }

  const sortedRanking: TrainScore[] = (() => {
    if (!state.trainRanking) return []
    const copy = [...state.trainRanking]
    copy.sort((a, b) => {
      const av = a[sortKey]
      const bv = b[sortKey]
      const aNum = typeof av === 'number' ? av : (av == null ? -Infinity : NaN)
      const bNum = typeof bv === 'number' ? bv : (bv == null ? -Infinity : NaN)
      if (sortKey === 'name') {
        return sortDir === 'asc'
          ? String(av).localeCompare(String(bv))
          : String(bv).localeCompare(String(av))
      }
      if (isNaN(aNum) && isNaN(bNum)) return 0
      if (isNaN(aNum)) return 1
      if (isNaN(bNum)) return -1
      return sortDir === 'asc' ? aNum - bNum : bNum - aNum
    })
    return copy
  })()

  const toggleSeedMode = () => {
    setState((s) => ({ ...s, segmentationEnabled: !s.segmentationEnabled }))
  }

  const removeSeed = (idx: number) => {
    setState((s) => ({ ...s, seeds: s.seeds.filter((_, i) => i !== idx) }))
  }

  const clearSeeds = () => setState((s) => ({ ...s, seeds: [] }))

  if (!state.metadata) {
    return (
      <aside className={styles.sidebar}>
        <div className={styles.header}>
          <h2 className={styles.headerTitle}>Analysis</h2>
          <p className={styles.subtitle}>Load a raster to begin</p>
        </div>
        <div className={styles.emptyState}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" className={styles.emptyIcon}>
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
          </svg>
          <p className={styles.emptyText}>No raster loaded</p>
          <p className={styles.emptySubtext}>Drop a GeoTIFF in the left panel to enable analysis</p>
        </div>
      </aside>
    )
  }

  return (
    <aside className={styles.sidebar}>
      <div className={styles.header}>
        <h2 className={styles.headerTitle}>Analysis</h2>
        <p className={styles.subtitle}>Spectral index segmentation</p>
      </div>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Index & Threshold</h2>

        <label className={styles.fieldLabel}>Spectral Index</label>
        <select
          className={styles.select}
          value={state.selectedIndex}
          onChange={(e) => setState((s) => ({ ...s, selectedIndex: e.target.value }))}
        >
          {supportedIndices.map((i) => (
            <option key={i.name} value={i.name}>
              {i.display_name} {i.status === 'supported_approx' ? '~' : ''}
            </option>
          ))}
        </select>

        <label className={styles.fieldLabel}>Threshold ({state.threshold.toFixed(2)})</label>
        <input
          type="range" min="0" max="1" step="0.01"
          value={state.threshold}
          onChange={(e) => setState((s) => ({ ...s, threshold: Number(e.target.value) }))}
          className={styles.rangeFull}
        />

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

        <label className={styles.fieldLabel}>Range mode</label>
        <select
          className={styles.select}
          value={state.rangeMode}
          onChange={(e) => setState((s) => ({ ...s, rangeMode: e.target.value as RangeMode }))}
        >
          <option value="auto">Auto (per-index default)</option>
          <option value="percentile">Percentile (2–98)</option>
          <option value="fixed">Fixed (use index default range)</option>
        </select>

        <button
          onClick={renderIndex}
          disabled={state.busyTask !== null}
          className={styles.btn}
          style={{ marginTop: 8 }}
        >
          {state.busyTask === 'render' ? (<><span className={styles.spinner} />Rendering…</>) : 'Apply Index Visualization'}
        </button>

        <label className={styles.checkbox} style={{ marginTop: 12 }}>
          <input
            type="checkbox"
            checked={state.useProgressive}
            onChange={(e) => setState((s) => ({ ...s, useProgressive: e.target.checked }))}
          />
          <span>Progressive (iterative refinement)</span>
        </label>

        <button
          onClick={runSegmentation}
          disabled={state.busyTask !== null || state.seeds.length === 0}
          className={styles.btnPrimary}
        >
          {state.busyTask === 'segment' ? (<><span className={styles.spinner} />Running...</>) : 'Run Segmentation'}
        </button>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionTitleRow}>
          <h2 className={styles.sectionTitle}>Seeds ({state.seeds.length})</h2>
          {state.seeds.length > 0 && (
            <button className={styles.linkBtn} onClick={clearSeeds}>Clear all</button>
          )}
        </div>

        <label className={styles.checkbox}>
          <input type="checkbox" checked={state.segmentationEnabled} onChange={toggleSeedMode} />
          <span>Place seeds on click</span>
        </label>

        {state.segmentationEnabled && (
          <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
            <button
              onClick={() => setState((s) => ({ ...s, seedKind: 'pos' }))}
              style={{
                flex: 1,
                padding: '8px 12px',
                background: state.seedKind === 'pos' ? '#22c55e' : '#2a2a2a',
                color: state.seedKind === 'pos' ? '#000' : '#e0e0e0',
                border: '1px solid #3a3a3a',
                borderRadius: 4,
                cursor: 'pointer',
                fontSize: 12,
                fontWeight: 600,
              }}
            >
              + Road
            </button>
            <button
              onClick={() => setState((s) => ({ ...s, seedKind: 'neg' }))}
              style={{
                flex: 1,
                padding: '8px 12px',
                background: state.seedKind === 'neg' ? '#ef4444' : '#2a2a2a',
                color: state.seedKind === 'neg' ? '#fff' : '#e0e0e0',
                border: '1px solid #3a3a3a',
                borderRadius: 4,
                cursor: 'pointer',
                fontSize: 12,
                fontWeight: 600,
              }}
            >
              − Non-Road
            </button>
          </div>
        )}

        {state.seeds.length === 0 ? (
          <p className={styles.placeholder}>
            {state.segmentationEnabled
              ? 'Click the map to place a seed point.'
              : 'Enable seed-placement above, then click the map.'}
          </p>
        ) : (
          <ul className={styles.seedList}>
            {state.seeds.map((s, i) => (
              <li key={i} className={styles.seedItem}>
                <span
                  className={styles.seedBadge}
                  style={{
                    background: s.kind === 'pos' ? '#22c55e' : '#ef4444',
                    color: s.kind === 'pos' ? '#000' : '#fff',
                  }}
                >
                  {i + 1}
                </span>
                <span className={styles.seedCoords}>
                  {s.kind === 'pos' ? '✓' : '✗'} r{s.row}, c{s.col}
                </span>
                <span className={styles.seedLatLng}>
                  {s.lat.toFixed(4)}°, {s.lng.toFixed(4)}°
                </span>
                <button className={styles.removeBtn} onClick={() => removeSeed(i)}>×</button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Best Filter Search</h2>
        <p className={styles.help}>
          Scores every supported index against your seed-derived training mask. Click a row to apply it.
        </p>
        <button
          onClick={runTraining}
          disabled={state.busyTask !== null || state.seeds.length === 0}
          className={styles.btn}
        >
          {state.busyTask === 'train' ? (<><span className={styles.spinner} />Searching…</>) : 'Search All Filters'}
        </button>

        {trainResult?.warning && (
          <p className={styles.warning} style={{ marginTop: 10 }}>{trainResult.warning}</p>
        )}

        {sortedRanking.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <div style={{ display: 'flex', gap: 10, fontSize: 10, color: '#9a9a9a', marginBottom: 4 }}>
              <span>Combined IoU: {trainResult?.combined_iou?.toFixed(3)}</span>
              <span>CV F1: {trainResult?.mean_cv_f1?.toFixed(3)}</span>
            </div>
            <div style={{ maxHeight: 280, overflowY: 'auto', border: '1px solid #3a3a3a', borderRadius: 4 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                <thead>
                  <tr style={{ background: '#333', color: '#9a9a9a', position: 'sticky', top: 0 }}>
                    <th
                      onClick={() => toggleSort('name')}
                      style={{ textAlign: 'left', padding: '6px 8px', cursor: 'pointer', userSelect: 'none' }}
                    >Index {sortKey === 'name' ? (sortDir === 'asc' ? '↑' : '↓') : ''}</th>
                    <th
                      onClick={() => toggleSort('iou')}
                      style={{ textAlign: 'right', padding: '6px 8px', cursor: 'pointer', userSelect: 'none' }}
                    >IoU {sortKey === 'iou' ? (sortDir === 'asc' ? '↑' : '↓') : ''}</th>
                    <th
                      onClick={() => toggleSort('f1')}
                      style={{ textAlign: 'right', padding: '6px 8px', cursor: 'pointer', userSelect: 'none' }}
                    >F1 {sortKey === 'f1' ? (sortDir === 'asc' ? '↑' : '↓') : ''}</th>
                    <th
                      onClick={() => toggleSort('suggested_threshold')}
                      style={{ textAlign: 'right', padding: '6px 8px', cursor: 'pointer', userSelect: 'none' }}
                    >Thr {sortKey === 'suggested_threshold' ? (sortDir === 'asc' ? '↑' : '↓') : ''}</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedRanking.map((row) => {
                    const isSelected = row.name === state.selectedIndex
                    return (
                      <tr
                        key={row.name}
                        onClick={() => applyRanking(row)}
                        title="Click to apply this index + suggested threshold"
                        style={{
                          background: isSelected ? '#3d3a2a' : 'transparent',
                          color: row.error ? '#c88' : '#e0e0e0',
                          cursor: 'pointer',
                          borderTop: '1px solid #333',
                        }}
                      >
                        <td style={{ padding: '5px 8px', fontWeight: isSelected ? 700 : 400 }}>
                          {row.name.toUpperCase()}
                        </td>
                        <td style={{ padding: '5px 8px', textAlign: 'right', fontFamily: 'monospace' }}>
                          {row.iou.toFixed(3)}
                        </td>
                        <td style={{ padding: '5px 8px', textAlign: 'right', fontFamily: 'monospace' }}>
                          {row.f1.toFixed(3)}
                        </td>
                        <td style={{ padding: '5px 8px', textAlign: 'right', fontFamily: 'monospace', color: '#999' }}>
                          {row.suggested_threshold != null && isFinite(row.suggested_threshold)
                            ? row.suggested_threshold.toFixed(3)
                            : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Metadata</h2>
        <div className={styles.metaGrid}>
          <div className={styles.metaItem}>
            <span className={styles.metaLabel}>CRS</span>
            <span className={styles.metaValue} title={state.metadata.crs}>
              {state.metadata.crs.split('/').pop()?.replace(/"/g, '').trim() || state.metadata.crs.slice(0, 18)}
            </span>
          </div>
          <div className={styles.metaItem}>
            <span className={styles.metaLabel}>Bands</span>
            <span className={styles.metaValue}>{state.metadata.bands}</span>
          </div>
          <div className={styles.metaItem}>
            <span className={styles.metaLabel}>Size</span>
            <span className={styles.metaValue}>{state.metadata.width}×{state.metadata.height}</span>
          </div>
          <div className={styles.metaItem}>
            <span className={styles.metaLabel}>Type</span>
            <span className={styles.metaValue}>{state.metadata.dtype}</span>
          </div>
        </div>
      </section>
    </aside>
  )
}
