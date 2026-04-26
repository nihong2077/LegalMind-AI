'use client'

import { useState, useEffect } from 'react'
import { ArrowRight, Law, User, Clock, CheckCircle, AlertCircle, FileText } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import Navbar from '@/components/Navbar'
import Footer from '@/components/Footer'
import Link from 'next/link'

interface CaseAnalysisResult {
  analyst_output?: string
  plaintiff_output?: string
  defendant_output?: string
  judge_output?: string
  mediator_output?: string
  summary?: string
  error?: string
}

export default function ComplexAnalysisPage() {
  const [caseDescription, setCaseDescription] = useState('')
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [analysisResult, setAnalysisResult] = useState<CaseAnalysisResult | null>(null)
  const [currentStep, setCurrentStep] = useState(0)
  const [showResult, setShowResult] = useState(false)

  const steps = [
    { name: '案情分析', icon: FileText },
    { name: '原告律师', icon: User },
    { name: '被告律师', icon: User },
    { name: '法官裁判', icon: Law },
    { name: '调解员', icon: CheckCircle },
    { name: '生成总结', icon: FileText }
  ]

  const handleAnalyze = async () => {
    if (!caseDescription.trim()) return
    
    setIsAnalyzing(true)
    setAnalysisResult(null)
    setShowResult(false)
    setCurrentStep(0)

    try {
      const token = localStorage.getItem('token')
      const response = await fetch('/api/complex-analysis', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': token ? `Bearer ${token}` : '',
        },
        body: JSON.stringify({ case_description: caseDescription }),
      })

      if (!response.ok) {
        throw new Error('分析失败')
      }

      // 流式响应，逐步更新
      const reader = response.body?.getReader()
      const decoder = new TextDecoder()
      let result: CaseAnalysisResult = {}
      
      if (reader) {
        let buffer = ''
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''
          
          for (const line of lines) {
            if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))
            result = { ...result, ...data }
            setAnalysisResult({ ...result })
            
            if (data.step && data.step > currentStep) {
              setCurrentStep(data.step)
            }
          } catch (e) {
              console.error('解析失败', e)
            }
          }
        }
      }

      setShowResult(true)
    } catch (error) {
      console.error('分析错误:', error)
      setAnalysisResult({ error: '分析过程中出错，请稍后重试' })
    } finally {
      setIsAnalyzing(false)
    }
  }

  return (
    <div className="min-h-screen flex flex-col bg-navy-950">
      <Navbar />
      
      <main className="flex-1 max-w-7xl mx-auto w-full px-6 py-12">
        <div className="mb-8">
          <Link href="/" className="text-gold-400 hover:text-gold-300 flex items-center gap-2 mb-6">
          ← 返回首页
        </Link>
          <h1 className="text-3xl font-bold text-gold-100 mb-2">复杂案情分析</h1>
          <p className="text-gold-200/60">
            深度分析案件事实，识别法律关系，归纳争议焦点，提供专业法律分析报告
          </p>
        </div>

        <div className="grid lg:grid-cols-2 gap-8">
          {/* 输入区域 */}
          <div className="space-y-6">
            <div className="glass-card p-6 rounded-xl border border-gold-400/10">
              <h2 className="text-xl font-bold text-gold-100 mb-4">案件描述</h2>
              <textarea
                value={caseDescription}
                onChange={(e) => setCaseDescription(e.target.value)}
                placeholder="请详细描述您的案件情况..."
                className="w-full h-64 bg-navy-800/50 border border-gold-400/20 rounded-lg p-4 text-gold-200 placeholder-gold-200/40 focus:outline-none focus:border-gold-400/50 resize-none"
              />
              <button
                onClick={handleAnalyze}
                disabled={isAnalyzing || !caseDescription.trim()}
                className="gold-btn mt-4 w-full flex items-center justify-center gap-2"
              >
                {isAnalyzing ? (
                  <>
                    <span className="animate-pulse">分析中...</span>
                  </>
                ) : (
                  <>
                    开始分析 <ArrowRight className="w-5 h-5" />
                  </>
                )}
              </button>
            </div>

            {/* 分析步骤 */}
            <div className="glass-card p-6 rounded-xl border border-gold-400/10">
              <h2 className="text-xl font-bold text-gold-100 mb-4">分析步骤</h2>
              <div className="space-y-3">
                {steps.map((step, index) => (
                <div
                    key={index}
                    className={`flex items-center gap-4 p-3 rounded-lg transition-all ${
                    index < currentStep
                      ? 'bg-green-400/10 border border-green-400/20'
                      : index === currentStep && isAnalyzing
                      ? 'bg-gold-400/10 border border-gold-400/20 animate-pulse'
                      : 'bg-navy-800/30 border border-gold-400/5'
                    }`}
                >
                  <div className={`w-10 h-10 rounded-full flex items-center justify-center ${
                    index < currentStep
                      ? 'bg-green-400/20 text-green-400'
                      : index === currentStep && isAnalyzing
                      ? 'bg-gold-400/20 text-gold-400'
                      : 'bg-navy-800/50 text-gold-200/30'
                    }`}>
                    {index < currentStep ? (
                      <CheckCircle className="w-5 h-5" />
                    ) : (
                      <step.icon className="w-5 h-5" />
                    )}
                  </div>
                    <div className="flex-1">
                    <span className={`font-medium ${
                      index < currentStep
                        ? 'text-green-400'
                        : index === currentStep && isAnalyzing
                        ? 'text-gold-400'
                        : 'text-gold-200/50'
                    }`}>
                        {step.name}
                    </span>
                  </div>
                </div>
              ))}
              </div>
            </div>
          </div>

          {/* 结果区域 */}
          <div className="space-y-6">
            <AnimatePresence>
              {showResult && analysisResult && (
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="glass-card p-6 rounded-xl border border-gold-400/10"
                >
                  <h2 className="text-xl font-bold text-gold-100 mb-4">分析结果</h2>
                  
                  {analysisResult.error ? (
                    <div className="p-4 bg-red-900/20 border border-red-500/30 rounded-lg text-red-400">
                      {analysisResult.error}
                    </div>
                  ) : (
                    <div className="space-y-6">
                      {analysisResult.summary && (
                        <div>
                          <h3 className="text-lg font-bold text-gold-200 mb-2 flex items-center gap-2">
                            <FileText className="w-5 h-5" /> 分析总结
                          </h3>
                          <div className="bg-navy-800/50 p-4 rounded-lg text-gold-200/80 whitespace-pre-wrap">
                            {analysisResult.summary}
                          </div>
                        </div>
                      )}
                      
                      {analysisResult.analyst_output && (
                        <div>
                          <h3 className="text-lg font-bold text-gold-200 mb-2 flex items-center gap-2">
                            <FileText className="w-5 h-5" /> 案情分析
                          </h3>
                          <div className="bg-navy-800/50 p-4 rounded-lg text-gold-200/80 whitespace-pre-wrap">
                            {analysisResult.analyst_output}
                          </div>
                        </div>
                      )}
                      
                      {analysisResult.plaintiff_output && (
                        <div>
                          <h3 className="text-lg font-bold text-gold-200 mb-2 flex items-center gap-2">
                            <User className="w-5 h-5" /> 原告律师意见
                          </h3>
                          <div className="bg-navy-800/50 p-4 rounded-lg text-gold-200/80 whitespace-pre-wrap">
                            {analysisResult.plaintiff_output}
                          </div>
                        </div>
                      )}
                      
                      {analysisResult.defendant_output && (
                        <div>
                          <h3 className="text-lg font-bold text-gold-200 mb-2 flex items-center gap-2">
                            <User className="w-5 h-5" /> 被告律师意见
                          </h3>
                          <div className="bg-navy-800/50 p-4 rounded-lg text-gold-200/80 whitespace-pre-wrap">
                            {analysisResult.defendant_output}
                          </div>
                        </div>
                      )}
                      
                      {analysisResult.judge_output && (
                        <div>
                          <h3 className="text-lg font-bold text-gold-200 mb-2 flex items-center gap-2">
                            <Law className="w-5 h-5" /> 法官裁判意见
                          </h3>
                          <div className="bg-navy-800/50 p-4 rounded-lg text-gold-200/80 whitespace-pre-wrap">
                            {analysisResult.judge_output}
                          </div>
                        </div>
                      )}
                      
                      {analysisResult.mediator_output && (
                        <div>
                          <h3 className="text-lg font-bold text-gold-200 mb-2 flex items-center gap-2">
                            <CheckCircle className="w-5 h-5" /> 调解员和解方案
                          </h3>
                          <div className="bg-navy-800/50 p-4 rounded-lg text-gold-200/80 whitespace-pre-wrap">
                            {analysisResult.mediator_output}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </main>

      <Footer />
    </div>
  )
}
