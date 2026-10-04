import { useCallback, useState } from 'react'
import { apiRequest } from '../api'
import { useAppContext } from '../AppContext'

const DEFAULT_ZONE = {
  name: 'restricted-area',
  zoneType: 'keep_out',
  minX: '-0.20',
  minY: '-0.20',
  minZ: '0.00',
  maxX: '0.20',
  maxY: '0.20',
  maxZ: '0.40',
}

export default function SafetyZoneManager() {
  const { safetyZones, setSafetyZones, setNotice } = useAppContext()
  const [formOpen, setFormOpen] = useState(false)
  const [zone, setZone] = useState(DEFAULT_ZONE)

  const refreshZones = useCallback(async () => {
    setSafetyZones(await apiRequest('/api/safety-zones'))
  }, [setSafetyZones])

  const createZone = useCallback(async () => {
    const minBounds = ['minX', 'minY', 'minZ'].map((key) => Number(zone[key]))
    const maxBounds = ['maxX', 'maxY', 'maxZ'].map((key) => Number(zone[key]))
    if (!zone.name.trim() || [...minBounds, ...maxBounds].some((value) => !Number.isFinite(value))) {
      setNotice({ type: 'error', text: 'Provide a zone name and valid numeric bounds.' })
      return
    }

    try {
      await apiRequest('/api/safety-zones', {
        method: 'POST',
        body: JSON.stringify({
          name: zone.name.trim(),
          zone_type: zone.zoneType,
          min_bounds: minBounds,
          max_bounds: maxBounds,
          color: zone.zoneType === 'keep_out' ? '#ff5c6780' : '#47d7a380',
        }),
      })
      await refreshZones()
      setFormOpen(false)
      setNotice({ type: 'success', text: `${zone.name.trim()} safety zone created.` })
    } catch (error) {
      setNotice({ type: 'error', text: error.message })
    }
  }, [refreshZones, setNotice, zone])

  const deleteZone = useCallback(async (zoneId, zoneName) => {
    try {
      await apiRequest(`/api/safety-zones/${zoneId}`, { method: 'DELETE' })
      await refreshZones()
      setNotice({ type: 'success', text: `${zoneName} safety zone removed.` })
    } catch (error) {
      setNotice({ type: 'error', text: error.message })
    }
  }, [refreshZones, setNotice])

  const updateField = (field, value) => setZone((current) => ({ ...current, [field]: value }))

  return (
    <section className="card">
      <div className="card-header">
        <div>
          <span className="eyebrow">SAFETY ENVELOPE</span>
          <h2>Workspace zones</h2>
        </div>
        <button className="text-button" onClick={() => setFormOpen((open) => !open)}>
          {formOpen ? 'Close' : 'Add zone'}
        </button>
      </div>

      {safetyZones.length > 0 && (
        <div className="object-list">
          {safetyZones.map((item) => (
            <div className="object-row safety-zone-row" key={item.id}>
              <span>
                <i className={item.zone_type} />
                <span><strong>{item.name}</strong><small>{item.zone_type.replace('_', ' ')}</small></span>
              </span>
              <button onClick={() => deleteZone(item.id, item.name)} aria-label={`Remove ${item.name}`}>×</button>
            </div>
          ))}
        </div>
      )}

      {formOpen && (
        <div className="object-form">
          <div className="form-row">
            <label className="field-grow">
              <span>Name</span>
              <input className="input" value={zone.name} onChange={(event) => updateField('name', event.target.value)} />
            </label>
            <label>
              <span>Policy</span>
              <select className="input" value={zone.zoneType} onChange={(event) => updateField('zoneType', event.target.value)}>
                <option value="keep_out">Keep out</option>
                <option value="keep_in">Keep in</option>
              </select>
            </label>
          </div>
          <div className="bounds-grid">
            {['X', 'Y', 'Z'].map((axis) => (
              <div className="bound-pair" key={axis}>
                <span>{axis} MIN / MAX</span>
                <div>
                  <input className="input" type="number" step="0.05" value={zone[`min${axis}`]} onChange={(event) => updateField(`min${axis}`, event.target.value)} />
                  <input className="input" type="number" step="0.05" value={zone[`max${axis}`]} onChange={(event) => updateField(`max${axis}`, event.target.value)} />
                </div>
              </div>
            ))}
          </div>
          <button className="btn btn-secondary btn-block" onClick={createZone}>Create safety zone</button>
        </div>
      )}

      {!formOpen && safetyZones.length === 0 && (
        <p className="empty-copy">No safety zones configured. Motion is limited only by joint constraints.</p>
      )}
    </section>
  )
}
