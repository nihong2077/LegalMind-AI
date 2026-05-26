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
  show: { opacity: 1, transition: { staggerChildren: 0.15 } },
}

const item = {
  hidden: { opacity: 0, y: 20 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5 } },
}

export default function Home() {
  const router = useRouter()

  useEffect(() => {
    if (isAuthenticated()) {
      router.replace('/dashboard')
    }
  }, [router])

  return (
    <div className="min-h-screen bg-white">
      {/* 顶部导航 */}
      <header className="fixed top-0 left-0 right-0 z-50 bg-white/90 backdrop-blur-xl border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-blue-600 flex items-center justify-center">
              <Scale size={18} className="text-white" />
            </div>
            <span className="text-lg font-bold text-slate-800">LegalMind AI</span>
          </div>
          <Link href="/login" className="gold-btn text-sm !px-4 !py-2">
            登录
          </Link>
        </div>
      </header>

      {/* Hero 区域 */}
      <section className="relative z-10 min-h-[90vh] flex items-center justify-center px-6 bg-gradient-to-br from-blue-50 via-white to-slate-50">
        <div className="text-center max-w-3xl">
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8 }}
          >
            <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full
                            border border-blue-200 bg-blue-50 mb-8">
              <span className="w-2 h-2 bg-blue-600 rounded-full animate-pulse" />
              <span className="text-xs text-blue-600">多智能体司法协作系统</span>
            </div>

            <h1 className="text-5xl md:text-7xl font-bold text-slate-800 leading-tight">
              LegalMind
              <span className="block text-blue-600">AI</span>
            </h1>

            <p className="mt-6 text-lg text-slate-500 max-w-xl mx-auto leading-relaxed">
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
        </div>
      </section>

      {/* 核心能力 */}
      <section className="relative z-10 py-32 px-6 max-w-6xl mx-auto">
        <div className="text-center mb-20">
          <motion.h2
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="text-4xl md:text-5xl font-bold text-slate-800"
          >
            核心能力
          </motion.h2>
          <motion.p
            initial={{ opacity: 0 }}
            whileInView={{ opacity: 1 }}
            viewport={{ once: true }}
            transition={{ delay: 0.2 }}
            className="mt-6 text-slate-500 text-lg"
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
            <motion.div key={f.title} variants={item} className="glass-card p-8 group">
              <div className="feature-glow" />
              <div className="w-12 h-12 rounded-xl bg-blue-50 flex items-center justify-center mb-5
                              group-hover:bg-blue-100 transition-colors duration-300">
                <f.icon size={24} className="text-blue-600" />
              </div>
              <h3 className="text-lg font-semibold text-slate-800 mb-3 relative z-10">{f.title}</h3>
              <p className="text-sm text-slate-500 leading-relaxed relative z-10">{f.desc}</p>
            </motion.div>
          ))}
        </motion.div>
      </section>

      {/* 底部 */}
      <footer className="relative z-10 py-12 text-center border-t border-gray-200 bg-slate-50">
        <p className="text-xs text-slate-400">
          LegalMind AI © {new Date().getFullYear()} · 智能司法协作平台 · 仅供法律研究参考
        </p>
      </footer>
    </div>
  )
}
