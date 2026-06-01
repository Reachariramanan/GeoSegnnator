import { useState } from 'react'
import { CUSTOM_RAMP_KEY, RampDef, RampStop } from '../App'
import RampEditor from './RampEditor'

interface Props {
  ramps: Record<string, RampDef>
  selectedRamp: string
  customRamp: RampStop[] | null
  onChange: (rampId: string, customStops: RampStop[] | null) => void
  label?: string
}

export function gradientCss(stops: RampStop[]): string {
  if (!stops || stops.length === 0) return 'linear-gradient(to right, #555, #555)'
  const sorted = [...stops].sort((a, b) => a.pos - b.pos)
  const parts = sorted.map((s) => {
    const pct = Math.round(Math.max(0, Math.min(1, s.pos)) * 100)
    const a = Math.max(0, Math.min(1, s.alpha))
    const hex = s.color.replace('#', '')
    const r = parseInt(hex.slice(0, 2), 16)
    const g = parseInt(hex.slice(2, 4), 16)
    const b = parseInt(hex.slice(4, 6), 16)
    return `rgba(${r},${g},${b},${a}) ${pct}%`
  })
  return `linear-gradient(to right, ${parts.join(', ')})`
}

export default function RampPicker({ ramps, selectedRamp, customRamp, onChange, label = 'Color ramp' }: Props) {
  const [showEditor, setShowEditor] = useState(false)
  const ids = Object.keys(ramps)
  const stops =
    selectedRamp === CUSTOM_RAMP_KEY && customRamp
      ? customRamp
      : ramps[selectedRamp]?.stops ?? []

  const handleSelect = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const value = e.target.value
    if (value === CUSTOM_RAMP_KEY) {
      setShowEditor(true)
      return
    }
    onChange(value, null)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 10 }}>
      <label style={{ fontSize: 11, color: '#9a9a9a', textTransform: 'uppercase', letterSpacing: 0.6 }}>
        {label}
      </label>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <select
          value={selectedRamp}
          onChange={handleSelect}
          style={{
            flex: 1,
            background: '#2a2a2a',
            color: '#e0e0e0',
            border: '1px solid #4a4a4a',
            borderRadius: 4,
            padding: '6px 8px',
            fontSize: 12,
            fontFamily: 'inherit',
          }}
        >
          {ids.map((id) => (
            <option key={id} value={id}>
              {ramps[id].name}
            </option>
          ))}
          <option value={CUSTOM_RAMP_KEY}>{customRamp ? 'Custom (edit…)' : 'Custom…'}</option>
        </select>
        {selectedRamp === CUSTOM_RAMP_KEY && (
          <button
            type="button"
            onClick={() => setShowEditor(true)}
            style={{
              background: '#3a3a3a',
              color: '#e0e0e0',
              border: '1px solid #4a4a4a',
              borderRadius: 4,
              padding: '6px 10px',
              fontSize: 11,
              cursor: 'pointer',
            }}
          >
            Edit
          </button>
        )}
      </div>
      <div
        title="Ramp preview"
        style={{
          height: 14,
          borderRadius: 3,
          border: '1px solid #4a4a4a',
          backgroundImage: gradientCss(stops),
          backgroundColor: '#222',
        }}
      />
      {showEditor && (
        <RampEditor
          initialStops={customRamp ?? stops}
          onCancel={() => setShowEditor(false)}
          onApply={(newStops) => {
            onChange(CUSTOM_RAMP_KEY, newStops)
            setShowEditor(false)
          }}
        />
      )}
    </div>
  )
}
