import fitz  # PyMuPDF
from typing import Optional, Dict, Any, List
from PIL import Image

# 尝试导入cv2和numpy，如果失败则设置为None
try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    cv2 = None
    np = None
    CV2_AVAILABLE = False


class DocumentParserService:
    """文档解析服务"""
    
    def __init__(self):
        # 延迟导入PaddleOCR以减少启动时间
        self.ocr = None
    
    def _get_ocr(self):
        """获取OCR实例"""
        if self.ocr is None:
            from paddleocr import PaddleOCR
            self.ocr = PaddleOCR(
                lang='ch',
                use_angle_cls=True,
                use_gpu=False  # 默认为False，可根据需要启用GPU
            )
        return self.ocr
    
    def parse_pdf(self, pdf_path: str) -> Dict[str, Any]:
        """解析PDF文件
        
        返回包含文本内容和解析状态的字典
        """
        try:
            doc = fitz.open(pdf_path)
            
            # 检查是否为文本型PDF
            is_text_based = self._is_text_based_pdf(doc)
            
            if is_text_based:
                # 文本型PDF直接提取
                text = self._extract_text_from_pdf(doc)
                return {
                    "success": True,
                    "text": text,
                    "is_text_based": True,
                    "page_count": len(doc),
                    "method": "text_extraction"
                }
            else:
                # 扫描型PDF使用OCR
                if CV2_AVAILABLE:
                    text = self._ocr_scanned_pdf(doc)
                    return {
                        "success": True,
                        "text": text,
                        "is_text_based": False,
                        "page_count": len(doc),
                        "method": "ocr"
                    }
                else:
                    return {
                        "success": False,
                        "error": "OCR功能不可用，缺少必要的依赖库",
                        "method": "ocr"
                    }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "method": "unknown"
            }
    
    def _is_text_based_pdf(self, doc: fitz.Document) -> bool:
        """判断PDF是否为文本型"""
        text_count = 0
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            if text.strip():
                text_count += 1
        
        # 如果超过50%的页面有文本，则认为是文本型PDF
        return text_count / len(doc) > 0.5
    
    def _extract_text_from_pdf(self, doc: fitz.Document) -> str:
        """从文本型PDF提取文本"""
        text = []
        for page_num in range(len(doc)):
            page = doc[page_num]
            page_text = page.get_text()
            if page_text.strip():
                text.append(f"=== 第 {page_num + 1} 页 ===")
                text.append(page_text)
        
        return "\n".join(text)
    
    def _ocr_scanned_pdf(self, doc: fitz.Document) -> str:
        """使用OCR处理扫描型PDF"""
        text = []
        ocr = self._get_ocr()
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            # 将PDF页面转换为图像
            pix = page.get_pixmap()
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            img_array = np.array(img)
            
            # 使用OCR识别
            result = ocr.ocr(img_array, cls=True)
            
            # 提取文本
            page_text = []
            for line in result:
                for word_info in line:
                    if len(word_info) >= 2:
                        page_text.append(word_info[1][0])
            
            if page_text:
                text.append(f"=== 第 {page_num + 1} 页 ===")
                text.append(" ".join(page_text))
        
        return "\n".join(text)
    
    def parse_image(self, image_path: str) -> Dict[str, Any]:
        """解析图像文件"""
        try:
            ocr = self._get_ocr()
            result = ocr.ocr(image_path, cls=True)
            
            text = []
            for line in result:
                for word_info in line:
                    if len(word_info) >= 2:
                        text.append(word_info[1][0])
            
            return {
                "success": True,
                "text": " ".join(text),
                "method": "ocr"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "method": "ocr"
            }
    
    def parse_text(self, text_path: str) -> Dict[str, Any]:
        """解析文本文件"""
        try:
            with open(text_path, 'r', encoding='utf-8') as f:
                text = f.read()
            
            return {
                "success": True,
                "text": text,
                "method": "text_read"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "method": "text_read"
            }
    
    def smart_parse(self, file_path: str) -> Dict[str, Any]:
        """智能解析文件
        
        根据文件扩展名自动选择解析方法
        """
        import os
        ext = os.path.splitext(file_path)[1].lower()
        
        if ext == '.pdf':
            return self.parse_pdf(file_path)
        elif ext in ['.jpg', '.jpeg', '.png', '.bmp']:
            return self.parse_image(file_path)
        elif ext == '.txt':
            return self.parse_text(file_path)
        else:
            return {
                "success": False,
                "error": f"不支持的文件类型: {ext}",
                "method": "unknown"
            }


# 全局单例
_document_parser_service: Optional[DocumentParserService] = None


def get_document_parser_service() -> DocumentParserService:
    """获取文档解析服务"""
    global _document_parser_service
    if _document_parser_service is None:
        _document_parser_service = DocumentParserService()
    return _document_parser_service
