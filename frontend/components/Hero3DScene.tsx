'use client'

import { useRef, useMemo } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { Float, Icosahedron, Torus, MeshDistortMaterial, Sphere } from '@react-three/drei'
import * as THREE from 'three'

// 主体：扭曲的法律天平抽象模型（多层几何体组合）
function LegalScale3D({ scrollProgress }: { scrollProgress: () => number }) {
  const groupRef = useRef<THREE.Group>(null)
  const innerRef = useRef<THREE.Mesh>(null)
  const ringRef = useRef<THREE.Mesh>(null)

  useFrame((state) => {
    if (!groupRef.current) return
    const scroll = scrollProgress()
    // 根据滚动旋转
    groupRef.current.rotation.y = scroll * Math.PI * 2 + state.clock.elapsedTime * 0.1
    groupRef.current.rotation.x = scroll * Math.PI * 0.5
    // 内部球体自转
    if (innerRef.current) {
      innerRef.current.rotation.x = state.clock.elapsedTime * 0.3
      innerRef.current.rotation.z = state.clock.elapsedTime * 0.2
    }
    // 环旋转
    if (ringRef.current) {
      ringRef.current.rotation.x = state.clock.elapsedTime * 0.4
      ringRef.current.rotation.y = state.clock.elapsedTime * 0.3
    }
  })

  return (
    <group ref={groupRef}>
      {/* 中心扭曲球体 - 代表法律核心 */}
      <Sphere ref={innerRef} args={[1.2, 64, 64]}>
        <MeshDistortMaterial
          color="#3b82f6"
          attach="material"
          distort={0.4}
          speed={2}
          roughness={0.2}
          metalness={0.8}
        />
      </Sphere>

      {/* 外层线框二十面体 - 代表法律框架 */}
      <Icosahedron args={[2.2, 1]}>
        <meshBasicMaterial color="#60a5fa" wireframe transparent opacity={0.3} />
      </Icosahedron>

      {/* 旋转环 - 代表司法公正 */}
      <Torus ref={ringRef} args={[3, 0.05, 16, 100]}>
        <meshStandardMaterial
          color="#1e40af"
          emissive="#3b82f6"
          emissiveIntensity={0.5}
          metalness={0.9}
          roughness={0.1}
        />
      </Torus>

      {/* 第二个环 */}
      <Torus args={[3.5, 0.03, 16, 100]} rotation={[Math.PI / 3, 0, 0]}>
        <meshStandardMaterial
          color="#93c5fd"
          emissive="#60a5fa"
          emissiveIntensity={0.3}
          metalness={0.9}
          roughness={0.1}
        />
      </Torus>

      {/* 粒子点 */}
      <Particles />
    </group>
  )
}

// 粒子系统
function Particles() {
  const ref = useRef<THREE.Points>(null)

  const positions = useMemo(() => {
    const count = 800
    const arr = new Float32Array(count * 3)
    for (let i = 0; i < count; i++) {
      const r = 4 + Math.random() * 3
      const theta = Math.random() * Math.PI * 2
      const phi = Math.acos(2 * Math.random() - 1)
      arr[i * 3] = r * Math.sin(phi) * Math.cos(theta)
      arr[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta)
      arr[i * 3 + 2] = r * Math.cos(phi)
    }
    return arr
  }, [])

  useFrame((state) => {
    if (ref.current) {
      ref.current.rotation.y = state.clock.elapsedTime * 0.05
    }
  })

  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          count={positions.length / 3}
          array={positions}
          itemSize={3}
        />
      </bufferGeometry>
      <pointsMaterial
        size={0.04}
        color="#60a5fa"
        transparent
        opacity={0.6}
        sizeAttenuation
      />
    </points>
  )
}

// 光照
function Lights() {
  return (
    <>
      <ambientLight intensity={0.3} />
      <pointLight position={[10, 10, 10]} intensity={1} color="#3b82f6" />
      <pointLight position={[-10, -10, -10]} intensity={0.5} color="#93c5fd" />
      <spotLight position={[0, 5, 5]} intensity={0.8} angle={0.3} penumbra={1} color="#ffffff" />
    </>
  )
}

export default function Hero3DScene({ scrollProgress }: { scrollProgress: () => number }) {
  return (
    <Canvas
      camera={{ position: [0, 0, 8], fov: 50 }}
      style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%' }}
      gl={{ antialias: true, alpha: true }}
    >
      <Lights />
      <Float speed={1.5} rotationIntensity={0.3} floatIntensity={0.5}>
        <LegalScale3D scrollProgress={scrollProgress} />
      </Float>
    </Canvas>
  )
}
