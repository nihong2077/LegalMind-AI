'use client'

import { motion } from 'framer-motion'
import Link from 'next/link'
import HeroBackground from '@/components/HeroBackground'
import Navbar from '@/components/Navbar'
import FeatureCards from '@/components/FeatureCards'
import Footer from '@/components/Footer'

export default function Home() {
  return (
    <div className="min-h-screen relative overflow-x-hidden">
      <HeroBackground />
      <Navbar />

      <section className="relative z-10 min-h-[90vh] flex items-center justify-center px-6">
        <div className="text-center max-w-3xl">
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8 }}
          >
            <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full
                            border border-gold-400/20 bg-gold-400/5 mb-8">
              <span className="w-2 h-2 bg-gold-400 rounded-full animate-pulse" />
              <span className="text-xs text-gold-400">多智能体司法协作系统</span>
            </div>

            <h1 className="text-5xl md:text-7xl font-bold text-gold-200 leading-tight">
              LegalMind
              <span className="block text-gold-400">AI</span>
            </h1>

            <p className="mt-6 text-lg text-gold-200/50 max-w-xl mx-auto leading-relaxed">
              面向民事法律场景的自适应司法协作多智能体系统，
              融合 RAG 检索、智能分析与文档处理能力
            </p>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.4 }}
            className="mt-10 flex flex-col sm:flex-row justify-center gap-4"
          >
            <Link href="/chat" className="gold-btn text-base">
              开始 AI 对话
            </Link>
            <Link href="/dashboard" className="gold-btn-outline text-base">
              进入工作台
            </Link>
          </motion.div>
        </div>
      </section>

      <FeatureCards />
      <Footer />
    </div>
  )
}
