from typing import Optional, Dict, Any
import asyncio
import tempfile
import os
from faster_whisper import WhisperModel
from cosyvoice.cli.cosyvoice import CosyVoice
from app.core.config import settings

class VoiceService:
    def __init__(self):
        self.whisper_model = None
        self.cosyvoice_model = None
        self._init_models()

    def _init_models(self):
        try:
            # 初始化Whisper模型
            self.whisper_model = WhisperModel(
                "small",
                device="cuda" if settings.USE_GPU else "cpu",
                compute_type="float16" if settings.USE_GPU else "int8"
            )
            
            # 初始化CosyVoice模型
            self.cosyvoice_model = CosyVoice()
        except Exception as e:
            print(f"语音模型初始化失败: {e}")

    async def transcribe_audio(self, audio_file: str) -> str:
        """使用Whisper模型转录音频"""
        try:
            segments, info = self.whisper_model.transcribe(
                audio_file,
                beam_size=5,
                language="zh"
            )
            
            text = "".join([segment.text for segment in segments])
            return text
        except Exception as e:
            print(f"音频转录失败: {e}")
            return ""

    async def text_to_speech(self, text: str, output_file: str) -> bool:
        """使用CosyVoice将文本转换为语音"""
        try:
            self.cosyvoice_model.inference(
                text=text,
                output_path=output_file
            )
            return True
        except Exception as e:
            print(f"语音合成失败: {e}")
            return False

    async def process_audio_bytes(self, audio_bytes: bytes) -> str:
        """处理音频字节数据"""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            temp_file.write(audio_bytes)
            temp_file_path = temp_file.name
        
        try:
            result = await self.transcribe_audio(temp_file_path)
            return result
        finally:
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    async def generate_speech(self, text: str) -> Optional[bytes]:
        """生成语音并返回字节数据"""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            temp_output_path = temp_file.name
        
        try:
            success = await self.text_to_speech(text, temp_output_path)
            if success:
                with open(temp_output_path, "rb") as f:
                    return f.read()
            return None
        finally:
            if os.path.exists(temp_output_path):
                os.unlink(temp_output_path)

voice_service = VoiceService()