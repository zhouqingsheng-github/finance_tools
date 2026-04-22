"""
商家配置解析器
解析和校验商家配置 JSON，提供默认值和验证逻辑
"""

import re
from typing import Any, Optional


class ConfigParser:
    """解析和校验商家配置"""
    
    def parse(self, raw_config: dict) -> dict:
        """
        解析原始配置，填充默认值
        """
        config = {
            'id': raw_config.get('id'),
            'name': raw_config.get('name', '').strip(),
            'url': self._normalize_url(raw_config.get('url', '')),
            'login_url': self._normalize_url(
                raw_config.get('login_url') or raw_config.get('url', '')
            ),
            
            # 登录凭证
            'username': raw_config.get('username', ''),
            'password': raw_config.get('password', ''),
            
            # 表单选择器（用于自动填写）
            'selectors': {
                'username': raw_config.get('username_selector') or '#username',
                'password': raw_config.get('password_selector') or '#password',
                'submit': raw_config.get('submit_selector') or '.btn-login, #submitBtn',
            },
            
            'status': raw_config.get('status', 'active'),
            
            # Cookie 域名白名单
            'cookie_domains': raw_config.get('cookie_domains') or [],
            
            # 自定义 Headers
            'headers': raw_config.get('headers') or {},
            
            # 数据采集配置（API 端点等）
            'api_endpoints': raw_config.get('api_endpoints') or [],
            
            # 高级选项
            'options': {
                'timeout': int(raw_config.get('timeout', 30)),
                'wait_after_login': int(raw_config.get('wait_after_login', 3)),
                'max_retries': int(raw_config.get('max_retries', 3))
            }
        }
        
        return config

    def validate(self, config: dict) -> tuple[bool, list[str]]:
        """校验配置是否有效"""
        errors = []
        
        if not config.get('name'):
            errors.append('商家名称不能为空')
        
        if not config.get('url'):
            errors.append('访问地址不能为空')
        elif not self._is_valid_url(config['url']):
            errors.append('访问地址格式无效')
        
        return len(errors) == 0, errors

    def _normalize_url(self, url: str) -> str:
        """规范化 URL"""
        url = url.strip()
        if not url:
            return ''
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        return url.rstrip('/')

    def _is_valid_url(self, url: str) -> bool:
        """检查 URL 是否合法"""
        pattern = r'^https?://[^\s/$.?#].[^\s]*$'
        return bool(re.match(pattern, url))

    def build_api_request_config(self, config: dict, endpoint_name: str = 'default') -> Optional[dict]:
        """
        构建数据采集 API 请求配置
        
        Args:
            config: 商家配置
            endpoint_name: API 端点名称
            
        Returns:
            HTTP 请求配置或 None
        """
        endpoints = config.get('api_endpoints', [])
        endpoint = None
        
        for ep in endpoints:
            if ep.get('name') == endpoint_name:
                endpoint = ep
                break
        
        if not endpoint and endpoints:
            endpoint = endpoints[0]
        
        if not endpoint:
            return None
        
        base_url = config['url'].rstrip('/')
        request_path = endpoint.get('path', '')
        
        return {
            'method': (endpoint.get('method', 'GET')).upper(),
            'url': f"{base_url}{request_path}" if request_path.startswith('/') else f"{base_url}/{request_path}",
            'headers': {**config.get('headers', {}), **endpoint.get('headers', {})},
            'params': endpoint.get('params', {}),
            'field_mapping': endpoint.get('field_mapping', {}),
            'pagination': endpoint.get('pagination', {})
        }
