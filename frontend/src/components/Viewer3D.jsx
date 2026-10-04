import { Html, OrbitControls } from '@react-three/drei'
import { Canvas, useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import { useAppContext } from '../AppContext'

const LINK_COLORS = ['#33435c', '#2676a5', '#344966', '#2676a5', '#344966', '#2676a5', '#344966', '#f05d5e']
const LINK_RADII = [0.068, 0.062, 0.058, 0.052, 0.047, 0.042, 0.036, 0.032]

// The simulator uses Z-up coordinates; Three.js uses Y-up coordinates.
const toScenePosition = ([x = 0, y = 0, z = 0]) => [x, z, -y]

function Link({ start, end, radius, color }) {
  const transform = useMemo(() => {
    const from = new THREE.Vector3(...start)
    const to = new THREE.Vector3(...end)
    const direction = new THREE.Vector3().subVectors(to, from)
    const height = Math.max(direction.length(), 0.001)
    const quaternion = new THREE.Quaternion()
    quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction.normalize())
    return {
      position: new THREE.Vector3().addVectors(from, to).multiplyScalar(0.5),
      quaternion,
      height,
    }
  }, [end, start])

  return (
    <mesh position={transform.position} quaternion={transform.quaternion} castShadow receiveShadow>
      <cylinderGeometry args={[radius * 0.88, radius, transform.height, 24]} />
      <meshStandardMaterial color={color} metalness={0.72} roughness={0.28} />
    </mesh>
  )
}

function Joint({ position, radius, isTool }) {
  const ring = useRef()
  useFrame(({ clock }) => {
    if (isTool && ring.current) ring.current.rotation.z = clock.elapsedTime * 0.8
  })

  return (
    <group position={position}>
      <mesh castShadow>
        <sphereGeometry args={[radius * 1.08, 24, 24]} />
        <meshStandardMaterial
          color={isTool ? '#ff6b6b' : '#42c7f5'}
          emissive={isTool ? '#ff3030' : '#00789c'}
          emissiveIntensity={isTool ? 0.35 : 0.22}
          metalness={0.78}
          roughness={0.2}
        />
      </mesh>
      <mesh ref={ring} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[radius * 1.38, 0.004, 10, 36]} />
        <meshBasicMaterial color={isTool ? '#ff8b8b' : '#73dcff'} transparent opacity={0.65} />
      </mesh>
      {isTool && [-1, 1].map((side) => (
        <mesh key={side} position={[side * 0.022, -0.038, 0]} castShadow>
          <boxGeometry args={[0.009, 0.05, 0.018]} />
          <meshStandardMaterial color="#d9e2ef" metalness={0.9} roughness={0.16} />
        </mesh>
      ))}
    </group>
  )
}

function RobotArm() {
  const { linkStates, safetyZones, ikTarget } = useAppContext()
  const jointPositions = useMemo(() => {
    if (linkStates?.length > 1) {
      return linkStates.map((link) => toScenePosition(link.position))
    }
    return [0, 0.1575, 0.36, 0.5645, 0.78, 0.9645, 1.18, 1.261]
      .map((height) => [0, height, 0])
  }, [linkStates])

  return (
    <group>
      <mesh position={[0, 0.018, 0]} receiveShadow castShadow>
        <cylinderGeometry args={[0.105, 0.125, 0.036, 32]} />
        <meshStandardMaterial color="#182235" metalness={0.82} roughness={0.28} />
      </mesh>

      {jointPositions.slice(0, -1).map((position, index) => (
        <Link
          key={`link-${index}`}
          start={position}
          end={jointPositions[index + 1]}
          radius={LINK_RADII[index] || 0.035}
          color={LINK_COLORS[index] || '#2676a5'}
        />
      ))}
      {jointPositions.map((position, index) => (
        <Joint
          key={`joint-${index}`}
          position={position}
          radius={LINK_RADII[index] || 0.032}
          isTool={index === jointPositions.length - 1}
        />
      ))}

      {safetyZones.map((zone) => {
        const minimum = toScenePosition([zone.min_x, zone.min_y, zone.min_z])
        const maximum = toScenePosition([zone.max_x, zone.max_y, zone.max_z])
        const size = maximum.map((value, index) => Math.abs(value - minimum[index]))
        const center = maximum.map((value, index) => (value + minimum[index]) / 2)
        const color = zone.zone_type === 'keep_out' ? '#ff5c67' : '#47d7a3'
        return (
          <group key={zone.id}>
            <mesh position={center}>
              <boxGeometry args={size} />
              <meshBasicMaterial color={color} transparent opacity={0.07} side={THREE.DoubleSide} />
            </mesh>
            <mesh position={center}>
              <boxGeometry args={size} />
              <meshBasicMaterial color={color} wireframe transparent opacity={0.35} />
            </mesh>
          </group>
        )
      })}

      {ikTarget && (
        <group position={toScenePosition(ikTarget)}>
          <mesh>
            <sphereGeometry args={[0.018, 18, 18]} />
            <meshStandardMaterial color="#ffbd4a" emissive="#ff9200" emissiveIntensity={0.8} />
          </mesh>
          {[0, Math.PI / 2].map((rotation) => (
            <mesh key={rotation} rotation={[rotation, 0, 0]}>
              <torusGeometry args={[0.044, 0.002, 8, 36]} />
              <meshBasicMaterial color="#ffbd4a" transparent opacity={0.7} />
            </mesh>
          ))}
        </group>
      )}
    </group>
  )
}

