'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { motion } from 'framer-motion'
import { Scale, ArrowRight, Brain, FileSearch, BookOpen } from 'lucide-react'
import Link from 'next/link'
import { isAuthenticated } from '@/app/lib/api'

const features = [
  {
    icon: Brain,
    title: '多智能体协作',
    desc: '基于 LangChain 编排法官、律师等多专业 AI Agent，协同完成模拟法庭辩论',
  },
  {
    icon: FileSearch,
    title: '文档智能分析',
    desc: '自动提取合同关键条款，识别潜在法律风险，生成结构化分析报告',
  },
  {
    icon: BookOpen,
    title: '法律知识检索',
    desc: '基于 RAG 技术从海量法规、判例、辩护策略库中精准检索相关知识',
  },
]

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.2 } },
} as const

const item = {
  hidden: { opacity: 0, y: 30 },
  show: { opacity: 1, y: 0, transition: { duration: 0.6, ease: [0.25, 0.46, 0.45, 0.94] as const } },
}

export default function Home() {
  const router = useRouter()

  useEffect(() => {
    if (isAuthenticated()) {
      router.replace('/dashboard')
    }
  }, [router])

  return (
    <div className="min-h-screen bg-white relative overflow-hidden">
      {/* ════════════════════════════════════════════
          LAYER 1 — Multi-layer Gradient Mesh Background
      ════════════════════════════════════════════ */}
      <div
        className="pointer-events-none absolute inset-0"
        aria-hidden="true"
        style={{
          background:
            'linear-gradient(135deg, #f8fbff 0%, #eff6ff 15%, #f5f3ff 35%, #ecfeff 55%, #f0fdf4 70%, #eff6ff 85%, #fafbff 100%)',
          backgroundSize: '400% 400%',
          animation: 'gradientShift 20s ease infinite',
        }}
      />

      {/* ════════════════════════════════════════════
          LAYER 2 — Dot Grid Pattern Overlay
      ════════════════════════════════════════════ */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            'radial-gradient(circle, rgba(59,130,246,0.07) 1px, transparent 1px)',
          backgroundSize: '24px 24px',
        }}
        aria-hidden="true"
      />

      {/* ════════════════════════════════════════════
          LAYER 3 — Floating Blurred Gradient Orbs
      ════════════════════════════════════════════ */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
        {/* Orb 1 — Large Blue (top-right) */}
        <div
          className="absolute -top-32 -right-20 w-[550px] h-[550px] rounded-full animate-float blur-3xl opacity-60"
          style={{
            background: 'radial-gradient(circle, rgba(59,130,246,0.4) 0%, rgba(59,130,246,0.08) 50%, transparent 75%)',
          }}
        />
        {/* Orb 2 — Cyan (bottom-left) */}
        <div
          className="absolute -bottom-40 -left-24 w-[480px] h-[480px] rounded-full animate-float-slow blur-3xl opacity-50"
          style={{
            background: 'radial-gradient(circle, rgba(6,182,212,0.35) 0%, rgba(6,182,212,0.06) 50%, transparent 72%)',
            animationDelay: '2s',
          }}
        />
        {/* Orb 3 — Soft Indigo (center-right) */}
        <div
          className="absolute top-1/3 right-[10%] w-[360px] h-[360px] rounded-full animate-float-delayed blur-3xl opacity-45"
          style={{
            background: 'radial-gradient(circle, rgba(129,140,248,0.38) 0%, rgba(129,140,248,0.05) 55%, transparent 72%)',
            animationDelay: '4s',
          }}
        />
        {/* Orb 4 — Small Blue accent (top-left area) */}
        <div
          className="absolute top-[12%] left-[8%] w-[240px] h-[240px] rounded-full animate-float blur-2xl opacity-40"
          style={{
            background: 'radial-gradient(circle, rgba(96,165,250,0.35) 0%, transparent 65%)',
            animationDelay: '1s',
          }}
        />
        {/* Orb 5 — Tiny warm accent for depth (center) */}
        <div
          className="absolute top-[55%] left-[40%] w-[180px] h-[180px] rounded-full animate-orb-pulse blur-xl opacity-25"
          style={{
            background: 'radial-gradient(circle, rgba(167,139,250,0.28) 0%, transparent 60%)',
            animationDelay: '3s',
          }}
        />
      </div>

      {/* ════════════════════════════════════════════
          LAYER 4 — Geometric Decorative Elements
      ════════════════════════════════════════════ */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
        {/* Ring 1 — Large faint ring (top-right) */}
        <div
          className="absolute top-[8%] right-[-4%] w-[420px] h-[420px] rounded-full border border-blue-200/30 animate-float-slow"
          style={{ animationDelay: '5s' }}
        />
        {/* Ring 2 — Medium ring (bottom-left) */}
        <div
          className="absolute bottom-[15%] left-[-6%] w-[320px] h-[320px] rounded-full border border-cyan-200/20 animate-float-delayed"
          style={{ animationDelay: '7s' }}
        />
        {/* Ring 3 — Small solid-ish ring (hero center-right) */}
        <div
          className="absolute top-[42%] right-[6%] w-[160px] h-[160px] rounded-full border border-indigo-200/25 animate-float"
          style={{ animationDelay: '2.5s' }}
        />
        {/* Diagonal line accent */}
        <div
          className="absolute top-[22%] left-[4%] w-[120px] h-px bg-gradient-to-r from-blue-300/30 to-transparent animate-float-slow origin-left"
          style={{ animationDelay: '1.5s' }}
        />
        {/* Horizontal thin line */}
        <div
          className="absolute bottom-[30%] right-[10%] w-[80px] h-px bg-gradient-to-l from-cyan-300/25 to-transparent animate-float"
          style={{ animationDelay: '4.5s' }}
        />
        {/* Small dot cluster */}
        <div className="absolute top-[68%] left-[14%] flex gap-3">
          {[...Array(3)].map((_, i) => (
            <div
              key={i}
              className="w-1.5 h-1.5 rounded-full bg-blue-300/30 animate-float"
              style={{ animationDelay: `${i * 0.7}s` }}
            />
          ))}
        </div>
      </div>

      {/* ════════════════════════════════════════════
          FIXED HEADER
      ════════════════════════════════════════════ */}
      <header className="fixed top-0 left-0 right-0 z-50 backdrop-blur-xl bg-white/80 border-b border-ink-100">
        <div className="max-w-7xl mx-auto px-6 py-3.5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div
              className="w-9 h-9 rounded-xl flex items-center justify-center shadow-sm"
              style={{
                background: 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)',
              }}
            >
              <Scale size={18} className="text-white" />
            </div>
            <span className="text-lg font-display font-semibold text-ink-900 tracking-wide">
              LegalMind AI
            </span>
          </div>
          <Link href="/login" className="btn-sm !rounded-lg">
            登录
          </Link>
        </div>
      </header>

      {/* ════════════════════════════════════════════
          HERO SECTION
      ════════════════════════════════════════════ */}
      <section className="relative z-10 min-h-screen flex flex-col items-center justify-center px-6 pt-16">
        {/* Centered Content */}
        <div className="text-center max-w-4xl mx-auto relative z-10">
          {/* Badge Pill */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease: 'easeOut' }}
          >
            <span className="inline-flex items-center gap-2.5 px-5 py-2 rounded-full mb-10 bg-blue-50 text-blue-600 text-xs font-body tracking-wider">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500" />
              </span>
              多智能体司法协作系统
            </span>
          </motion.div>

          {/* Main Heading */}
          <motion.h1
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.15, ease: 'easeOut' }}
            className="font-display font-bold leading-[0.95] tracking-tight text-5xl md:text-7xl lg:text-8xl"
          >
            <span className="text-ink-900">LegalMind</span>{' '}
            <span
              className="bg-clip-text text-transparent"
              style={{
                backgroundImage: 'linear-gradient(135deg, #2563eb 0%, #3b82f6 40%, #06b6d4 70%, #818cf8 100%)',
                backgroundSize: '200% 200%',
                animation: 'gradientShift 6s ease infinite',
              }}
            >
              AI
            </span>
          </motion.h1>

          {/* Subtitle */}
          <motion.p
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.4, ease: 'easeOut' }}
            className="mt-8 text-lg md:text-xl text-ink-500 max-w-2xl mx-auto leading-relaxed font-body"
          >
            面向民事法律场景的自适应司法协作多智能体系统，
            <br className="hidden sm:block" />
            融合 RAG 检索、模拟法庭与智能分析能力
          </motion.p>

          {/* CTA Buttons */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.65, ease: 'easeOut' }}
            className="mt-12 flex flex-col sm:flex-row justify-center gap-4"
          >
            <Link
              href="/login"
              className="primary-btn text-base !px-8 !py-3.5"
            >
              开始使用 <ArrowRight size={18} />
            </Link>
            <Link
              href="#features"
              className="outline-btn text-base !px-8 !py-3.5"
            >
              了解更多
            </Link>
          </motion.div>
        </div>

        {/* Animated Gradient Wave at Bottom of Hero */}
        <div className="absolute bottom-0 left-0 right-0 pointer-events-none overflow-hidden" aria-hidden="true">
          <svg
            viewBox="0 0 1440 140"
            preserveAspectRatio="none"
            className="w-full h-[120px]"
            style={{ filter: 'blur(0.5px)' }}
          >
            <defs>
              <linearGradient id="waveGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="rgba(59,130,246,0.10)" />
                <stop offset="33%" stopColor="rgba(6,182,212,0.08)" />
                <stop offset="66%" stopColor="rgba(129,140,248,0.09)" />
                <stop offset="100%" stopColor="rgba(59,130,246,0.11)" />
              </linearGradient>
              <linearGradient id="waveGrad2" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="rgba(96,165,250,0.07)" />
                <stop offset="50%" stopColor="rgba(129,140,248,0.06)" />
                <stop offset="100%" stopColor="rgba(6,182,212,0.07)" />
              </linearGradient>
            </defs>
            <motion.path
              d="M0,64 C240,110 480,20 720,64 C960,108 1200,26 1440,64 L1440,140 L0,140 Z"
              fill="url(#waveGrad)"
              animate={{
                d: [
                  'M0,64 C240,110 480,20 720,64 C960,108 1200,26 1440,64 L1440,140 L0,140 Z',
                  'M0,44 C240,76 480,54 720,84 C960,114 1200,46 1440,74 L1440,140 L0,140 Z',
                  'M0,74 C240,36 480,86 720,52 C960,88 1200,58 1440,56 L1440,140 L0,140 Z',
                  'M0,64 C240,110 480,20 720,64 C960,108 1200,26 1440,64 L1440,140 L0,140 Z',
                ],
              }}
              transition={{ duration: 12, repeat: Infinity, ease: 'easeInOut' }}
            />
            <motion.path
              d="M0,90 C320,130 640,50 960,88 C1280,126 1360,78 1440,95 L1440,140 L0,140 Z"
              fill="url(#waveGrad2)"
              animate={{
                d: [
                  'M0,90 C320,130 640,50 960,88 C1280,126 1360,78 1440,95 L1440,140 L0,140 Z',
                  'M0,70 C320,104 640,78 960,106 C1280,134 1360,62 1440,82 L1440,140 L0,140 Z',
                  'M0,98 C320,62 640,112 960,74 C1280,102 1360,92 1440,102 L1440,140 L0,140 Z',
                  'M0,90 C320,130 640,50 960,88 C1280,126 1360,78 1440,95 L1440,140 L0,140 Z',
                ],
              }}
              transition={{ duration: 16, repeat: Infinity, ease: 'easeInOut', delay: 1 }}
            />
          </svg>
        </div>
      </section>

      {/* ════════════════════════════════════════════
          FEATURES SECTION
      ════════════════════════════════════════════ */}
      <section id="features" className="relative z-10 py-24 md:py-32 px-6">
        <div className="max-w-6xl mx-auto">
          {/* Section Header */}
          <div className="text-center mb-20">
            <motion.div
              initial={{ opacity: 0 }}
              whileInView={{ opacity: 1 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5 }}
              className="inline-flex items-center gap-3 mb-6"
            >
              <span className="w-8 h-px bg-blue-300/50" />
              <span className="text-xs font-body text-blue-500 tracking-[0.2em] uppercase">Core Capabilities</span>
              <span className="w-8 h-px bg-blue-300/50" />
            </motion.div>
            <motion.h2
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.6 }}
              className="font-display text-3xl md:text-4xl text-ink-900"
            >
              核心能力
            </motion.h2>
            <motion.p
              initial={{ opacity: 0 }}
              whileInView={{ opacity: 1 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5, delay: 0.2 }}
              className="mt-5 text-ink-500 text-lg font-body"
            >
              智能驱动 · 专业可靠 · 高效协作
            </motion.p>
          </div>

          {/* Feature Cards Grid */}
          <motion.div
            variants={container}
            initial="hidden"
            whileInView="show"
            viewport={{ once: true, margin: '-80px' }}
            className="grid md:grid-cols-3 gap-6"
          >
            {features.map((f) => (
              <motion.div key={f.title} variants={item} className="glass-card p-8 group">
                <div className="feature-glow" />
                <div className="w-14 h-14 rounded-xl flex items-center justify-center mb-6 relative z-10 transition-all duration-300 group-hover:scale-105 bg-blue-50/80">
                  <f.icon size={26} className="text-blue-500" />
                </div>
                <h3 className="text-xl font-display font-semibold text-ink-800 mb-3 relative z-10">
                  {f.title}
                </h3>
                <p className="text-sm text-ink-500 leading-relaxed relative z-10 font-body">
                  {f.desc}
                </p>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </section>

      {/* ════════════════════════════════════════════
          FOOTER
      ════════════════════════════════════════════ */}
      <footer className="relative z-10 py-12 border-t border-ink-100 bg-white/50">
        <div className="max-w-6xl mx-auto text-center">
          <p className="text-ink-400 text-sm font-body">
            LegalMind AI © {new Date().getFullYear()} · 智能司法协作平台 · 仅供法律研究参考
          </p>
        </div>
      </footer>
    </div>
  )
}
