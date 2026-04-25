from typing import Dict, Any, List, Optional
import re
from fastapi import HTTPException, status

class InputValidator:
    """输入验证服务"""
    
    def __init__(self):
        # 正则表达式模式
        self.patterns = {
            "email": r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$",
            "username": r"^[a-zA-Z0-9_-]{3,20}$",
            "password": r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$",
            "phone": r"^1[3-9]\d{9}$",
            "text": r"^[\u4e00-\u9fa5a-zA-Z0-9\s.,!?'"";:()\[\]{}<>\-]+$",
            "case_description": r"^[\u4e00-\u9fa5a-zA-Z0-9\s.,!?'"";:()\[\]{}<>\-]{10,10000}$"
        }
        
        # 敏感词列表
        self.sensitive_words = [
            "违法", "犯罪", "毒品", "赌博", "色情", "暴力", 
            "恐怖", "极端", "颠覆", "分裂", "邪教", "诈骗"
        ]
    
    def validate_email(self, email: str) -> bool:
        """验证邮箱"""
        return bool(re.match(self.patterns["email"], email))
    
    def validate_username(self, username: str) -> bool:
        """验证用户名"""
        return bool(re.match(self.patterns["username"], username))
    
    def validate_password(self, password: str) -> bool:
        """验证密码"""
        return bool(re.match(self.patterns["password"], password))
    
    def validate_phone(self, phone: str) -> bool:
        """验证手机号"""
        return bool(re.match(self.patterns["phone"], phone))
    
    def validate_text(self, text: str) -> bool:
        """验证文本"""
        return bool(re.match(self.patterns["text"], text))
    
    def validate_case_description(self, description: str) -> bool:
        """验证案件描述"""
        return bool(re.match(self.patterns["case_description"], description))
    
    def check_sensitive_content(self, text: str) -> bool:
        """检查敏感内容"""
        for word in self.sensitive_words:
            if word in text:
                return True
        return False
    
    def validate_input(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """验证输入数据"""
        errors = {}
        
        # 验证邮箱
        if "email" in input_data:
            if not self.validate_email(input_data["email"]):
                errors["email"] = "邮箱格式不正确"
        
        # 验证用户名
        if "username" in input_data:
            if not self.validate_username(input_data["username"]):
                errors["username"] = "用户名格式不正确，长度3-20，只能包含字母、数字、下划线和连字符"
        
        # 验证密码
        if "password" in input_data:
            if not self.validate_password(input_data["password"]):
                errors["password"] = "密码必须至少8位，包含大小写字母、数字和特殊字符"
        
        # 验证手机号
        if "phone" in input_data:
            if input_data["phone"] and not self.validate_phone(input_data["phone"]):
                errors["phone"] = "手机号格式不正确"
        
        # 验证文本
        if "text" in input_data:
            if not self.validate_text(input_data["text"]):
                errors["text"] = "文本包含非法字符"
        
        # 验证案件描述
        if "case_description" in input_data:
            if not self.validate_case_description(input_data["case_description"]):
                errors["case_description"] = "案件描述长度必须在10-10000字之间，包含非法字符"
        
        # 检查敏感内容
        for key, value in input_data.items():
            if isinstance(value, str) and self.check_sensitive_content(value):
                errors[key] = "内容包含敏感信息"
        
        if errors:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=errors
            )
        
        return input_data
    
    def sanitize_input(self, input_data: Any) -> Any:
        """清理输入数据"""
        if isinstance(input_data, str):
            # 移除首尾空白
            input_data = input_data.strip()
            # 转义特殊字符
            input_data = input_data.replace("<", "&lt;").replace(">", "&gt;")
        elif isinstance(input_data, dict):
            for key, value in input_data.items():
                input_data[key] = self.sanitize_input(value)
        elif isinstance(input_data, list):
            for i, item in enumerate(input_data):
                input_data[i] = self.sanitize_input(item)
        
        return input_data

# 全局单例
input_validator = InputValidator()