from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path
from textwrap import dedent

from ..config import (
    AI_SUMMARY_API_KEY,
    AI_SUMMARY_BASE_URL,
    AI_SUMMARY_MAX_IMAGE_BYTES,
    AI_SUMMARY_MAX_IMAGES,
    AI_SUMMARY_MAX_TEXT_CHARS,
    AI_SUMMARY_MODEL,
    AI_SUMMARY_TEMPERATURE,
    AI_SUMMARY_TIMEOUT,
    STATIC_DIR,
)
from ..models import Post


logger = logging.getLogger(__name__)


class AISummaryConfigurationError(RuntimeError):
    """Raised when AI summary credentials are missing."""


class AISummaryGenerationError(RuntimeError):
    """Raised when the model cannot produce a usable summary."""


def is_ai_summary_configured() -> bool:
    return bool(AI_SUMMARY_API_KEY and AI_SUMMARY_BASE_URL and AI_SUMMARY_MODEL)


def summarize_post(
    post: Post,
    *,
    like_count: int = 0,
    comments: list[str] | None = None,
) -> tuple[str, int]:
    if not is_ai_summary_configured():
        raise AISummaryConfigurationError('请先在 .env 中配置 AI_SUMMARY_API_KEY 和 AI_SUMMARY_BASE_URL。')

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise AISummaryGenerationError('LangChain 依赖未安装，请先执行 pip install -r requirements.txt。') from exc

    clean_comments = [item.strip() for item in (comments or []) if item and item.strip()]
    text_payload = _build_text_payload(post, like_count=like_count, comments=clean_comments)
    image_blocks = _build_image_blocks(post.images)
    if not text_payload and not image_blocks:
        raise AISummaryGenerationError('这条帖子没有可供总结的文本或图片内容。')

    logger.info(
        'Requesting LLM summary for post_id=%s model=%s base_url=%s text_chars=%s image_count=%s like_count=%s comment_count=%s',
        post.id,
        AI_SUMMARY_MODEL,
        AI_SUMMARY_BASE_URL,
        len(text_payload),
        len(image_blocks),
        like_count,
        len(clean_comments),
    )

    model = ChatOpenAI(
        model=AI_SUMMARY_MODEL,
        api_key=AI_SUMMARY_API_KEY,
        base_url=AI_SUMMARY_BASE_URL,
        temperature=AI_SUMMARY_TEMPERATURE,
        timeout=AI_SUMMARY_TIMEOUT,
        max_retries=2,
    )
    response = model.invoke(
        [
            SystemMessage(
                content=(
                    '你是一个中文校园社区助手。'
                    '请根据用户提供的帖子文字和图片，生成简短、客观、自然的中文总结。'
                    '不要编造图片里没有的信息，不要输出标题、项目符号、Markdown 或“作为 AI”之类的措辞。'
                )
            ),
            HumanMessage(
                content=[
                    {'type': 'text', 'text': _build_prompt(text_payload, len(image_blocks))},
                    *image_blocks,
                ]
            ),
        ]
    )
    summary = _normalize_summary(response.content)
    if not summary:
        logger.warning('LLM returned empty summary for post_id=%s model=%s', post.id, AI_SUMMARY_MODEL)
        raise AISummaryGenerationError('模型没有返回可用的总结内容，请稍后重试。')
    logger.info(
        'LLM summary completed for post_id=%s model=%s summary_chars=%s',
        post.id,
        AI_SUMMARY_MODEL,
        len(summary),
    )
    return summary, len(image_blocks)


def _build_text_payload(post: Post, *, like_count: int, comments: list[str]) -> str:
    parts: list[str] = []
    if post.title:
        parts.append(f'标题：{post.title.strip()}')
    if post.content:
        content = post.content.strip()
        if len(content) > AI_SUMMARY_MAX_TEXT_CHARS:
            content = f'{content[:AI_SUMMARY_MAX_TEXT_CHARS]}...'
        parts.append(f'正文：{content}')
    parts.append(f'点赞数：{like_count}')
    if comments:
        comment_lines = [f'- {comment[:160]}' for comment in comments[:8]]
        parts.append('评论区摘录：\n' + '\n'.join(comment_lines))
    else:
        parts.append('评论区摘录：暂无评论')
    return '\n\n'.join(parts).strip()


def _build_prompt(text_payload: str, image_count: int) -> str:
    source_hint = (
        f'本次还附带了 {image_count} 张图片，请结合图片视觉内容一起判断。'
        if image_count
        else '这条帖子没有可用图片，请仅根据文字内容总结。'
    )
    body = text_payload or '这条帖子没有文字正文，请主要根据图片内容做出简短总结。'
    return dedent(
        f"""
        请为这条帖子写一段简短中文解释。

        要求：
        1. 输出 2 到 4 句，控制在 120 个中文字符左右。
        2. 先概括帖子在讲什么，再点出图片或文字里的核心信息。
        3. 可以参考点赞数和评论区反馈判断帖子关注点，但不要夸大热度。
        4. 不要使用 Markdown、标题、序号或项目符号。
        5. 如果信息不足，请用“根据现有图文和互动信息”这种自然说法保留判断。

        {source_hint}

        帖子内容：
        {body}
        """
    ).strip()


def _build_image_blocks(image_urls: list[str]) -> list[dict]:
    image_blocks: list[dict] = []
    for image_url in image_urls[:AI_SUMMARY_MAX_IMAGES]:
        image_block = _image_url_to_block(image_url)
        if image_block is not None:
            image_blocks.append(image_block)
    return image_blocks


def _image_url_to_block(image_url: str) -> dict | None:
    if image_url.startswith('/static/'):
        file_path = _resolve_static_path(image_url)
        if file_path is None or not file_path.is_file():
            return None
        if file_path.stat().st_size > AI_SUMMARY_MAX_IMAGE_BYTES:
            return None

        mime_type = mimetypes.guess_type(str(file_path))[0] or ''
        if not mime_type.startswith('image/'):
            return None

        encoded = base64.b64encode(file_path.read_bytes()).decode('ascii')
        return {'type': 'image_url', 'image_url': {'url': f'data:{mime_type};base64,{encoded}'}}

    if image_url.startswith('http://') or image_url.startswith('https://'):
        return {'type': 'image_url', 'image_url': {'url': image_url}}

    return None


def _resolve_static_path(image_url: str) -> Path | None:
    relative_path = image_url.removeprefix('/static/').strip('/')
    candidate = (STATIC_DIR / Path(relative_path)).resolve()
    static_root = STATIC_DIR.resolve()
    try:
        candidate.relative_to(static_root)
    except ValueError:
        return None
    return candidate


def _normalize_summary(content: str | list) -> str:
    if isinstance(content, str):
        return content.strip()

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            cleaned = item.strip()
            if cleaned:
                parts.append(cleaned)
            continue
        if isinstance(item, dict) and item.get('type') == 'text':
            text = str(item.get('text', '')).strip()
            if text:
                parts.append(text)
    return '\n'.join(parts).strip()
