"""
通用辅助工具函数
"""

import re
import time
from datetime import datetime
from typing import Optional


def generate_id(prefix: str = '', length: int = 8) -> str:
    """
    生成短 ID（用于商家 ID 等）
    
    Args:
        prefix: ID 前缀
        length: 随机部分长度
        
    Returns:
        生成的 ID 字符串
    """
    import uuid
    
    raw_id = uuid.uuid4().hex[:length]
    return f"{prefix}{raw_id}" if prefix else raw_id


def format_timestamp(timestamp: int | float, fmt: str = '%Y-%m-%d %H:%M:%S') -> str:
    """格式化时间戳为可读字符串"""
    try:
        return datetime.fromtimestamp(timestamp).strftime(fmt)
    except (ValueError, OSError):
        return str(timestamp)


def is_url_valid(url: str) -> bool:
    """检查 URL 是否有效"""
    pattern = r'^https?://[^\s/$.?#].[^\s]*$'
    return bool(re.match(pattern, url))


def normalize_url(url: str) -> str:
    """规范化 URL（补全协议，去除尾部斜杠）"""
    url = url.strip()
    
    # 补全协议
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    # 去除尾部斜杠
    url = url.rstrip('/')
    
    return url


def extract_domain(url: str) -> str:
    """从 URL 中提取域名（不含路径）"""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return parsed.netloc or url


def safe_json_parse(text: str, default=None):
    """安全地解析 JSON，失败返回默认值"""
    import json
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default


def truncate_text(text: str, max_length: int = 100, suffix: str = '...') -> str:
    """截断文本到指定长度"""
    text = str(text)
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def retry_async(
    func,
    max_retries: int = 3,
    delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,)
):
    """
    异步重试装饰器
    
    Args:
        func: 异步函数
        max_retries: 最大重试次数
        delay: 初始延迟时间（秒）
        backoff_factor: 延迟增长因子
        exceptions: 需要重试的异常类型
        
    Returns:
        包装后的异步函数
    """
    import asyncio
    import functools

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        last_exception = None
        current_delay = delay
        
        for attempt in range(max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except exceptions as e:
                last_exception = e
                
                if attempt < max_retries:
                    import logging
                    logger = logging.getLogger('finance-tools.helpers')
                    logger.warning(
                        f"Retry {attempt + 1}/{max_retries} for {func.__name__}: {e}, "
                        f"waiting {current_delay:.1f}s"
                    )
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff_factor
                else:
                    raise last_exception
    
    return wrapper


class Timer:
    """简单计时器上下文管理器"""
    
    def __init__(self, description: str = 'Operation'):
        self.description = description
        self.start_time: float = 0
        self.end_time: float = 0
        self.elapsed_ms: float = 0

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
        self.elapsed_ms = (self.end_time - self.start_time) * 1000
        return False

    @property
    def elapsed_str(self) -> str:
        if self.elapsed_ms < 1000:
            return f"{self.elapsed_ms:.0f}ms"
        elif self.elapsed_ms < 60000:
            return f"{self.elapsed_ms / 1000:.2f}s"
        else:
            minutes = int(self.elapsed_ms / 60000)
            seconds = (self.elapsed_ms % 60000) / 1000
            return f"{minutes}m {seconds:.1f}s"

    def log(self, logger_func=print):
        """输出计时结果"""
        logger_func(f"[Timer] {self.description}: {self.elapsed_str}")
