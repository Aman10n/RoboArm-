import { useCallback, useState } from 'react'
import { apiRequest } from '../api'
import { useAppContext } from '../AppContext'
import SafetyZoneManager from './SafetyZoneManager'
import TrajectoryMonitor from './TrajectoryMonitor'

const PRESET_POSES = [
  { name: 'Home', angles: [0, 0, 0, 0, 0, 0, 0] },
  { name: 'Ready', angles: [0, -0.5, 0, 1.0, 0, -0.5, 0] },
  { name: 'Reach left', angles: [1.2, -0.4, 0.3, 0.8, -0.5, -0.3, 0] },
  { name: 'Reach right', angles: [-1.2, -0.4, -0.3, 0.8, 0.5, -0.3, 0] },
  { name: 'Reach high', angles: [0, -1.2, 0, 0.3, 0, -0.2, 0] },
  { name: 'Fold', angles: [0, 0.8, 0, -1.5, 0, 0.7, 0] },
]

const formatJointName = (name, index) => {
  const match = name?.match(/(\d+)$/)
  return `Axis ${match?.[1] || index + 1}`
}

const radToDeg = (radians) => (radians * 180 / Math.PI).toFixed(1)

export default function ControlPanel() {
  const {
    connected,
    robotInfo,
    jointAngles,
    controlMode,
    telemetry,
    setControlMode,
    setJointAngle,
    moveToIK,
    resetArm,
    emergencyStop,
    setNotice,
  } = useAppContext()
  const [ikInput, setIkInput] = useState({ x: '0.40', y: '0.00', z: '0.40' })
  const [objectFormOpen, setObjectFormOpen] = useState(false)
  const [newObject, setNewObject] = useState({
    name: 'workpiece', shape: 'box', x: '0.40', y: '0.00', z: '0.05',
  })

  const numJoints = robotInfo?.num_joints || 7
  const jointNames = robotInfo?.joint_names || []
  const jointLimits = robotInfo?.joint_limits || []
  const motionDisabled = !connected || controlMode !== 'manual' || telemetry?.emergency_stopped
    || telemetry?.safety_violations?.length > 0
  const objects = telemetry?.objects || {}
  const systemStatus = telemetry?.emergency_stopped
    ? 'Motion locked'
    : telemetry?.safety_violations?.length
      ? 'Safety boundary violation'
      : connected ? 'Ready for commands' : 'Simulator offline'

  const handleIKMove = useCallback(() => {
    const position = ['x', 'y', 'z'].map((axis) => Number(ikInput[axis]))
    if (position.some((value) => !Number.isFinite(value))) {
      setNotice({ type: 'error', text: 'Enter valid X, Y, and Z coordinates.' })
      return
    }
    moveToIK(position)
  }, [ikInput, moveToIK, setNotice])

  const handleSmoothPose = useCallback(async (pose) => {
    try {
      await apiRequest('/api/trajectory/execute', {
        method: 'POST',
        body: JSON.stringify({
          target_angles: pose.angles,
          duration: 2,
          method: 'quintic',
          num_points: 120,
        }),
      })
      setNotice({ type: 'success', text: `${pose.name} trajectory started.` })
    } catch (error) {
      setNotice({ type: 'error', text: error.message })
    }
  }, [setNotice])

  const handleAddObject = useCallback(async () => {
    const position = ['x', 'y', 'z'].map((axis) => Number(newObject[axis]))
    if (!newObject.name.trim() || position.some((value) => !Number.isFinite(value))) {
      setNotice({ type: 'error', text: 'Provide an object name and valid coordinates.' })
      return
    }

    try {
      await apiRequest('/api/objects/add', {
        method: 'POST',
        body: JSON.stringify({
          name: newObject.name.trim(),
          shape: newObject.shape,
          position,
          size: [0.06, 0.06, 0.06],
          color: [0.16, 0.65, 0.88, 1],
          mass: 0.1,
        }),
      })
      setNotice({ type: 'success', text: `${newObject.name.trim()} added to the workspace.` })
      setObjectFormOpen(false)
    } catch (error) {
      setNotice({ type: 'error', text: error.message })
    }
  }, [newObject, setNotice])

  const handleRemoveObject = useCallback(async (name) => {
    try {
      await apiRequest(`/api/objects/${encodeURIComponent(name)}`, { method: 'DELETE' })
      setNotice({ type: 'success', text: `${name} removed.` })
    } catch (error) {
      setNotice({ type: 'error', text: error.message })
    }
  }, [setNotice])

  return (
    <div className="control-panel">
      <section className="card status-card">
        <div>
          <span className="eyebrow">SYSTEM STATUS</span>
          <strong>{systemStatus}</strong>
        </div>
        <span className={`status-indicator ${connected && !motionDisabled ? 'ready' : 'warning'}`} />
      </section>

      {controlMode !== 'manual' && (
        <button className="mode-return" onClick={() => setControlMode('manual')}>
          Return to manual control
        </button>
      )}

      <section className="card">
        <div className="card-header">
          <div>
            <span className="eyebrow">JOINT SPACE</span>
            <h2>Axis control</h2>
          </div>
          <span className="card-badge">{numJoints} DOF</span>
        </div>

        {Array.from({ length: numJoints }, (_, index) => {
          const angle = jointAngles[index] || 0
          const limit = jointLimits[index] || { lower: -2.96, upper: 2.96 }
          const percentage = ((angle - limit.lower) / (limit.upper - limit.lower)) * 100
          return (
            <label className="joint-slider-group" key={index}>
              <span className="joint-slider-header">
                <span className="joint-name">{formatJointName(jointNames[index], index)}</span>
                <span className="joint-value">{radToDeg(angle)}°</span>
              </span>
              <input
                type="range"
                className="joint-slider"
                min={limit.lower}
                max={limit.upper}
                step="0.01"
                value={angle}
                onChange={(event) => setJointAngle(index, Number(event.target.value))}
                disabled={motionDisabled}
                style={{ '--joint-progress': `${Math.max(0, Math.min(100, percentage))}%` }}
              />
            </label>
          )
        })}
      </section>

      <section className="card">
        <div className="card-header">
          <div>
            <span className="eyebrow">QUICK MOTION</span>
            <h2>Preset poses</h2>
          </div>
          <span className="card-note">2 s quintic</span>
        </div>
        <div className="preset-grid">
          {PRESET_POSES.map((pose, index) => (
            <button
              key={pose.name}
              className="preset-button"
              disabled={!connected || telemetry?.emergency_stopped}
              onClick={() => handleSmoothPose(pose)}
              title="Click for a smooth trajectory"
            >
              <span>{String(index + 1).padStart(2, '0')}</span>
              {pose.name}
            </button>
          ))}
        </div>
      </section>

      <TrajectoryMonitor />

      <section className="card">
        <div className="card-header">
          <div>
            <span className="eyebrow">TASK SPACE</span>
            <h2>Inverse kinematics</h2>
          </div>
          <span className="card-note">meters</span>
        </div>
        <div className="coordinate-inputs">
          {['x', 'y', 'z'].map((axis) => (
            <label key={axis}>
              <span>{axis.toUpperCase()}</span>
              <input
                type="number"
                className="input"
                step="0.05"
                value={ikInput[axis]}
                onChange={(event) => setIkInput((current) => ({
                  ...current,
                  [axis]: event.target.value,
                }))}
              />
            </label>
          ))}
        </div>
        <button className="btn btn-primary btn-block" onClick={handleIKMove} disabled={motionDisabled}>
          Solve and move
        </button>
      </section>

      <section className="card">
        <div className="card-header">
          <div>
            <span className="eyebrow">SCENE</span>
            <h2>Workspace objects</h2>
          </div>
          <button className="text-button" onClick={() => setObjectFormOpen((open) => !open)}>
            {objectFormOpen ? 'Close' : 'Add object'}
          </button>
        </div>

        {Object.keys(objects).length > 0 && (
          <div className="object-list">
            {Object.keys(objects).map((name) => (
              <div className="object-row" key={name}>
                <span><i />{name}</span>
                <button onClick={() => handleRemoveObject(name)} aria-label={`Remove ${name}`}>×</button>
              </div>
            ))}
          </div>
        )}

        {objectFormOpen && (
          <div className="object-form">
            <div className="form-row">
              <label className="field-grow">
                <span>Name</span>
                <input
                  className="input"
                  value={newObject.name}
                  onChange={(event) => setNewObject((current) => ({ ...current, name: event.target.value }))}
                />
              </label>
              <label>
                <span>Shape</span>
                <select
                  className="input"
                  value={newObject.shape}
                  onChange={(event) => setNewObject((current) => ({ ...current, shape: event.target.value }))}
                >
                  <option value="box">Box</option>
                  <option value="sphere">Sphere</option>
                  <option value="cylinder">Cylinder</option>
                </select>
              </label>
            </div>
            <div className="coordinate-inputs compact">
              {['x', 'y', 'z'].map((axis) => (
                <label key={axis}>
                  <span>{axis.toUpperCase()}</span>
                  <input
                    type="number"
                    className="input"
                    step="0.05"
                    value={newObject[axis]}
                    onChange={(event) => setNewObject((current) => ({
                      ...current,
                      [axis]: event.target.value,
                    }))}
                  />
                </label>
              ))}
            </div>
            <button className="btn btn-secondary btn-block" onClick={handleAddObject}>Add to scene</button>
          </div>
        )}

        {!objectFormOpen && Object.keys(objects).length === 0 && (
          <p className="empty-copy">No workspace objects in the current scene.</p>
        )}
      </section>

      <SafetyZoneManager />

      <section className="safety-actions">
        <button className="btn btn-secondary" onClick={resetArm} disabled={!connected}>Reset system</button>
        <button className="btn btn-danger" onClick={emergencyStop} disabled={!connected}>Emergency stop</button>
      </section>
    </div>
  )
}
