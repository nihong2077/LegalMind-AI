'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { motion } from 'framer-motion'
import { Scale, ArrowRight, Brain, FileSearch, BookOpen, AlertTriangle } from 'lucide-react'
import Link from 'next/link'
import { isAuthenticated } from '@/app/lib/api'
import dynamic from 'next/dynamic'

// 动态加载3D场景（避免SSR）
const Hero3DScene = dynamic(() => import('@/components/Hero3DScene'), { ssr: false })

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
  show: { opacity: 1, transition: { staggerChildren: 0.15 } },
}

const item = {
  hidden: { opacity: 0, y: 20 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5 } },
}

export default function Home() {
  const router = useRouter()
  const scrollProgressRef = useRef(0)
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    if (isAuthenticated()) {
      router.replace('/dashboard')
    }
    setMounted(true)
    // 监听滚动，更新进度
    const handleScroll = () => {
      const scrollTop = window.scrollY
      const docHeight = document.documentElement.scrollHeight - window.innerHeight
      scrollProgressRef.current = docHeight > 0 ? scrollTop / docHeight : 0
    }
    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [router])

  return (
    <div className="min-h-screen bg-slate-900">
      {/* 顶部导航 */}
      <header className="fixed top-0 left-0 right-0 z-50 bg-slate-900/80 backdrop-blur-xl border-b border-white/10">
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-blue-600 flex items-center justify-center">
              <Scale size={18} className="text-white" />
            </div>
            <span className="text-lg font-bold text-white">LegalMind AI</span>
          </div>
          <Link href="/login" className="gold-btn text-sm !px-4 !py-2">
            登录
          </Link>
        </div>
      </header>

      {/* Hero 区域 - 带3D背景 */}
      <section className="relative z-10 min-h-[100vh] flex items-center justify-center px-6 overflow-hidden bg-gradient-to-br from-slate-900 via-blue-950 to-slate-900">
        {/* 3D 场景背景 */}
        {mounted && (
          <div className="absolute inset-0 z-0 opacity-70">
            <Hero3DScene scrollProgress={() => scrollProgressRef.current} />
          </div>
        )}
        {/* 渐变遮罩，让文字更清晰 */}
        <div className="absolute inset-0 z-[1] bg-gradient-to-b from-transparent via-transparent to-slate-900/60 pointer-events-none" />

        <div className="text-center max-w-3xl relative z-10">
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8 }}
          >
            <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full
                            border border-blue-400/30 bg-blue-500/10 backdrop-blur-md mb-8">
              <span className="w-2 h-2 bg-blue-400 rounded-full animate-pulse" />
              <span className="text-xs text-blue-300">多智能体司法协作系统</span>
            </div>

            <h1 className="text-5xl md:text-7xl font-bold text-white leading-tight drop-shadow-2xl">
              LegalMind
              <span className="block bg-gradient-to-r from-blue-400 to-cyan-300 bg-clip-text text-transparent">AI</span>
            </h1>

            <p className="mt-6 text-lg text-slate-300 max-w-xl mx-auto leading-relaxed">
              面向民事法律场景的自适应司法协作多智能体系统，
              融合 RAG 检索、模拟法庭与智能分析能力
            </p>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.4 }}
            className="mt-10 flex flex-col sm:flex-row justify-center gap-4"
          >
            <Link href="/login" className="gold-btn text-base inline-flex items-center gap-2">
              登录使用 <ArrowRight size={16} />
            </Link>
          </motion.div>

          {/* 滚动提示 */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 1.5 }}
            className="absolute -bottom-20 left-1/2 -translate-x-1/2 text-blue-300/60 text-xs flex flex-col items-center gap-2"
          >
            <span>向下滚动探索</span>
            <div className="w-px h-8 bg-gradient-to-b from-blue-400/60 to-transparent" />
          </motion.div>
        </div>
      </section>

      {/* 核心能力 */}
      <section className="relative z-10 py-32 px-6 max-w-6xl mx-auto">
        <div className="text-center mb-20">
          <motion.h2
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="text-4xl md:text-5xl font-bold text-white"
          >
            核心能力
          </motion.h2>
          <motion.p
            initial={{ opacity: 0 }}
            whileInView={{ opacity: 1 }}
            viewport={{ once: true }}
            transition={{ delay: 0.2 }}
            className="mt-6 text-slate-400 text-lg"
          >
            智能驱动 · 专业可靠 · 高效协作
          </motion.p>
        </div>

        <motion.div
          variants={container}
          initial="hidden"
          whileInView="show"
          viewport={{ once: true }}
          className="grid md:grid-cols-3 gap-6"
        >
          {features.map((f) => (
            <motion.div key={f.title} variants={item} className="glass-card p-8 group bg-white/5 border border-white/10 backdrop-blur-md rounded-2xl">
              <div className="feature-glow" />
              <div className="w-12 h-12 rounded-xl bg-blue-500/20 flex items-center justify-center mb-5
                              group-hover:bg-blue-500/30 transition-colors duration-300">
                <f.icon size={24} className="text-blue-400" />
              </div>
              <h3 className="text-lg font-semibold text-white mb-3 relative z-10">{f.title}</h3>
              <p className="text-sm text-slate-400 leading-relaxed relative z-10">{f.desc}</p>
            </motion.div>
          ))}
        </motion.div>
      </section>

      {/* 底部 */}
      <footer className="relative z-10 py-10 text-center border-t border-white/10 bg-slate-950">
        <div className="max-w-2xl mx-auto px-4">
          <div className="flex items-start justify-center gap-2 mb-3">
            <AlertTriangle size={14} className="text-amber-500 mt-0.5 flex-shrink-0" />
            <p className="text-[11px] text-amber-500/80 leading-relaxed text-left">
              <strong>免责声明：</strong>本平台由人工智能技术提供，回答可能存在错误或偏差，仅供参考，<strong>不构成任何司法建议或法律意见</strong>。法律问题具有高度专业性，如遇实际法律纠纷，请务必咨询执业律师或相关法律专业人士。
            </p>
          </div>
          <p className="text-xs text-slate-500">
            LegalMind AI © {new Date().getFullYear()} · 智能司法协作平台 · 仅供法律研究参考
          </p>
        </div>
      </footer>
    </div>
  )
}
