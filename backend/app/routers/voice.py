from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import Response
from app.services.voice_service import voice_service
import asyncio

router = APIRouter()

@router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """转录音频文件为文本"""
    try:
        audio_bytes = await file.read()
        text = await voice_service.process_audio_bytes(audio_bytes)
        return {"text": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"音频处理失败: {str(e)}")

@router.post("/synthesize")
async def synthesize_speech(text: str):
    """将文本合成为语音"""
    try:
        audio_bytes = await voice_service.generate_speech(text)
        if audio_bytes:
            return Response(
                content=audio_bytes,
                media_type="audio/wav"
            )
        raise HTTPException(status_code=500, detail="语音合成失败")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"语音合成失败: {str(e)}")