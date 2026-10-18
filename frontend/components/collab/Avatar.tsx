'use client'

/**
 * 通用头像（T1.8）：传入 http(s) 地址则渲染图片，否则以名称首字取色块。
 */
interface AvatarProps {
  name?: string | null
  avatar?: string | null
  seed?: string
  size?: number
  className?: string
}

const PALETTE = [
  'bg-blue-500',
  'bg-emerald-500',
  'bg-amber-500',
  'bg-violet-500',
  'bg-rose-500',
  'bg-cyan-500',
  'bg-indigo-500',
  'bg-teal-500',
]

function colorFor(seed: string): string {
  let hash = 0
  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash * 31 + seed.charCodeAt(i)) % 100000
  }
  return PALETTE[hash % PALETTE.length]
}

export default function Avatar({ name, avatar, seed, size = 32, className = '' }: AvatarProps) {
  const label = (name || '?').trim()
  const isUrl = !!avatar && /^(https?:\/\/|\/)/.test(avatar)
  const dim = { width: size, height: size }

  if (isUrl) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={avatar as string}
        alt={label}
        style={dim}
        className={`rounded-full object-cover flex-shrink-0 ${className}`}
      />
    )
  }

  return (
    <div
      style={dim}
      className={`rounded-full flex items-center justify-center text-white font-medium flex-shrink-0 ${colorFor(
        seed || label,
      )} ${className}`}
    >
      <span style={{ fontSize: Math.round(size * 0.42) }}>{label.slice(0, 1)}</span>
    </div>
  )
}
