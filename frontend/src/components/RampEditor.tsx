import { useState } from 'react'
import { RampStop } from '../App'
import { gradientCss } from './RampPicker'

interface Props {
  initialStops: RampStop[]
  onApply: (stops: RampStop[]) => void
  onCancel: () => void
}

function cloneStops(stops: RampStop[]): RampStop[] {
  return stops.map((s) => ({ ...s }))
}

const DEFAULT_NEW_STOP: RampStop = { pos: 0.5, color: '#888888', alpha: 1.0 }

export default function RampEditor({ initialStops, onApply, onCancel }: Props) {
  const [stops, setStops] = useState<RampStop[]>(() =>
    initialStops && initialStops.length > 0 ? cloneStops(initialStops) : [
      { pos: 0, color: '#000000', alpha: 1.0 },
      { pos: 1, color: '#ffffff', alpha: 1.0 },
    ]
  )

  const updateStop = (idx: number, patch: Partial<RampStop>) => {
    setStops((s) => s.map((stop, i) => (i === idx ? { ...stop, ...patch } : stop)))
  }
  const removeStop = (idx: number) => {
    setStops((s) => s.filter((_, i) => i !== idx))
  }
  const addStop = () => {
    setStops((s) => [...s, { ...DEFAULT_NEW_STOP }])
  }

  const sortedForPreview = [...stops].sort((a, b) => a.pos - b.pos)

  return (
    <div
      onClick={onCancel}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.6)',
        zIndex: 3000,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: '#2f2f2f',
          border: '1px solid #4a4a4a',
          borderRadius: 8,
          padding: 18,
          width: 460,
          maxHeight: '80vh',
          overflowY: 'auto',
          color: '#e8e8e8',
          fontSize: 12,
          boxShadow: '0 12px 40px rgba(0,0,0,0.6)',
        }}
      >
        <h3 style={{ fontSize: 14, marginBottom: 12, fontWeight: 700 }}>Custom color ramp</h3>

        <div
          style={{
            height: 26,
            borderRadius: 4,
            border: '1px solid #4a4a4a',
            marginBottom: 14,
            backgroundImage: gradientCss(sortedForPreview),
            backgroundColor: '#222',
          }}
        />

        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ color: '#9a9a9a', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.6 }}>
              <th style={{ textAlign: 'left', padding: '4px 6px' }}>Pos</th>
              <th style={{ textAlign: 'left', padding: '4px 6px' }}>Color</th>
              <th style={{ textAlign: 'left', padding: '4px 6px' }}>Alpha</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {stops.map((s, i) => (
              <tr key={i} style={{ borderTop: '1px solid #3a3a3a' }}>
                <td style={{ padding: '6px 6px', width: 120 }}>
                  <input
                    type="range" min={0} max={1} step={0.01}
                    value={s.pos}
                    onChange={(e) => updateStop(i, { pos: Number(e.target.value) })}
                    style={{ width: '100%' }}
                  />
                  <div style={{ fontSize: 10, color: '#9a9a9a', textAlign: 'center' }}>
                    {s.pos.toFixed(2)}
                  </div>
                </td>
                <td style={{ padding: '6px 6px', width: 110 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <input
                      type="color"
                      value={s.color}
                      onChange={(e) => updateStop(i, { color: e.target.value })}
                      style={{ width: 28, height: 22, border: 'none', background: 'transparent', cursor: 'pointer' }}
                    />
                    <input
                      type="text"
                      value={s.color}
                      onChange={(e) => updateStop(i, { color: e.target.value })}
                      style={{
                        flex: 1, minWidth: 0, fontSize: 11, fontFamily: 'monospace',
                        padding: '3px 5px', background: '#222', color: '#e0e0e0',
                        border: '1px solid #4a4a4a', borderRadius: 3,
                      }}
                    />
                  </div>
                </td>
                <td style={{ padding: '6px 6px', width: 110 }}>
                  <input
                    type="range" min={0} max={1} step={0.05}
                    value={s.alpha}
                    onChange={(e) => updateStop(i, { alpha: Number(e.target.value) })}
                    style={{ width: '100%' }}
                  />
                  <div style={{ fontSize: 10, color: '#9a9a9a', textAlign: 'center' }}>
                    {s.alpha.toFixed(2)}
                  </div>
                </td>
                <td style={{ padding: '6px 6px', textAlign: 'right' }}>
                  <button
                    type="button"
                    onClick={() => removeStop(i)}
                    disabled={stops.length <= 2}
                    title="Remove stop"
                    style={{
                      background: 'transparent',
                      color: stops.length <= 2 ? '#555' : '#d88',
                      border: 'none',
                      fontSize: 16,
                      cursor: stops.length <= 2 ? 'not-allowed' : 'pointer',
                    }}
                  >
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <button
          type="button"
          onClick={addStop}
          style={{
            marginTop: 10,
            background: '#3a3a3a',
            border: '1px dashed #5a5a5a',
            color: '#bbb',
            padding: '6px 12px',
            borderRadius: 4,
            cursor: 'pointer',
            fontSize: 11,
          }}
        >
          + Add stop
        </button>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
          <button
            type="button"
            onClick={onCancel}
            style={{
              background: 'transparent',
              border: '1px solid #4a4a4a',
              color: '#bbb',
              padding: '6px 14px',
              borderRadius: 4,
              cursor: 'pointer',
              fontSize: 12,
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => {
              const sorted = [...stops].sort((a, b) => a.pos - b.pos)
              onApply(sorted)
            }}
            style={{
              background: '#e0e0e0',
              border: 'none',
              color: '#2a2a2a',
              padding: '6px 14px',
              borderRadius: 4,
              cursor: 'pointer',
              fontSize: 12,
              fontWeight: 700,
            }}
          >
            Apply
          </button>
        </div>
      </div>
    </div>
  )
}
