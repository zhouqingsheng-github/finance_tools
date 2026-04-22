"""
日志工具
统一的日志格式和级别控制
"""

import logging
import sys


def setup_logger(
    name: str = 'finance-tools',
    level: int = logging.INFO,
    log_file: str = None
) -> logging.Logger:
    """
    配置并返回日志记录器
    
    Args:
        name: 日志器名称
        level: 日志级别
        log_file: 可选的日志文件路径
        
    Returns:
        配置好的 Logger 实例
    """
    logger = logging.getLogger(name)
    
    # 避免重复添加 handler
    if logger.handlers:
        return logger
    
    logger.setLevel(level)
    
    # 格式化器
    formatter = logging.Formatter(
        fmt='%(asctime)s [%(levelname)-5s] %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 文件处理器（可选）
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)  # 文件记录所有级别
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


# 默认日志实例
log = setup_logger()
