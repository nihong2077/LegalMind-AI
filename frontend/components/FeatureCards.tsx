'use client'

import { motion } from 'framer-motion'
import { Scale, Brain, FileSearch, Users, ArrowRight } from 'lucide-react'
import Link from 'next/link'

const features = [
  {
    icon: Brain,
    title: '多智能体协作',
    desc: '基于 LangChain 编排多个专业法律 AI Agent，协同完成复杂法律分析任务',
  },
  {
    icon: FileSearch,
    title: '文档智能分析',
    desc: '自动提取合同关键条款，识别潜在法律风险，生成结构化分析报告',
  },
  {
    icon: Scale,
    title: '案例检索匹配',
    desc: '基于 RAG 技术从海量判例库中精准检索相似案例，提供裁判参考',
  },
  {
    icon: Users,
    title: '司法协作平台',
    desc: '支持多角色协同工作，律师、法官、当事人共享案件信息与进展',
  },
]

const container = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.15 },
  },
}

const item = {
  hidden: { opacity: 0, y: 20 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5 } },
}

export default function FeatureCards() {
  return (
    <section className="relative z-10 py-32 px-6 max-w-6xl mx-auto">
      <div className="text-center mb-20">
        <motion.h2
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="text-4xl md:text-5xl font-bold text-gold-200"
        >
          核心能力
        </motion.h2>
        <motion.p
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true }}
          transition={{ delay: 0.2 }}
          className="mt-6 text-gold-200/50 text-lg"
        >
          智能驱动 · 专业可靠 · 高效协作
        </motion.p>
      </div>

      <motion.div
        variants={container}
        initial="hidden"
        whileInView="show"
        viewport={{ once: true }}
        className="grid md:grid-cols-2 lg:grid-cols-4 gap-6"
      >
        {features.map((f) => (
          <motion.div key={f.title} variants={item} className="glass-card p-8 group">
            <div className="feature-glow" />
            <div className="w-12 h-12 rounded-xl bg-gold-400/10 flex items-center justify-center mb-5
                            group-hover:bg-gold-400/20 transition-colors duration-300">
              <f.icon size={24} className="text-gold-400" />
            </div>
            <h3 className="text-lg font-semibold text-gold-200 mb-3 relative z-10">{f.title}</h3>
            <p className="text-sm text-gold-200/50 leading-relaxed relative z-10">{f.desc}</p>
          </motion.div>
        ))}
      </motion.div>

      <motion.div
        initial={{ opacity: 0 }}
        whileInView={{ opacity: 1 }}
        viewport={{ once: true }}
        className="text-center mt-16"
      >
        <Link href="/chat" className="gold-btn inline-flex items-center gap-2">
          开始体验 <ArrowRight size={16} />
        </Link>
      </motion.div>
    </section>
  )
}
