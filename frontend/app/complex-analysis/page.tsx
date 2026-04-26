'use client'

import { useState, useEffect } from 'react'
import { ArrowRight, Gavel, User, Clock, CheckCircle, AlertCircle, FileText } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import Sidebar from '@/components/Sidebar'

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
    { name: '法官裁判', icon: Gavel },
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
                
                // 更新步骤
                if (data.step && data.step > currentStep) {
                  setCurrentStep(data.step)
                } else if (data.analyst_output && currentStep < 1) {
                  setCurrentStep(1)
                } else if (data.plaintiff_output && currentStep < 2) {
                  setCurrentStep(2)
                } else if (data.defendant_output && currentStep < 3) {
                  setCurrentStep(3)
                } else if (data.judge_output && currentStep < 4) {
                  setCurrentStep(4)
                } else if (data.mediator_output && currentStep < 5) {
                  setCurrentStep(5)
                } else if (data.summary && currentStep < 6) {
                  setCurrentStep(6)
                }
              } catch (e) {
                console.error('解析失败', e)
              }
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
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex-1 flex flex-col min-h-0">
        <div className="px-6 py-4 border-b border-gold-400/10 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-gold-200">复杂案情分析</h2>
            <p className="text-xs text-gold-200/40">深度分析案件事实，识别法律关系，归纳争议焦点</p>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-6">
          <div className="grid lg:grid-cols-2 gap-8 max-w-6xl mx-auto">
            {/* 输入区域 */}
            <div className="space-y-6">
              <motion.div 
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.6 }}
                className="glass-card p-6 rounded-xl border border-gold-400/10"
              >
                <h2 className="text-xl font-bold text-gold-100 mb-4">案件描述</h2>
                <textarea
                  value={caseDescription}
                  onChange={(e) => setCaseDescription(e.target.value)}
                  placeholder="请详细描述您的案件情况..."
                  className="input-field h-64 resize-none"
                />
                <button
                  onClick={handleAnalyze}
                  disabled={isAnalyzing || !caseDescription.trim()}
                  className="gold-btn mt-6 w-full flex items-center justify-center gap-2 py-3"
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
              </motion.div>

              {/* 分析步骤 */}
              <motion.div 
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.6, delay: 0.2 }}
                className="glass-card p-6 rounded-xl border border-gold-400/10"
              >
                <h2 className="text-xl font-bold text-gold-100 mb-6">分析步骤</h2>
                <div className="space-y-4">
                  {steps.map((step, index) => (
                    <motion.div
                      key={index}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.4, delay: 0.1 * index }}
                      className={`flex items-center gap-4 p-4 rounded-lg transition-all duration-300 ${
                        index < currentStep
                          ? 'bg-green-400/10 border border-green-400/20'
                          : index === currentStep && isAnalyzing
                          ? 'bg-gold-400/10 border border-gold-400/20 animate-pulse'
                          : 'bg-navy-800/30 border border-gold-400/5'
                      }`}
                    >
                      <div className={`w-12 h-12 rounded-full flex items-center justify-center transition-all duration-300 ${
                        index < currentStep
                          ? 'bg-green-400/20 text-green-400 shadow-lg shadow-green-400/20'
                          : index === currentStep && isAnalyzing
                          ? 'bg-gold-400/20 text-gold-400 shadow-lg shadow-gold-400/20'
                          : 'bg-navy-800/50 text-gold-200/30'
                      }`}>
                        {index < currentStep ? (
                          <CheckCircle className="w-6 h-6" />
                        ) : (
                          <step.icon className="w-6 h-6" />
                        )}
                      </div>
                      <div className="flex-1">
                        <span className={`font-medium transition-all duration-300 ${
                          index < currentStep
                            ? 'text-green-400'
                            : index === currentStep && isAnalyzing
                            ? 'text-gold-400'
                            : 'text-gold-200/50'
                        }`}>
                          {step.name}
                        </span>
                      </div>
                    </motion.div>
                  ))}
                </div>
              </motion.div>
            </div>

            {/* 结果区域 */}
            <div className="space-y-6">
              <AnimatePresence>
                {showResult && analysisResult && (
                  <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.6 }}
                    className="glass-card p-6 rounded-xl border border-gold-400/10"
                  >
                    <h2 className="text-xl font-bold text-gold-100 mb-6">分析结果</h2>
                    
                    {analysisResult.error ? (
                      <div className="p-5 bg-red-900/20 border border-red-500/30 rounded-lg text-red-400">
                        {analysisResult.error}
                      </div>
                    ) : (
                      <div className="space-y-6">
                        {analysisResult.summary && (
                          <motion.div
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ duration: 0.4 }}
                          >
                            <h3 className="text-lg font-semibold text-gold-200 mb-3 flex items-center gap-2">
                              <FileText className="w-5 h-5" /> 分析总结
                            </h3>
                            <div className="bg-navy-800/60 p-5 rounded-lg text-gold-200/90 whitespace-pre-wrap border border-gold-400/10">
                              {analysisResult.summary}
                            </div>
                          </motion.div>
                        )}
                        
                        {analysisResult.analyst_output && (
                          <motion.div
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ duration: 0.4, delay: 0.1 }}
                          >
                            <h3 className="text-lg font-semibold text-gold-200 mb-3 flex items-center gap-2">
                              <FileText className="w-5 h-5" /> 案情分析
                            </h3>
                            <div className="bg-navy-800/60 p-5 rounded-lg text-gold-200/90 whitespace-pre-wrap border border-gold-400/10">
                              {analysisResult.analyst_output}
                            </div>
                          </motion.div>
                        )}
                        
                        {analysisResult.plaintiff_output && (
                          <motion.div
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ duration: 0.4, delay: 0.2 }}
                          >
                            <h3 className="text-lg font-semibold text-gold-200 mb-3 flex items-center gap-2">
                              <User className="w-5 h-5" /> 原告律师意见
                            </h3>
                            <div className="bg-navy-800/60 p-5 rounded-lg text-gold-200/90 whitespace-pre-wrap border border-gold-400/10">
                              {analysisResult.plaintiff_output}
                            </div>
                          </motion.div>
                        )}
                        
                        {analysisResult.defendant_output && (
                          <motion.div
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ duration: 0.4, delay: 0.3 }}
                          >
                            <h3 className="text-lg font-semibold text-gold-200 mb-3 flex items-center gap-2">
                              <User className="w-5 h-5" /> 被告律师意见
                            </h3>
                            <div className="bg-navy-800/60 p-5 rounded-lg text-gold-200/90 whitespace-pre-wrap border border-gold-400/10">
                              {analysisResult.defendant_output}
                            </div>
                          </motion.div>
                        )}
                        
                        {analysisResult.judge_output && (
                          <motion.div
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ duration: 0.4, delay: 0.4 }}
                          >
                            <h3 className="text-lg font-semibold text-gold-200 mb-3 flex items-center gap-2">
                              <Gavel className="w-5 h-5" /> 法官裁判意见
                            </h3>
                            <div className="bg-navy-800/60 p-5 rounded-lg text-gold-200/90 whitespace-pre-wrap border border-gold-400/10">
                              {analysisResult.judge_output}
                            </div>
                          </motion.div>
                        )}
                        
                        {analysisResult.mediator_output && (
                          <motion.div
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ duration: 0.4, delay: 0.5 }}
                          >
                            <h3 className="text-lg font-semibold text-gold-200 mb-3 flex items-center gap-2">
                              <CheckCircle className="w-5 h-5" /> 调解员和解方案
                            </h3>
                            <div className="bg-navy-800/60 p-5 rounded-lg text-gold-200/90 whitespace-pre-wrap border border-gold-400/10">
                              {analysisResult.mediator_output}
                            </div>
                          </motion.div>
                        )}
                      </div>
                    )}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
