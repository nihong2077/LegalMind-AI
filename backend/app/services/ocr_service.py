"""PaddleOCR AIStudio 异步任务 OCR 服务封装。

流程: 提交文件 → 轮询任务状态 → 下载 JSONL 结果 → 拼接纯文本。
仅依赖 httpx,与项目异步架构一致,不阻塞事件循环。
"""
import asyncio
import json
import logging
import os
from typing import Optional

import httpx

from ..core.config import settings

logger = logging.getLogger(__name__)

# PaddleOCR 任务 API 基础路径
JOB_BASE = settings.OCR_API_URL.rstrip("/")

# 可选参数: 合同扫描件方向固定,关闭校正类预处理以加速识别
OPTIONAL_PAYLOAD = {
    "useDocOrientationClassify": False,
    "useDocUnwarping": False,
    "useTextlineOrientation": False,
}


def _auth_headers() -> dict:
    """构造鉴权 header。Token 从 .env 读取,不硬编码。"""
    return {
        "Authorization": f"bearer {settings.OCR_API_TOKEN}",
    }


async def submit_ocr_job(client: httpx.AsyncClient, file_path: str) -> str:
    """提交 OCR 任务,返回 jobId。"""
    headers = _auth_headers()
    data = {
        "model": settings.OCR_MODEL,
        "optionalPayload": json.dumps(OPTIONAL_PAYLOAD),
    }
    with open(file_path, "rb") as f:
        files = {"file": (os.path.basename(file_path), f, "application/octet-stream")}
        resp = await client.post(JOB_BASE, headers=headers, data=data, files=files)

    if resp.status_code != 200:
        raise RuntimeError(f"OCR 提交失败 status={resp.status_code} body={resp.text}")

    payload = resp.json()
    job_id = payload.get("data", {}).get("jobId")
    if not job_id:
        raise RuntimeError(f"OCR 响应缺少 jobId: {payload}")
    logger.info("OCR 任务已提交: %s (file=%s)", job_id, os.path.basename(file_path))
    return job_id


async def poll_ocr_job(client: httpx.AsyncClient, job_id: str) -> str:
    """轮询任务状态,done 时返回 jsonUrl;failed 或超时抛异常。"""
    headers = _auth_headers()
    deadline = asyncio.get_event_loop().time() + settings.OCR_POLL_TIMEOUT
    poll_interval = settings.OCR_POLL_INTERVAL
    url = f"{JOB_BASE}/{job_id}"

    while True:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(f"OCR 轮询失败 status={resp.status_code} body={resp.text}")

        data = resp.json().get("data", {})
        state = data.get("state")
        progress = data.get("extractProgress", {})

        if state == "done":
            json_url = data.get("resultUrl", {}).get("jsonUrl", "")
            if not json_url:
                raise RuntimeError(f"OCR done 但缺少 jsonUrl: {data}")
            logger.info(
                "OCR 任务完成: %s (extractedPages=%s)",
                job_id, progress.get("extractedPages"),
            )
            return json_url

        if state == "failed":
            err = data.get("errorMsg", "未知错误")
            raise RuntimeError(f"OCR 任务失败: {err}")

        # pending / running 继续轮询
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError(f"OCR 轮询超时 ({settings.OCR_POLL_TIMEOUT}s),last_state={state}")

        logger.debug("OCR 轮询中: state=%s progress=%s", state, progress)
        await asyncio.sleep(poll_interval)


def _extract_text_from_page(page_result: dict) -> str:
    """从单页 OCR 结果提取纯文本,按 y 坐标排序保持阅读顺序。

    PaddleOCR JSONL 每行 result.ocrResults 是该页所有文本框。
    字段名做 fallback: recText / rec_text / text 任一存在即用。
    坐标字段: detPoly / det_polygon 任一存在即用。
    """
    ocr_results = page_result.get("ocrResults") or page_result.get("ocr_results") or []
    if not ocr_results:
        # 某些版本直接把整页 markdown 放在 md 字段
        md = page_result.get("md") or page_result.get("markdown")
        if md:
            return md
        return ""

    # 收集 (y, text) 对,按 y 排序后逐行拼接
    lines: list[tuple[float, str]] = []
    for res in ocr_results:
        # 文本字段 fallback
        text = (
            res.get("recText")
            or res.get("rec_text")
            or res.get("text")
            or ""
        )
        if not text:
            continue

        # 坐标字段 fallback: detPolygon 可能是 [[x1,y1],[x2,y2],...] 或扁平 [x1,y1,x2,y2,...]
        poly = res.get("detPoly") or res.get("det_polygon") or res.get("detPolygon")
        y_top = 0.0
        if poly and isinstance(poly, list):
            try:
                if isinstance(poly[0], (list, tuple)):
                    ys = [pt[1] for pt in poly]
                else:
                    # 扁平结构 [x1,y1,x2,y2,...]
                    ys = [poly[i] for i in range(1, len(poly), 2)]
                if ys:
                    y_top = min(ys)
            except (IndexError, TypeError):
                y_top = 0.0

        lines.append((y_top, text))

    # 按 y 排序,相同 y 容差 5px 视为同一行
    lines.sort(key=lambda x: x[0])
    merged: list[str] = []
    prev_y: Optional[float] = None
    current_line: list[str] = []

    for y, text in lines:
        if prev_y is None or abs(y - prev_y) <= 5.0:
            current_line.append(text)
        else:
            merged.append(" ".join(current_line))
            current_line = [text]
        prev_y = y

    if current_line:
        merged.append(" ".join(current_line))

    return "\n".join(merged)


async def fetch_ocr_text(client: httpx.AsyncClient, json_url: str) -> str:
    """下载 JSONL 结果并拼接为纯文本。"""
    resp = await client.get(json_url)
    resp.raise_for_status()

    parts: list[str] = []
    for line in resp.text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("OCR JSONL 解析失败,跳过该行")
            continue

        result = obj.get("result", {})
        page_text = _extract_text_from_page(result)
        if page_text:
            parts.append(page_text)

    return "\n\n".join(parts)


async def ocr_file(file_path: str) -> str:
    """统一入口: 提交 → 轮询 → 拉取文本。

    失败时返回空字符串并 log warning,不抛异常,避免阻塞文档读取主流程。
    """
    if not settings.OCR_API_TOKEN:
        logger.warning("OCR_API_TOKEN 未配置,跳过 OCR")
        return ""

    if not os.path.exists(file_path):
        logger.warning("OCR 文件不存在: %s", file_path)
        return ""

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            job_id = await submit_ocr_job(client, file_path)
            json_url = await poll_ocr_job(client, job_id)
            text = await fetch_ocr_text(client, json_url)
            logger.info("OCR 完成: %s (text_len=%d)", file_path, len(text))
            return text
    except Exception as e:
        logger.warning("OCR 失败 %s: %s", file_path, e)
        return ""
