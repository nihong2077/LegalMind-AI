from typing import Dict, Any, List, Optional
import re
from app.core.llm_client import get_llm_client

class OutputAuditor:
    """输出审核服务"""
    
    def __init__(self):
        self.llm = get_llm_client()
        # 敏感内容模式
        self.sensitive_patterns = [
            r"违法|犯罪|毒品|赌博|色情|暴力|恐怖|极端|颠覆|分裂|邪教|诈骗",
            r"个人隐私|身份证|银行卡|密码|联系方式",
            r"歧视|侮辱|诽谤|威胁",
            r"虚假信息|谣言|误导",
            r"侵权|盗版|抄袭"
        ]
        
        # 法律风险关键词
        self.legal_risk_words = [
            "建议起诉", "建议报警", "肯定胜诉", "必然赔偿",
            "保证结果", "绝对有效", "完全合法", "毫无风险"
        ]
    
    def check_sensitive_content(self, text: str) -> List[str]:
        """检查敏感内容"""
        issues = []
        
        for pattern in self.sensitive_patterns:
            if re.search(pattern, text):
                issues.append(f"包含敏感内容: {pattern}")
        
        for word in self.legal_risk_words:
            if word in text:
                issues.append(f"包含法律风险表述: {word}")
        
        return issues
    
    async def audit_output(self, output: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """审核输出内容"""
        # 初步检查
        issues = self.check_sensitive_content(output)
        
        # 使用LLM进行深度审核
        audit_result = await self._llm_audit(output, context)
        
        # 合并结果
        if audit_result.get("issues"):
            issues.extend(audit_result["issues"])
        
        return {
            "original_output": output,
            "issues": issues,
            "is_safe": len(issues) == 0,
            "modified_output": audit_result.get("modified_output", output)
        }
    
    async def _llm_audit(self, output: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """使用LLM进行深度审核"""
        audit_prompt = self._generate_audit_prompt(output, context)
        
        messages = [
            {"role": "system", "content": self._get_auditor_system_prompt()},
            {"role": "user", "content": audit_prompt}
        ]
        
        try:
            response = await self.llm.chat(
                model="gpt-4o",
                messages=messages,
                temperature=0.3
            )
            
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            return self._parse_audit_result(content)
        except Exception as e:
            return {
                "issues": [f"审核失败: {str(e)}"],
                "modified_output": output
            }
    
    def _get_auditor_system_prompt(self) -> str:
        """获取审核器系统提示"""
        return """你是一名专业的内容审核专家，负责检查法律智能体的输出内容。

审核标准：
1. 合法性：输出内容是否符合法律法规
2. 道德性：输出内容是否符合社会道德规范
3. 准确性：输出内容是否准确、客观
4. 安全性：输出内容是否存在安全风险
5. 专业性：输出内容是否专业、严谨

审核要求：
- 识别并列出所有问题
- 提供修改建议
- 输出格式：JSON格式，包含issues数组（问题列表）和modified_output（修改后的内容）"""
    
    def _generate_audit_prompt(self, output: str, context: Dict[str, Any] = None) -> str:
        """生成审核提示"""
        prompt = f"需要审核的内容：{output}\n"
        if context:
            prompt += f"\n上下文信息：{context}\n"
        prompt += "\n请对上述内容进行审核，并以JSON格式输出审核结果。"
        return prompt
    
    def _parse_audit_result(self, content: str) -> Dict[str, Any]:
        """解析审核结果"""
        import json
        try:
            # 提取JSON部分
            start_idx = content.find('{')
            end_idx = content.rfind('}') + 1
            if start_idx != -1 and end_idx != -1:
                json_str = content[start_idx:end_idx]
                result = json.loads(json_str)
                
                # 验证结果格式
                if "issues" in result and "modified_output" in result:
                    return result
        except Exception as e:
            print(f"解析审核结果失败: {e}")
        
        # 解析失败时返回默认值
        return {
            "issues": [],
            "modified_output": content
        }
    
    def sanitize_output(self, output: str) -> str:
        """清理输出内容"""
        # 移除敏感信息
        output = re.sub(r"[0-9]{18}", "***", output)  # 身份证号
        output = re.sub(r"[0-9]{16,19}", "***", output)  # 银行卡号
        output = re.sub(r"1[3-9]\d{9}", "***", output)  # 手机号
        
        # 移除危险表述
        for word in self.legal_risk_words:
            output = output.replace(word, "")
        
        return output

# 全局单例
output_auditor = OutputAuditor()