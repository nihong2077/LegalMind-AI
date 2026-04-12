'use client'

import { useEffect, useState } from 'react'

export default function HeroBackground() {
  const [stars, setStars] = useState<Array<{ id: number; top: number; left: number; size: number; opacity: number }>>([])
  const [mousePos, setMousePos] = useState({ x: 50, y: 50 })

  useEffect(() => {
    const generated = Array.from({ length: 100 }).map((_, i) => ({
      id: i,
      top: Math.random() * 100,
      left: Math.random() * 100,
      size: Math.random() * 2.5 + 0.5,
      opacity: Math.random() * 0.5 + 0.2,
    }))
    setStars(generated)
  }, [])

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      const x = (e.clientX / window.innerWidth) * 100
      const y = (e.clientY / window.innerHeight) * 100
      setMousePos({ x, y })
    }
    window.addEventListener('mousemove', handleMouseMove)
    return () => window.removeEventListener('mousemove', handleMouseMove)
  }, [])

  return (
    <div className="fixed inset-0 -z-10 overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_25%,#0d1326_0%,#05070f_60%,#000000_100%)]" />

      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <div
          className="gold-aura animate-aura-pulse"
          style={{
            background: `radial-gradient(
              circle at ${mousePos.x}% ${mousePos.y}%,
              rgba(198,168,92,0.45),
              rgba(198,168,92,0.2) 30%,
              rgba(198,168,92,0.08) 55%,
              transparent 70%
            )`,
          }}
        />
      </div>

      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <div className="orbit-ring" />
      </div>

      {stars.map((star) => (
        <div
          key={star.id}
          className="absolute bg-white rounded-full animate-twinkle"
          style={{
            top: `${star.top}%`,
            left: `${star.left}%`,
            width: star.size,
            height: star.size,
            opacity: star.opacity,
          }}
        />
      ))}
    </div>
  )
}
