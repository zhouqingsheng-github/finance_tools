"""
数据采集器
利用保存的 Cookie 凭证，通过 HTTP 请求获取商家数据
"""

import asyncio
import json
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger('finance-tools.collector')

# 请求重试配置
MAX_RETRIES = 3
RETRY_DELAY = 2  # 秒
REQUEST_TIMEOUT = 30  # 秒


class DataCollector:
    """数据采集器"""
    
    def __init__(self, credential_manager, data_repo):
        self.credential_mgr = credential_manager
        self.data_repo = data_repo
    
    async def collect(self, merchant_id: str) -> int:
        """
        为指定商家执行数据采集
        
        Args:
            merchant_id: 商家 ID
            
        Returns:
            采集到的数据条数
        """
        try:
            from engine.config_parser import ConfigParser
            from db.repositories import MerchantRepository
            
            config_parser = ConfigParser()
            
            # 获取商家配置
            merchant_repo = MerchantRepository(self.data_repo.db_path)
            raw_config = merchant_repo.get_by_id(merchant_id)
            
            if not raw_config:
                raise Exception(f'商家配置不存在: {merchant_id}')
            
            config = config_parser.parse(raw_config)
            
            # 获取凭证（Cookie）
            cookie_header = self.credential_mgr.get_cookie_header(merchant_id)
            if not cookie_header:
                raise Exception('无法获取有效的登录凭证，请先重新登录')
            
            # 构建请求配置
            api_config = config_parser.build_api_request_config(config)
            
            if not api_config or not api_config.get('url'):
                # 如果没有配置 API 端点，使用默认的商家首页获取数据
                logger.info(f"No API endpoint configured for {merchant_id}, fetching default page")
                return await self._fetch_default_page(config, cookie_header, merchant_id)
            
            return await self._execute_api_request(api_config, config, cookie_header, merchant_id)
            
        except Exception as e:
            logger.error(f"Data collection failed for {merchant_id}: {e}")
            raise

    async def _execute_api_request(
        self, 
        api_config: dict,
        config: dict,
        cookie_header: str,
        merchant_id: str
    ) -> int:
        """执行 API 数据请求"""
        
        method = api_config.get('method', 'GET').upper()
        url = api_config.get('url')
        headers = {
            'Cookie': cookie_header,
            'User-Agent': config.get('headers', {}).get('User-Agent') or 
                          'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            **api_config.get('headers', {}),
            'Accept': 'application/json, text/html, */*'
        }
        params = api_config.get('params', {})
        field_mapping = api_config.get('field_mapping', {})
        pagination = api_config.get('pagination', {})
        
        total_collected = 0
        
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            for attempt in range(MAX_RETRIES + 1):
                try:
                    if method == 'GET':
                        response = await client.get(url, headers=headers, params=params)
                    elif method == 'POST':
                        response = await client.post(url, headers=headers, json=params)
                    else:
                        response = await client.request(method, url, headers=headers, json=params)
                    
                    # 检查响应状态
                    if response.status_code == 401 or response.status_code == 403:
                        logger.warning(f"Auth failed (status {response.status_code}), invalidating credentials")
                        self.credential_mgr.invalidate(merchant_id)
                        raise Exception(f'认证失败 (HTTP {response.status_code})，可能需要重新登录')
                    
                    if response.status_code >= 400:
                        raise Exception(f'HTTP 错误 {response.status_code}: {response.text[:200]}')
                    
                    # 解析响应数据
                    parsed_data = self._parse_response(response, field_mapping)
                    
                    # 分页处理
                    if pagination:
                        page_data = await self._handle_pagination(
                            client, url, headers, method, params,
                            pagination, parsed_data, field_mapping
                        )
                        parsed_data.extend(page_data)
                    
                    # 写入数据库
                    count = self._save_data(parsed_data, merchant_id, config['name'])
                    total_collected += count
                    
                    logger.info(f"Collected {count} records from {url}")
                    break
                    
                except httpx.TimeoutException:
                    if attempt < MAX_RETRIES:
                        wait = RETRY_DELAY * (attempt + 1)
                        logger.warning(f"Request timeout, retrying in {wait}s... (attempt {attempt + 1})")
                        await asyncio.sleep(wait)
                    else:
                        raise Exception('请求超时，已达到最大重试次数')
                
                except Exception as e:
                    if attempt < MAX_RETRIES and isinstance(e, (httpx.NetworkError,)):
                        wait = RETRY_DELAY * (attempt + 1)
                        logger.warning(f"Network error: {e}, retrying in {wait}s...")
                        await asyncio.sleep(wait)
                    else:
                        raise
        
        return total_collected

    async def _fetch_default_page(self, config: dict, cookie_header: str, merchant_id: str) -> int:
        """当没有配置 API 端点时，抓取默认页面数据"""
        base_url = config['url']
        
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(base_url, headers={
                'Cookie': cookie_header,
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            })
            
            if response.status_code != 200:
                raise Exception(f'页面访问失败: HTTP {response.status_code}')
            
            # 尝试解析 JSON 数据
            try:
                data = response.json()
            except Exception:
                # 非 JSON 响应，存储原始 HTML 摘要
                data = {'html_content': response.text[:5000], 'content_type': 'html'}
            
            return self._save_data([data], merchant_id, config['name'], 'page')

    def _parse_response(self, response, field_mapping: dict) -> list[dict]:
        """
        解析 API 响应数据
        
        Args:
            response: httpx Response 对象
            field_mapping: 字段映射配置
            
        Returns:
            解析后的数据列表
        """
        try:
            json_data = response.json()
            
            # 处理常见的 API 响应格式
            # 格式1: { data: [...] }
            if isinstance(json_data, dict):
                if 'data' in json_data and isinstance(json_data['data'], list):
                    items = json_data['data']
                elif 'list' in json_data and isinstance(json_data['list'], list):
                    items = json_data['list']
                elif 'records' in json_data and isinstance(json_data['records'], list):
                    items = json_data['records']
                elif 'items' in json_data and isinstance(json_data['items'], list):
                    items = json_data['items']
                else:
                    items = [json_data]  # 单条记录
            elif isinstance(json_data, list):
                items = json_data
            else:
                items = [str(json_data)]
            
            # 应用字段映射
            if field_mapping:
                mapped_items = []
                for item in items:
                    if isinstance(item, dict):
                        mapped_item = {}
                        for target_field, source_key in field_mapping.items():
                            value = item
                            for key in source_key.split('.'):
                                value = value.get(key, {}) if isinstance(value, dict) else None
                            mapped_item[target_field] = value if value is not None else item.get(source_key)
                        mapped_items.append(mapped_item)
                    else:
                        mapped_items.append(item)
                items = mapped_items
            
            return items
            
        except Exception as e:
            logger.warning(f"Response parse warning: {e}, storing raw response")
            return [{'raw_response': response.text[:10000]}]

    async def _handle_pagination(
        self, 
        client, url, headers, method, params,
        pagination: dict, first_page_data: list, field_mapping: dict
    ) -> list[dict]:
        """
        处理分页请求
        
        Args:
            pagination: 分页配置 {page_param: 'page', size_param: 'pageSize', ...}
            
        Returns:
            额外的分页数据
        """
        all_extra_data = []
        page_param = pagination.get('page_param', 'page')
        size_param = pagination.get('size_param', 'pageSize')
        page_size = pagination.get('page_size', 20)
        max_pages = pagination.get('max_pages', 10)
        
        current_page = params.get(page_param, 1) or 1
        has_more = len(first_page_data) >= page_size
        
        while has_more and current_page < max_pages:
            current_page += 1
            page_params = {**params, page_param: current_page, size_param: page_size}
            
            try:
                if method == 'GET':
                    resp = await client.get(url, headers=headers, params=page_params)
                else:
                    resp = await client.post(url, headers=headers, json=page_params)
                
                if resp.status_code != 200:
                    break
                
                page_data = self._parse_response(resp, field_mapping)
                
                if not page_data:
                    break
                
                all_extra_data.extend(page_data)
                has_more = len(page_data) >= page_size
                
                # 限流：避免请求过快
                await asyncio.sleep(random.uniform(0.3, 1.0))
                
            except Exception as e:
                logger.warning(f"Pagination error at page {current_page}: {e}")
                break
        
        return all_extra_data

    def _save_data(
        self,
        data_list: list[dict],
        merchant_id: str,
        merchant_name: str
    ) -> int:
        """将数据写入数据库"""
        saved_count = 0
        now = int(time.time())

        for item in data_list:
            record = {
                'merchant_id': merchant_id,
                'merchant_name': merchant_name,
                'raw_data': item,
                'collected_at': now
            }
            
            try:
                self.data_repo.create(record)
                saved_count += 1
            except Exception as e:
                logger.error(f"Failed to save record: {e}")
        
        return saved_count


import random
