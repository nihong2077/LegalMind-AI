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
}

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
    <div className="min-h-screen bg-navy-950 relative overflow-hidden">
      {/* ── Decorative background orbs ── */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
        {/* Large top-right orb */}
        <div
          className="absolute -top-32 -right-32 w-[600px] h-[600px] rounded-full animate-aura-pulse"
          style={{
            background: 'radial-gradient(circle, rgba(212,160,23,0.08) 0%, rgba(30,68,128,0.12) 40%, transparent 70%)',
          }}
        />
        {/* Medium bottom-left orb */}
        <div
          className="absolute -bottom-40 -left-40 w-[500px] h-[500px] rounded-full animate-aura-pulse"
          style={{
            background: 'radial-gradient(circle, rgba(37,88,160,0.1) 0%, rgba(212,160,23,0.06) 45%, transparent 70%)',
            animationDelay: '3s',
          }}
        />
        {/* Small center-left orb */}
        <div
          className="absolute top-1/2 -left-20 w-[300px] h-[300px] rounded-full animate-float"
          style={{
            background: 'radial-gradient(circle, rgba(212,160,23,0.06) 0%, transparent 60%)',
          }}
        />
        {/* Subtle top-left glow */}
        <div
          className="absolute top-0 left-0 w-[400px] h-[400px] rounded-full"
          style={{
            background: 'radial-gradient(circle, rgba(59,125,216,0.06) 0%, transparent 60%)',
          }}
        />
      </div>

      {/* ── Fixed Header ── */}
      <header className="fixed top-0 left-0 right-0 z-50 backdrop-blur-xl bg-navy-950/70 border-b border-gold-500/10">
        <div className="max-w-7xl mx-auto px-6 py-3.5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg flex items-center justify-center"
              style={{ background: 'linear-gradient(135deg, #d4a017 0%, #b8860b 100%)' }}
            >
              <Scale size={18} className="text-navy-900" />
            </div>
            <span className="text-lg font-display font-semibold text-gold-300 tracking-wide">
              LegalMind AI
            </span>
          </div>
          <Link href="/login" className="gold-btn text-sm !px-5 !py-2">
            登录
          </Link>
        </div>
      </header>

      {/* ── Hero Section ── */}
      <section className="relative z-10 min-h-screen flex items-center justify-center px-6 pt-16">
        <div className="text-center max-w-4xl mx-auto">
          {/* Badge */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease: 'easeOut' }}
          >
            <div className="inline-flex items-center gap-2.5 px-5 py-2 rounded-full mb-10"
              style={{
                background: 'rgba(212,160,23,0.06)',
                border: '1px solid rgba(212,160,23,0.15)',
              }}
            >
              <span className="w-2 h-2 bg-gold-400 rounded-full animate-glow-pulse" />
              <span className="text-xs font-body text-gold-300 tracking-wider">多智能体司法协作系统</span>
            </div>
          </motion.div>

          {/* Main Heading */}
          <motion.h1
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.15, ease: 'easeOut' }}
            className="font-display text-6xl md:text-8xl lg:text-9xl font-bold leading-[0.95] tracking-tight"
          >
            <span
              className="bg-clip-text text-transparent"
              style={{
                backgroundImage: 'linear-gradient(135deg, #f0d578 0%, #d4a017 30%, #e6be44 50%, #b8860b 70%, #f0d578 100%)',
                backgroundSize: '200% 200%',
                animation: 'shimmer 4s ease-in-out infinite',
              }}
            >
              LegalMind
            </span>
            <br />
            <span
              className="bg-clip-text text-transparent"
              style={{
                backgroundImage: 'linear-gradient(135deg, #e6be44 0%, #f0d578 40%, #d4a017 70%, #e6be44 100%)',
                backgroundSize: '200% 200%',
                animation: 'shimmer 4s ease-in-out infinite',
                animationDelay: '0.5s',
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
            className="mt-8 text-lg md:text-xl text-navy-300 max-w-2xl mx-auto leading-relaxed font-body"
          >
            面向民事法律场景的自适应司法协作多智能体系统，
            <br className="hidden sm:block" />
            融合 RAG 检索、模拟法庭与智能分析能力
          </motion.p>

          {/* CTA */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.65, ease: 'easeOut' }}
            className="mt-12 flex flex-col sm:flex-row justify-center gap-4"
          >
            <Link
              href="/login"
              className="gold-btn text-base inline-flex items-center justify-center gap-2.5 !px-8 !py-3.5"
            >
              登录使用 <ArrowRight size={18} />
            </Link>
            <Link
              href="#features"
              className="gold-btn-outline text-base inline-flex items-center justify-center gap-2 !px-8 !py-3.5"
            >
              了解更多
            </Link>
          </motion.div>
        </div>
      </section>

      {/* ── Features Section ── */}
      <section id="features" className="relative z-10 py-32 px-6">
        <div className="max-w-6xl mx-auto">
          {/* Section header */}
          <div className="text-center mb-20">
            <motion.div
              initial={{ opacity: 0 }}
              whileInView={{ opacity: 1 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5 }}
              className="inline-flex items-center gap-3 mb-6"
            >
              <span className="w-8 h-px bg-gold-500/40" />
              <span className="text-xs font-body text-gold-400 tracking-[0.2em] uppercase">Core Capabilities</span>
              <span className="w-8 h-px bg-gold-500/40" />
            </motion.div>
            <motion.h2
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.6 }}
              className="font-display text-4xl md:text-5xl font-bold text-slate-50"
            >
              核心能力
            </motion.h2>
            <motion.p
              initial={{ opacity: 0 }}
              whileInView={{ opacity: 1 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5, delay: 0.2 }}
              className="mt-5 text-navy-300 text-lg font-body"
            >
              智能驱动 · 专业可靠 · 高效协作
            </motion.p>
          </div>

          {/* Feature cards */}
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
                <div
                  className="w-14 h-14 rounded-xl flex items-center justify-center mb-6 relative z-10 transition-all duration-300"
                  style={{
                    background: 'rgba(212,160,23,0.08)',
                    border: '1px solid rgba(212,160,23,0.12)',
                  }}
                >
                  <f.icon size={26} className="text-gold-400" />
                </div>
                <h3 className="text-xl font-display font-semibold text-slate-50 mb-3 relative z-10">
                  {f.title}
                </h3>
                <p className="text-sm text-navy-300 leading-relaxed relative z-10 font-body">
                  {f.desc}
                </p>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="relative z-10 py-12">
        <div className="divider max-w-6xl mx-auto mb-10" />
        <div className="text-center">
          <p className="text-xs text-navy-400 font-body">
            LegalMind AI © {new Date().getFullYear()} · 智能司法协作平台 · 仅供法律研究参考
          </p>
        </div>
      </footer>
    </div>
  )
}
