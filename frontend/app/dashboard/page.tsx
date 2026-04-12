'use client'

import Sidebar from '@/components/Sidebar'
import { MessageSquare, FileText, BookOpen, TrendingUp } from 'lucide-react'
import Link from 'next/link'
import { motion } from 'framer-motion'

const stats = [
  { label: 'AI 对话次数', value: '128', icon: MessageSquare, color: 'text-gold-400' },
  { label: '已分析文档', value: '36', icon: FileText, color: 'text-blue-400' },
  { label: '法律知识条目', value: '2,450', icon: BookOpen, color: 'text-emerald-400' },
  { label: '案件处理效率', value: '+45%', icon: TrendingUp, color: 'text-purple-400' },
]

const quickActions = [
  { title: 'AI 法律对话', desc: '向 AI 助手咨询法律问题', href: '/chat', icon: MessageSquare },
  { title: '文档智能分析', desc: '上传合同、诉状等法律文书', href: '/documents', icon: FileText },
  { title: '法律知识检索', desc: '搜索法律法规与判例', href: '/knowledge', icon: BookOpen },
]

const recentCases = [
  { id: '1', title: '劳动合同纠纷 - 张某诉某科技公司', status: '分析中', time: '2 小时前' },
  { id: '2', title: '房屋买卖合同违约 - 李某诉王某', status: '已完成', time: '昨天' },
  { id: '3', title: '交通事故损害赔偿 - 赵某诉某保险公司', status: '待处理', time: '3 天前' },
]

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.1 } },
}

const item = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0 },
}

export default function DashboardPage() {
  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex-1 overflow-y-auto p-8">
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
          <h2 className="text-2xl font-bold text-gold-200 mb-1">工作台</h2>
          <p className="text-sm text-gold-200/40 mb-8">欢迎回来，以下是您的工作概览</p>
        </motion.div>

        <motion.div
          variants={container}
          initial="hidden"
          animate="show"
          className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8"
        >
          {stats.map((s) => (
            <motion.div key={s.label} variants={item} className="glass-card-static p-5">
              <div className="flex items-center justify-between mb-3">
                <s.icon size={18} className={s.color} />
                <span className="text-2xl font-bold text-gold-200">{s.value}</span>
              </div>
              <p className="text-xs text-gold-200/40">{s.label}</p>
            </motion.div>
          ))}
        </motion.div>

        <div className="grid lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-4">
            <h3 className="text-lg font-semibold text-gold-200">快速操作</h3>
            <motion.div
              variants={container}
              initial="hidden"
              animate="show"
              className="grid sm:grid-cols-3 gap-4"
            >
              {quickActions.map((a) => (
                <motion.div key={a.title} variants={item}>
                  <Link
                    href={a.href}
                    className="glass-card p-6 block group"
                  >
                    <div className="feature-glow" />
                    <a.icon size={24} className="text-gold-400 mb-4 relative z-10" />
                    <h4 className="font-semibold text-gold-200 mb-1 relative z-10">{a.title}</h4>
                    <p className="text-xs text-gold-200/40 relative z-10">{a.desc}</p>
                  </Link>
                </motion.div>
              ))}
            </motion.div>
          </div>

          <div className="space-y-4">
            <h3 className="text-lg font-semibold text-gold-200">最近案件</h3>
            <div className="space-y-3">
              {recentCases.map((c) => (
                <div key={c.id} className="glass-card-static p-4">
                  <p className="text-sm text-gold-200 mb-2 truncate">{c.title}</p>
                  <div className="flex items-center justify-between">
                    <span className={`text-[10px] px-2 py-0.5 rounded-full
                      ${c.status === '已完成' ? 'bg-green-400/10 text-green-400' :
                        c.status === '分析中' ? 'bg-gold-400/10 text-gold-400' :
                        'bg-gold-200/10 text-gold-200/50'}`}>
                      {c.status}
                    </span>
                    <span className="text-[10px] text-gold-200/30">{c.time}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
