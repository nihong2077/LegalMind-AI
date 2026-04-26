'use client'

import { motion } from 'framer-motion'
import Link from 'next/link'
import HeroBackground from '@/components/HeroBackground'
import Navbar from '@/components/Navbar'
import Footer from '@/components/Footer'
import { ArrowRight, Gavel, MessageSquare, BookOpen, User, Brain, FileText, Database } from 'lucide-react'

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

            <h1 className="text-5xl md:text-7xl font-bold leading-tight mb-6">
              <span className="text-gold-200">LegalMind</span>
              <span className="block bg-gradient-to-r from-gold-400 to-gold-300 bg-clip-text text-transparent">AI</span>
            </h1>

            <p className="mt-6 text-lg text-gold-200/60 max-w-xl mx-auto leading-relaxed mb-12">
              面向民事法律场景的自适应司法协作多智能体系统，
              融合 RAG 检索、智能分析与文档处理能力，为您提供专业的法律分析与建议
            </p>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.4 }}
            className="mt-16 grid md:grid-cols-2 lg:grid-cols-3 gap-8 max-w-5xl mx-auto"
          >
            {/* 复杂案情分析 */}
            <Link href="/complex-analysis" className="group">
              <div className="feature-card p-8 h-full text-left">
                <div className="feature-card-icon group-hover:scale-110 transition-transform duration-300">
                  <Brain className="w-7 h-7" />
                </div>
                <h3 className="feature-card-title mb-3">
                  复杂案情分析
                </h3>
                <p className="feature-card-description mb-6">
                  深度分析案件事实，识别法律关系，归纳争议焦点，提供专业法律分析报告
                </p>
                <div className="flex items-center text-gold-400 font-medium group-hover:translate-x-1 transition-transform duration-300">
                  开始分析 <ArrowRight className="w-5 h-5 ml-2" />
                </div>
              </div>
            </Link>

            {/* 法庭模拟 */}
            <Link href="/courtroom-simulation" className="group">
              <div className="feature-card p-8 h-full text-left">
                <div className="feature-card-icon group-hover:scale-110 transition-transform duration-300">
                  <Gavel className="w-7 h-7" />
                </div>
                <h3 className="feature-card-title mb-3">
                  法庭模拟
                </h3>
                <p className="feature-card-description mb-6">
                  原告和被告律师来回辩论，每轮结束后由法官决定是否继续，最后由法官总结
                </p>
                <div className="flex items-center text-gold-400 font-medium group-hover:translate-x-1 transition-transform duration-300">
                  开始模拟 <ArrowRight className="w-5 h-5 ml-2" />
                </div>
              </div>
            </Link>

            {/* AI 对话 */}
            <Link href="/chat" className="group">
              <div className="feature-card p-8 h-full text-left">
                <div className="feature-card-icon group-hover:scale-110 transition-transform duration-300">
                  <MessageSquare className="w-7 h-7" />
                </div>
                <h3 className="feature-card-title mb-3">
                  AI 对话
                </h3>
                <p className="feature-card-description mb-6">
                  直接与AI对话，获取法律问题的即时回答和专业建议
                </p>
                <div className="flex items-center text-gold-400 font-medium group-hover:translate-x-1 transition-transform duration-300">
                  开始对话 <ArrowRight className="w-5 h-5 ml-2" />
                </div>
              </div>
            </Link>

            {/* 文档分析 */}
            <Link href="/document-analysis" className="group">
              <div className="feature-card p-8 h-full text-left">
                <div className="feature-card-icon group-hover:scale-110 transition-transform duration-300">
                  <FileText className="w-7 h-7" />
                </div>
                <h3 className="feature-card-title mb-3">
                  文档分析
                </h3>
                <p className="feature-card-description mb-6">
                  上传法律文档，获取专业的文档分析和解读
                </p>
                <div className="flex items-center text-gold-400 font-medium group-hover:translate-x-1 transition-transform duration-300">
                  上传文档 <ArrowRight className="w-5 h-5 ml-2" />
                </div>
              </div>
            </Link>

            {/* 法律知识库 */}
            <Link href="/knowledge-base" className="group">
              <div className="feature-card p-8 h-full text-left">
                <div className="feature-card-icon group-hover:scale-110 transition-transform duration-300">
                  <Database className="w-7 h-7" />
                </div>
                <h3 className="feature-card-title mb-3">
                  法律知识库
                </h3>
                <p className="feature-card-description mb-6">
                  访问和管理您的法律知识库，方便上传和查询法律资料
                </p>
                <div className="flex items-center text-gold-400 font-medium group-hover:translate-x-1 transition-transform duration-300">
                  查看知识库 <ArrowRight className="w-5 h-5 ml-2" />
                </div>
              </div>
            </Link>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.6 }}
            className="mt-16 flex flex-col sm:flex-row justify-center gap-6"
          >
            <Link href="/chat" className="gold-btn text-base flex items-center gap-2 px-8 py-4">
              <User className="w-4 h-4" /> 开始 AI 对话
            </Link>
            <Link href="/dashboard" className="gold-btn-outline text-base flex items-center gap-2 px-8 py-4">
              <BookOpen className="w-4 h-4" /> 进入工作台
            </Link>
          </motion.div>
        </div>
      </section>

      <Footer />
    </div>
  )
}