function WorkspaceObjects() {
  const { telemetry } = useAppContext()
  const objects = telemetry?.objects || {}

  return Object.entries(objects).map(([name, object]) => {
    const color = object.color
      ? new THREE.Color(object.color[0], object.color[1], object.color[2])
      : new THREE.Color('#3aaed8')
    const size = object.size || [0.05, 0.05, 0.05]
    const sceneSize = [size[0], size[2], size[1]]

    return (
      <mesh key={name} position={toScenePosition(object.position)} castShadow receiveShadow>
        {object.shape === 'sphere' ? (
          <sphereGeometry args={[size[0] / 2, 24, 24]} />
        ) : object.shape === 'cylinder' ? (
          <cylinderGeometry args={[size[0] / 2, size[0] / 2, size[2], 24]} />
        ) : (
          <boxGeometry args={sceneSize} />
        )}
        <meshStandardMaterial color={color} metalness={0.35} roughness={0.42} />
      </mesh>
    )
  })
}

function Scene() {
  const { connected } = useAppContext()
  return (
    <>
      <color attach="background" args={['#07101d']} />
      <fog attach="fog" args={['#07101d', 2.7, 7]} />
      <ambientLight intensity={0.42} />
      <hemisphereLight args={['#9bdcff', '#08101d', 0.65]} />
      <directionalLight
        position={[3.5, 5, 3]}
        intensity={2.1}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-2}
        shadow-camera-right={2}
        shadow-camera-top={2}
        shadow-camera-bottom={-2}
      />
      <pointLight position={[-2, 2, -2]} intensity={4} distance={5} color="#4e79ff" />

      <mesh receiveShadow rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[12, 12]} />
        <meshStandardMaterial color="#091523" metalness={0.55} roughness={0.72} />
      </mesh>
      <gridHelper args={[8, 80, '#28415c', '#16283b']} position={[0, 0.002, 0]} />
      <RobotArm />
      <WorkspaceObjects />

      <OrbitControls
        makeDefault
        enableDamping
        dampingFactor={0.08}
        minPolarAngle={0.12}
        maxPolarAngle={Math.PI / 2 - 0.03}
        minDistance={0.55}
        maxDistance={4.5}
        target={[0, 0.58, 0]}
      />

      {!connected && (
        <Html center position={[0, 0.58, 0]}>
          <div className="viewer-offline">
            <span />
            Connecting to simulator
          </div>
        </Html>
      )}
    </>
  )
}

export default function Viewer3D() {
  return (
    <Canvas
      shadows
      dpr={[1, 2]}
      camera={{ position: [1.55, 1.18, 1.55], fov: 48, near: 0.01, far: 100 }}
      gl={{ antialias: true, alpha: false, powerPreference: 'high-performance' }}
    >
      <Scene />
    </Canvas>
  )
}
