'use client'

import { motion } from 'framer-motion'
import Link from 'next/link'
import HeroBackground from '@/components/HeroBackground'
import Navbar from '@/components/Navbar'
import Footer from '@/components/Footer'
import { ArrowRight, Law, MessageSquare, Gavel, BookOpen, User } from 'lucide-react'

export default function Home() {
  return (
    <div className="min-h-screen relative overflow-x-hidden">
      <HeroBackground />
      <Navbar />

      <section className="relative z-10 min-h-[90vh] flex items-center justify-center px-6">
        <div className="text-center max-w-4xl">
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
            className="mt-16 grid md:grid-cols-2 lg:grid-cols-3 gap-6 max-w-5xl mx-auto"
          >
            {/* 复杂案情分析 */}
            <Link href="/complex-analysis" className="group">
              <div className="glass-card p-8 rounded-xl border border-gold-400/10 hover:border-gold-400/30 transition-all h-full text-left">
                <div className="w-16 h-16 bg-gradient-to-br from-gold-400/20 to-gold-400/5 rounded-xl flex items-center justify-center mb-6 group-hover:scale-110 transition-transform">
                  <Law className="w-8 h-8 text-gold-400" />
                </div>
                <h3 className="text-2xl font-bold text-gold-100 mb-3">
                  复杂案情分析
                </h3>
                <p className="text-gold-200/60 mb-6">
                  深度分析案件事实，识别法律关系，归纳争议焦点，提供专业法律分析报告
                </p>
                <div className="flex items-center text-gold-400 font-medium">
                  开始分析 <ArrowRight className="w-5 h-5 ml-2 group-hover:translate-x-1 transition-transform" />
                </div>
              </div>
            </Link>
            
            {/* 简单回答 */}
            <Link href="/simple-qa" className="group">
              <div className="glass-card p-8 rounded-xl border border-gold-400/10 hover:border-gold-400/30 transition-all h-full text-left">
                <div className="w-16 h-16 bg-gradient-to-br from-gold-400/20 to-gold-400/5 rounded-xl flex items-center justify-center mb-6 group-hover:scale-110 transition-transform">
                  <MessageSquare className="w-8 h-8 text-gold-400" />
                </div>
                <h3 className="text-2xl font-bold text-gold-100 mb-3">
                  简单回答
                </h3>
                <p className="text-gold-200/60 mb-6">
                  快速回答简单法律问题，提供即时法律建议和参考
                </p>
                <div className="flex items-center text-gold-400 font-medium">
                  开始咨询 <ArrowRight className="w-5 h-5 ml-2 group-hover:translate-x-1 transition-transform" />
                </div>
              </div>
            </Link>
            
            {/* 法庭模拟 */}
            <Link href="/courtroom-simulation" className="group">
              <div className="glass-card p-8 rounded-xl border border-gold-400/10 hover:border-gold-400/30 transition-all h-full text-left">
                <div className="w-16 h-16 bg-gradient-to-br from-gold-400/20 to-gold-400/5 rounded-xl flex items-center justify-center mb-6 group-hover:scale-110 transition-transform">
                  <Gavel className="w-8 h-8 text-gold-400" />
                </div>
                <h3 className="text-2xl font-bold text-gold-100 mb-3">
                  法庭模拟
                </h3>
                <p className="text-gold-200/60 mb-6">
                  模拟法庭辩论过程，原告和被告律师轮流辩论，最后由法官总结
                </p>
                <div className="flex items-center text-gold-400 font-medium">
                  开始模拟 <ArrowRight className="w-5 h-5 ml-2 group-hover:translate-x-1 transition-transform" />
                </div>
              </div>
            </Link>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.6 }}
            className="mt-10 flex flex-col sm:flex-row justify-center gap-4"
          >
            <Link href="/chat" className="gold-btn text-base flex items-center gap-2">
              <User className="w-4 h-4" /> 开始 AI 对话
            </Link>
            <Link href="/dashboard" className="gold-btn-outline text-base flex items-center gap-2">
              <BookOpen className="w-4 h-4" /> 进入工作台
            </Link>
          </motion.div>
        </div>
      </section>

      <Footer />
    </div>
  )
}
