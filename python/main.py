#!/usr/bin/env python3
"""
QingFlow 清流 - Python 后端引擎入口
JSON-RPC 消息循环，处理来自 Electron 主进程的请求
"""

import sys
import json
import os
import time
import traceback
import threading
import logging
import asyncio
from typing import Any, Callable, Optional

# 将 python 目录加入 sys.path，确保模块可以正常导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if os.environ.get('PYTHON_DEBUG') == '1':
    try:
        import pydevd_pycharm

        debug_host = os.environ.get('PYTHON_DEBUG_HOST', '127.0.0.1')
        debug_port = int(os.environ.get('PYTHON_DEBUG_PORT', '5678'))
        pydevd_pycharm.settrace(
            debug_host,
            port=debug_port,
            stdout_to_server=False,
            stderr_to_server=False,
            suspend=False,
        )
    except Exception as e:
        print(f"[PythonDebug] Failed to attach debugger: {e}", file=sys.stderr)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('finance-tools')


class JsonRpcServer:
    """JSON-RPC 2.0 服务器，通过 stdin/stdout 与 Electron 通信"""

    def __init__(self):
        self.handlers: dict = {}
        self.event_handlers: dict = {}
        self.request_id = 0
        self._lock = threading.Lock()

        # 运行中的任务线程
        self._running_threads: dict[str, threading.Thread] = {}
        # 已取消的任务集合
        self._cancelled_merchants: set[str] = set()

        # 注册所有处理器
        self._register_handlers()

    def _register_handlers(self):
        """注册 RPC 方法处理器"""
        from engine.config_parser import ConfigParser
        from engine.login_engine import LoginEngine
        from engine.credential_manager import CredentialManager
        from engine.data_collector import DataCollector
        from engine.curl_parser import CurlParser
        from engine.browser_automation import BrowserAutomationEngine
        from db.repositories import (
            MerchantRepository,
            DataRepository,
            TaskRepository,
            TaskRunRepository,
            DashboardRepository,
        )

        # 初始化组件
        # 数据库路径：优先使用环境变量 FINANCE_TOOLS_DB（Electron 启动时设置）
        # 打包后指向 userData 目录（重装不丢失），开发模式回退到 shared/db/
        _env_db = os.environ.get('FINANCE_TOOLS_DB')
        if _env_db:
            db_path = _env_db
        else:
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'shared', 'db', 'finance_tools.db')
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        self.merchant_repo = MerchantRepository(db_path)
        self.data_repo = DataRepository(db_path)
        self.task_repo = TaskRepository(db_path)
        self.task_run_repo = TaskRunRepository(db_path)
        self.dashboard_repo = DashboardRepository(db_path)
        self.credential_mgr = CredentialManager(db_path)
        self.config_parser = ConfigParser()
        self.curl_parser = CurlParser()
        self.data_collector = DataCollector(self.credential_mgr, self.data_repo)
        self.login_engine = LoginEngine(
            self.merchant_repo,
            self.credential_mgr,
            event_callback=self.emit_event
        )
        self.browser_engine = BrowserAutomationEngine(
            self.merchant_repo,
            self.credential_mgr,
            event_callback=self.emit_event
        )

        # 注册商家相关方法
        self.register('merchant.list', self.handle_merchant_list)
        self.register('merchant.create', self.handle_merchant_create)
        self.register('merchant.update', self.handle_merchant_update)
        self.register('merchant.delete', self.handle_merchant_delete)
        self.register('merchant.testLogin', self.handle_test_login)

        # 注册任务方法
        self.register('task.start', self.handle_task_start)
        self.register('task.stop', self.handle_task_stop)
        self.register('task.startAll', self.handle_task_start_all)
        self.register('task.stopAll', self.handle_task_stop_all)

        # 注册任务配置方法
        self.register('taskConfig.list', self.handle_task_config_list)
        self.register('taskConfig.listByMerchant', self.handle_task_config_list_by_merchant)
        self.register('taskConfig.create', self.handle_task_config_create)
        self.register('taskConfig.update', self.handle_task_config_update)
        self.register('taskConfig.delete', self.handle_task_config_delete)
        self.register('taskConfig.execute', self.handle_task_config_execute)
        self.register('taskConfig.parseCurl', self.handle_parse_curl)

        # 注册数据方法
        self.register('data.list', self.handle_data_list)
        self.register('data.export', self.handle_data_export)
        self.register('data.delete', self.handle_data_delete)

        # 注册仪表盘方法
        self.register('dashboard.summary', self.handle_dashboard_summary)

        logger.info("RPC handlers registered")

    def register(self, method: str, handler: Callable):
        """注册一个 RPC 方法"""
        self.handlers[method] = handler

    def emit_event(self, event: str, data: Any = None):
        """发送事件通知到 Electron"""
        message = json.dumps({
            'jsonrpc': '2.0',
            'event': event,
            'data': data
        }, ensure_ascii=False) + '\n'
        sys.stdout.write(message)
        sys.stdout.flush()

    def send_response(self, request_id: int, result: Any = None, error: dict = None):
        """发送 RPC 响应"""
        response = {
            'jsonrpc': '2.0',
            'id': request_id
        }
        if error:
            response['error'] = error
        else:
            response['result'] = result

        sys.stdout.write(json.dumps(response, ensure_ascii=False) + '\n')
        sys.stdout.flush()

    def handle_request(self, request: dict):
        """处理单个 RPC 请求"""
        try:
            method = request.get('method')
            params = request.get('params', {})
            request_id = request.get('id', 0)

            if not method:
                self.send_response(request_id, error={
                    'code': -32600,
                    'message': 'Invalid Request: missing method'
                })
                return

            if method == 'system.exit':
                logger.info("Received exit command")
                sys.exit(0)

            if method not in self.handlers:
                self.send_response(request_id, error={
                    'code': -32601,
                    'message': f'Method not found: {method}'
                })
                return

            handler = self.handlers[method]
            result = handler(params)

            # 如果是协程，需要等待结果
            if hasattr(result, '__await__'):
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # 如果已有事件循环在运行，创建新的线程执行
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(asyncio.run, result)
                            result = future.result(timeout=300)
                    else:
                        result = loop.run_until_complete(result)
                except RuntimeError:
                    result = asyncio.run(result)

            self.send_response(request_id, result=result)

        except Exception as e:
            logger.error(f"Error handling request: {e}")
            logger.error(traceback.format_exc())
            self.send_response(
                request.get('id', 0),
                error={'code': -32603, 'message': f'Internal error: {str(e)}'}
            )

    def run(self):
        """启动消息循环，从 stdin 读取请求"""
        logger.info("Python backend started, waiting for requests...")
        sys.stderr.write("[Finance-Tools] Python engine ready\n")
        sys.stderr.flush()

        buffer = ''
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    logger.info("stdin closed, exiting...")
                    break

                line = line.strip()
                if not line:
                    continue

                request = json.loads(line)
                self.handle_request(request)

            except json.JSONDecodeError as e:
                logger.error(f"JSON parse error: {e}, input: {line[:100]}")
            except Exception as e:
                logger.error(f"Error processing input: {e}")
                logger.error(traceback.format_exc())

    # ==================== 商家相关处理器 ====================

    def handle_merchant_list(self, params: dict) -> list:
        return self.merchant_repo.list_all()

    def handle_merchant_create(self, params: dict) -> dict:
        merchant = self.merchant_repo.create(params)
        return merchant

    def handle_merchant_update(self, params: dict) -> bool:
        id_ = params.pop('id', None)
        return self.merchant_repo.update(id_, params)

    def handle_merchant_delete(self, params: dict) -> bool:
        id_ = params.get('id')
        return self.merchant_repo.delete(id_)

    async def handle_test_login(self, params: dict) -> dict:
        id_ = params.get('id')
        success, message = await self.login_engine.test_login(id_)
        return {'success': success, 'message': message}

    # ==================== 任务相关处理器 ====================

    def handle_task_start(self, params: dict) -> dict:
        merchant_id = params.get('merchantId')
        if not merchant_id:
            return {'success': False, 'message': '缺少商家ID'}
        # 清除取消标志（重新启动）
        self._cancelled_merchants.discard(merchant_id)
        # 在后台线程执行，立即返回
        t = threading.Thread(target=self._run_collection_sync, args=(merchant_id,), daemon=True)
        t.start()
        self._running_threads[merchant_id] = t
        logger.info(f"Task started for merchant {merchant_id}")
        return {'success': True, 'message': '任务已启动'}

    def handle_task_stop(self, params: dict) -> dict:
        merchant_id = params.get('merchantId')
        # 设置取消标志
        self._cancelled_merchants.add(merchant_id)
        logger.info(f"Task stop requested for merchant {merchant_id}")

        # 清理线程引用
        self._running_threads.pop(merchant_id, None)

        self.emit_event('task:progress', {
            'merchantId': merchant_id,
            'status': 'error',
            'progress': 0,
            'message': '用户取消了任务'
        })
        return {'success': True, 'message': '任务已停止请求已发送'}

    def handle_task_start_all(self, params: dict) -> dict:
        merchants = self.merchant_repo.list_active()
        if not merchants:
            return {'success': False, 'message': '没有活跃的商家'}
        for merchant in merchants:
            mid = merchant['id']
            self._cancelled_merchants.discard(mid)
            t = threading.Thread(target=self._run_collection_sync, args=(mid,), daemon=True)
            t.start()
            self._running_threads[mid] = t
        return {'success': True, 'message': f'已启动 {len(merchants)} 个采集任务'}

    def handle_task_stop_all(self, params: dict) -> dict:
        # 取消所有运行中的任务
        for merchant_id in list(self._running_threads.keys()):
            self._cancelled_merchants.add(merchant_id)
            self.emit_event('task:progress', {
                'merchantId': merchant_id,
                'status': 'error',
                'progress': 0,
                'message': '用户取消了所有任务'
            })

        # 清空
        self._running_threads.clear()
        logger.info("All tasks stop requested")
        return {'success': True, 'message': '已发送停止所有任务的请求'}

    # ==================== 数据相关处理器 ====================

    def handle_data_list(self, params: dict) -> dict:
        page = params.get('page', 1)
        page_size = params.get('pageSize', 15)
        records, total = self.data_repo.list(params, page, page_size)
        return {'records': records, 'total': total}

    def handle_data_export(self, params: dict) -> str:
        merchant_id = params.get('merchantId')
        ids = params.get('ids')
        export_path = self.data_repo.export_to_excel(merchant_id, ids=ids)
        return export_path

    def handle_data_delete(self, params: dict) -> bool:
        id_ = params.get('id')
        return self.data_repo.delete(id_)

    # ==================== 仪表盘相关处理器 ====================

    def handle_dashboard_summary(self, params: dict) -> dict:
        return self.dashboard_repo.summary()

    # ==================== 任务配置相关处理器 ====================

    def handle_task_config_list(self, params: dict) -> list:
        return self.task_repo.list_all()

    def handle_task_config_list_by_merchant(self, params: dict) -> list:
        merchant_id = params.get('merchantId', '')
        return self.task_repo.list_by_merchant(merchant_id)

    def handle_task_config_create(self, params: dict) -> dict:
        return self.task_repo.create(params)

    def handle_task_config_update(self, params: dict) -> bool:
        id_ = params.pop('id', None)
        logger.info(f"Task update {id_}: url={params.get('url')}, body={str(params.get('body', ''))[:200]}")
        return self.task_repo.update(id_, params)

    def handle_task_config_delete(self, params: dict) -> bool:
        id_ = params.get('id')
        return self.task_repo.delete(id_)

    def handle_parse_curl(self, params: dict) -> dict:
        """解析 CURL 命令，返回结构化配置"""
        curl_command = params.get('curl', '')
        result = self.curl_parser.parse(curl_command)
        return result

    async def handle_task_config_execute(self, params: dict) -> dict:
        """执行指定任务"""
        task_id = params.get('taskId')
        if not task_id:
            return {'success': False, 'message': '缺少任务ID'}

        task = self.task_repo.get_by_id(task_id)
        if not task:
            return {'success': False, 'message': f'任务不存在: {task_id}'}

        merchant_id = task.get('merchant_id', '')

        # 清除取消标志
        self._cancelled_merchants.discard(merchant_id)

        # 在后台线程执行
        t = threading.Thread(target=self._run_task_sync, args=(task_id,), daemon=True)
        t.start()
        self._running_threads[task_id] = t

        logger.info(f"Task execution started: {task_id}")
        return {'success': True, 'message': '任务已开始执行'}

    # ==================== 内部方法 ====================

    def _run_collection_sync(self, merchant_id: str):
        """同步包装：在后台线程中执行数据采集流程"""
        try:
            asyncio.run(self._run_collection(merchant_id))
        except Exception as e:
            logger.error(f"Collection thread error for {merchant_id}: {e}")
            logger.error(traceback.format_exc())
            if not self._is_cancelled(merchant_id):
                self.emit_event('task:progress', {
                    'merchantId': merchant_id,
                    'status': 'error',
                    'progress': 0,
                    'message': f'采集异常: {str(e)}'
                })
        finally:
            # 清理线程和取消标志
            self._running_threads.pop(merchant_id, None)
            self._cancelled_merchants.discard(merchant_id)

    def _run_task_sync(self, task_id: str):
        """同步包装：在后台线程中执行单个任务"""
        try:
            asyncio.run(self._run_single_task(task_id))
        except Exception as e:
            logger.error(f"Task thread error for {task_id}: {e}")
            logger.error(traceback.format_exc())
            task = self.task_repo.get_by_id(task_id)
            if task:
                self.emit_event('task:progress', {
                    'taskId': task_id,
                    'merchantId': task.get('merchant_id', ''),
                    'status': 'error',
                    'progress': 0,
                    'message': f'任务执行异常: {str(e)}'
                })
                self.task_repo.update(task_id, {'status': 'error', 'last_result': str(e)[:200]})
        finally:
            self._running_threads.pop(task_id, None)
            self._cancelled_merchants.discard(task_id)

    def _is_cancelled(self, merchant_id: str) -> bool:
        """检查任务是否已被用户取消"""
        return merchant_id in self._cancelled_merchants

    def _find_page_object(self, obj: any, key: str) -> Optional[dict]:
        """返回包含指定分页字段的父字典，支持点号路径如 data.page.pageIndex"""
        import re
        if '.' in key:
            # 点号路径：逐层深入到父对象
            parts = re.split(r'\.|\[|\]', key)
            parts = [p for p in parts if p]
            current = obj
            for part in parts[:-1]:  # 到倒数第二层
                if isinstance(current, dict):
                    current = current.get(part)
                    if current is None:
                        return None
                else:
                    return None
            return current if isinstance(current, dict) else None
        else:
            # 简单字段名：递归搜索
            if isinstance(obj, dict):
                if key in obj:
                    return obj
                for v in obj.values():
                    if isinstance(v, dict):
                        result = self._find_page_object(v, key)
                        if result:
                            return result
                    elif isinstance(v, list):
                        for item in v:
                            if isinstance(item, dict):
                                result = self._find_page_object(item, key)
                                if result:
                                    return result
            elif isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict):
                        result = self._find_page_object(item, key)
                        if result:
                            return result
            return None

    async def _save_response_data(self, task_id: str, merchant_id: str, task: dict,
                                  json_data: any, extract_config: dict) -> int:
        """
        从响应中提取数据，按字段映射合并为单条 JSON 记录保存
        一次任务执行 = 一条 collected_data 记录，raw_data 是字段映射后的结构化 JSON
        
        Returns:
            保存的记录数（始终为1）
        """
        merchant = self.merchant_repo.get_by_id(merchant_id)
        merchant_name = merchant.get('name', '') if merchant else ''

        if extract_config:
            data_records = self.curl_parser.extract_data(json_data, extract_config)
        else:
            if isinstance(json_data, list):
                data_records = json_data
            elif isinstance(json_data, dict):
                data_records = [json_data]
            else:
                data_records = [{'raw': str(json_data)}]

        logger.info(
            f"[SaveData {task_id}] 提取到 {len(data_records) if isinstance(data_records, list) else 1} 条原始记录")

        # 统一格式：raw_data = { _count: N, _records: [ {字段: 值}, ... ] }
        # 单条数据也包装为 _records 数组，保持格式一致
        if len(data_records) == 0:
            final_raw_data = {'_count': 0, '_records': []}
        else:
            final_raw_data = {
                '_count': len(data_records),
                '_records': [item if isinstance(item, dict) else {'value': item} for item in data_records]
            }

        record_summary = f"共{final_raw_data['_count']}条数据"

        # 打印第一条数据的字段摘要（用于日志可读性）
        if final_raw_data['_records'] and isinstance(final_raw_data['_records'][0], dict):
            first = {k: v for k, v in final_raw_data['_records'][0].items() if not k.startswith('_')}
            if first:
                sample = ', '.join(f'{k}={str(v)[:30]}' for k, v in list(first.items())[:3])
                record_summary += f' (首条: {sample})'

        logger.info(f"[SaveData {task_id}] 最终保存: {record_summary}")

        # 发送到前端日志
        self.emit_event('task:log', {
            'taskId': task_id, 'merchantId': merchant_id,
            'log': {
                'level': 'info',
                'message': f'💾 数据已保存: {record_summary}',
                'timestamp': time.time()
            }
        })

        # 写入数据库：每次执行只产生一条记录
        self.data_repo.create({
            'task_id': task_id,
            'merchant_id': merchant_id,
            'merchant_name': merchant_name,
            'raw_data': final_raw_data,
            'collected_at': int(time.time())
        })

        return 1

    async def _run_paginated_collection(self, client, base_request_config: dict,
                                        task_id: str, merchant_id: str, task: dict,
                                        cookie_header: str, first_page_data: any) -> int:
        """分页循环：基于接口返回的分页信息自动翻页，所有页数据合并为一条记录保存"""
        import httpx

        pagination_config = task.get('pagination')
        if isinstance(pagination_config, str):
            try:
                pagination_config = json.loads(pagination_config)
            except:
                pagination_config = {}

        extract_config = task.get('response_extract', {})
        if isinstance(extract_config, str):
            try:
                extract_config = json.loads(extract_config)
            except:
                extract_config = {}

        # 分页参数名
        page_field = pagination_config.get('page_field') or 'pageNum'
        size_field = pagination_config.get('size_field') or 'pageSize'

        # 从原始请求体读取实际 pageSize（尊重 curl 中的值，不覆盖）
        body_for_read = base_request_config.get('json')
        if body_for_read and isinstance(body_for_read, dict):
            actual_page_size = self.curl_parser._find_first_value(body_for_read, size_field)
            if actual_page_size is not None:
                page_size = int(actual_page_size)
            else:
                page_size = 20
        else:
            page_size = 20

        logger.info(
            f"[Paginate {task_id}] 配置: page_field={page_field}, size_field={size_field}, 实际pageSize={page_size}（来自请求体）")
        logger.info(f"[Paginate {task_id}] first_page_data type={type(first_page_data).__name__}")

        # 累积所有页的原始数据
        all_extracted_records: list[dict] = []

        # 首页数据提取（不保存，先累积）
        first_page_records = self._extract_records_from_response(first_page_data, extract_config)
        all_extracted_records.extend(first_page_records)
        logger.info(f"[Paginate {task_id}] 首页提取 {len(first_page_records)} 条，累计 {len(all_extracted_records)} 条")

        # 实际请求的页数（首页 + 翻页数），用于最终日志
        total_pages_fetched = 1

        # ===== 从首页响应中提取分页信息 =====
        total_value = self.curl_parser.get_total_count(first_page_data, pagination_config)
        logger.info(f"[Paginate {task_id}] total_field 解析结果: total_value={total_value}")

        # 核心逻辑：根据 total_value 决定是否需要翻页、以及翻多少页
        effective_max_page = None  # 由响应决定的翻页上限

        if total_value is not None:
            if total_value <= 10:
                effective_max_page = int(total_value)
                logger.info(f"[Paginate {task_id}] 值{total_value}较小，识别为【总页数】，将翻到第{effective_max_page}页")
            else:
                estimated = -(-total_value // page_size)
                effective_max_page = estimated
                logger.info(f"[Paginate {task_id}] 值{total_value}较大，识别为【总记录数】，估算约{estimated}页")
        else:
            logger.warning(f"[Paginate {task_id}] 无法从响应中提取分页总数，按单页处理")

        # 安全硬上限
        hard_limit = min(effective_max_page + 1 if effective_max_page else 99, pagination_config.get('max_pages') or 50)

        if effective_max_page is None or effective_max_page <= 1:
            logger.info(f"[Paginate {task_id}] 无需翻页，直接保存首页数据")
        else:
            logger.info(f"[Paginate {task_id}] 开始翻页: 目标{effective_max_page}页，硬上限{hard_limit}页")

            current_page = 1
            consecutive_empty = 0
            logger.info(
                f"[Paginate {task_id}] 翻页循环初始化: current_page={current_page}, effective_max_page={effective_max_page}")

            while True:
                current_page += 1
                logger.info(f"[Paginate {task_id}] === 准备请求第{current_page}页 ===")

                if current_page > effective_max_page:
                    logger.info(f"[Paginate {task_id}] ✓ 已到达目标页数({effective_max_page})")
                    break
                if current_page > hard_limit:
                    logger.warning(f"[Paginate {task_id}] ⚠️ 达到安全硬上限({hard_limit})")
                    break
                if self._is_cancelled(task_id):
                    logger.info(f"[Paginate {task_id}] 任务已取消")
                    break

                self.emit_event('task:progress', {
                    'taskId': task_id, 'merchantId': merchant_id, 'status': 'running',
                    'progress': min(75 + int(20 * current_page / hard_limit), 95),
                    'message': f'正在请求第 {current_page}/{effective_max_page} 页 ({len(all_extracted_records)}条)...'
                })

                try:
                    import copy as _copy
                    page_config = _copy.deepcopy(base_request_config)
                    method = page_config.pop('method', 'GET')

                    _body_json = page_config.get('json')

                    if _body_json and isinstance(_body_json, dict):
                        is_dotted = '.' in page_field

                        if is_dotted:
                            old_val = self.curl_parser._get_value_by_path(_body_json, page_field)
                            self.curl_parser._set_value_by_path(_body_json, page_field, current_page)
                            new_val = self.curl_parser._get_value_by_path(_body_json, page_field)
                            logger.info(
                                f"[Paginate {task_id}] 第{current_page}页 '{page_field}': {old_val} => {new_val}")
                        else:
                            old_val = self.curl_parser._find_first_value(_body_json, page_field)
                            self.curl_parser._set_nested_value_recursive(_body_json, page_field, current_page)
                            new_val = self.curl_parser._find_first_value(_body_json, page_field)
                            logger.info(
                                f"[Paginate {task_id}] 第{current_page}页 '{page_field}': {old_val} => {new_val}")

                        if size_field:
                            sz_dotted = '.' in size_field
                            if sz_dotted:
                                self.curl_parser._set_value_by_path(_body_json, size_field, page_size)
                            else:
                                self.curl_parser._set_nested_value_recursive(_body_json, size_field, page_size)

                        page_obj = self._find_page_object(_body_json, page_field)

                        self.emit_event('task:log', {
                            'taskId': task_id, 'merchantId': merchant_id,
                            'log': {
                                'level': 'debug',
                                'message': f'📄 第{current_page}页分页参数:\n{json.dumps(page_obj, ensure_ascii=False, indent=2) if page_obj else f"(未找到 {page_field})"}',
                                'timestamp': time.time()
                            }
                        })
                    else:
                        _params = dict(page_config.get('params', {}))
                        _params[page_field] = current_page
                        if size_field:
                            _params[size_field] = page_size
                        page_config['params'] = _params

                    for attempt in range(3):
                        try:
                            if method == 'GET':
                                resp = await client.get(**page_config)
                            elif method == 'POST':
                                resp = await client.post(**page_config)
                            else:
                                resp = await client.request(method, **page_config)
                            break
                        except Exception as retry_err:
                            if attempt < 2:
                                await asyncio.sleep(1.5)
                            else:
                                raise retry_err

                    if resp.status_code in (401, 403):
                        self.credential_mgr.invalidate(merchant_id)
                        raise Exception(f'认证失败 (HTTP {resp.status_code})')
                    if resp.status_code >= 400:
                        logger.warning(f'第{current_page}页 HTTP错误 {resp.status_code}')
                        break

                    page_json = resp.json()
                    logger.info(f"[Paginate {task_id}] 第{current_page}页响应: HTTP {resp.status_code}")
                    total_pages_fetched += 1

                    # 提取并累积（不逐页保存）
                    page_records = self._extract_records_from_response(page_json, extract_config)
                    all_extracted_records.extend(page_records)
                    logger.info(
                        f"[Paginate {task_id}] 第{current_page}页提取 {len(page_records)} 条，累计 {len(all_extracted_records)} 条")

                    if len(page_records) == 0:
                        consecutive_empty += 1
                        if consecutive_empty >= 2:
                            logger.info(f"[Paginate {task_id}] 连续{consecutive_empty}页无数据，停止翻页")
                            break
                    else:
                        consecutive_empty = 0

                    await asyncio.sleep(0.5)

                except httpx.TimeoutException:
                    break
                except Exception as e:
                    logger.warning(f'第{current_page}页失败: {e}')
                    self.emit_event('task:log', {
                        'taskId': task_id, 'merchantId': merchant_id,
                        'log': {'level': 'error', 'message': f'第{current_page}页请求失败: {e}',
                                'timestamp': time.time()}
                    })
                    break

        # ========== 所有页数据收集完毕，合并为一条记录保存 ==========
        saved_count = await self._save_merged_data(task_id, merchant_id, task, all_extracted_records)

        logger.info(
            f"[Paginate {task_id}] 分页完成！共请求 {total_pages_fetched} 页，解析出 {len(all_extracted_records)} 条数据并保存")
        self.emit_event('task:log', {
            'taskId': task_id, 'merchantId': merchant_id,
            'log': {
                'level': 'info',
                'message': f'📊 分页采集完成：共 {total_pages_fetched} 页，{len(all_extracted_records)} 条原始数据已合并保存',
                'timestamp': time.time()
            }
        })

        return saved_count

    def _extract_records_from_response(self, response_json: any, extract_config: dict) -> list[dict]:
        """从单页响应中提取数据列表（不保存，仅用于累积）"""
        if extract_config:
            return self.curl_parser.extract_data(response_json, extract_config)
        else:
            if isinstance(response_json, list):
                return response_json
            elif isinstance(response_json, dict):
                return [response_json]
            else:
                return [{'raw': str(response_json)}]

    async def _save_merged_data(self, task_id: str, merchant_id: str, task: dict,
                                all_records: list[dict]) -> int:
        """将所有累积的数据合并为一条 collected_data 记录（统一 _records 格式）"""
        merchant = self.merchant_repo.get_by_id(merchant_id)
        merchant_name = merchant.get('name', '') if merchant else ''

        # 统一格式：raw_data = { _count: N, _records: [ {字段: 值}, ... ] }
        final_raw_data = {
            '_count': len(all_records),
            '_records': [r if isinstance(r, dict) else {'value': r} for r in all_records]
        }

        logger.info(f"[SaveMerged {task_id}] 最终保存: 共{final_raw_data['_count']}条数据")

        self.data_repo.create({
            'task_id': task_id,
            'merchant_id': merchant_id,
            'merchant_name': merchant_name,
            'raw_data': final_raw_data,
            'collected_at': int(time.time())
        })

        return 1

    async def _run_collection(self, merchant_id: str):
        """执行数据采集流程（异步）"""
        # 启动时检查是否已取消
        if self._is_cancelled(merchant_id):
            logger.info(f"Task for {merchant_id} was cancelled before start")
            return

        merchant = self.merchant_repo.get_by_id(merchant_id)
        if not merchant:
            self.emit_event('task:progress', {
                'merchantId': merchant_id,
                'status': 'error',
                'progress': 0,
                'message': '商家不存在'
            })
            return

        mid = merchant['id']

        try:
            # 1. 发送进度更新
            self.emit_event('task:progress', {
                'merchantId': mid,
                'status': 'logging_in',
                'progress': 10,
                'message': '开始登录...'
            })

            # 检查取消
            if self._is_cancelled(mid):
                return

            # 2. 执行登录
            login_result = await self.login_engine.login(mid)
            if not login_result['success']:
                raise Exception(login_result['message'])

            # 登录后检查取消
            if self._is_cancelled(mid):
                logger.info(f"Collection cancelled after login for {mid}")
                return

            # 3. 更新进度
            self.emit_event('task:progress', {
                'merchantId': mid,
                'status': 'collecting',
                'progress': 50,
                'message': '登录成功，开始采集数据...'
            })

            # 4. 数据采集
            collected_count = await self.data_collector.collect(mid)

            # 5. 完成通知
            self.emit_event('task:progress', {
                'merchantId': mid,
                'status': 'success',
                'progress': 100,
                'message': f'采集完成，共获取 {collected_count} 条数据'
            })

        except Exception as e:
            # 如果是因取消而中断的异常，不报错
            if self._is_cancelled(mid):
                logger.info(f"Collection interrupted by cancellation for {mid}")
                return
            logger.error(f"Collection failed for {mid}: {e}")
            self.emit_event('task:progress', {
                'merchantId': mid,
                'status': 'error',
                'progress': 0,
                'message': f'采集失败: {str(e)}'
            })

    async def _run_single_task(self, task_id: str):
        """执行单个任务（基于任务配置的 CURL 请求），循环每个关联商家"""
        task = self.task_repo.get_by_id(task_id)
        if not task:
            return

        merchant_ids = task.get('merchant_ids', [])
        # 兼容旧数据：如果 merchant_ids 为空但有旧的 merchant_id 字段
        if not merchant_ids and task.get('merchant_id'):
            merchant_ids = [task['merchant_id']]
        if not merchant_ids:
            logger.error(f"[Task {task_id}] 没有关联商家，跳过执行")
            self.emit_event('task:progress', {
                'taskId': task_id, 'status': 'error', 'progress': 0,
                'message': '没有关联商家'
            })
            return

        task_name = task.get('name', '')
        total_merchants = len(merchant_ids)
        success_merchant_count = 0
        total_collected_count = 0
        error_messages = []

        for idx, merchant_id in enumerate(merchant_ids):
            merchant_name = ''
            run_started_at = int(time.time())
            try:
                # 获取商家名
                m = self.merchant_repo.get_by_id(merchant_id)
                merchant_name = m.get('name', '') if m else merchant_id
                run_started_at = int(time.time())

                logger.info(
                    f"[Task {task_id}] === 商家 {idx + 1}/{total_merchants}: {merchant_name} ({merchant_id}) ===")
                self.emit_event('task:progress', {
                    'taskId': task_id, 'merchantId': merchant_id, 'status': 'running',
                    'progress': int((idx / total_merchants) * 100),
                    'message': f'[{idx + 1}/{total_merchants}] 开始执行: {merchant_name}'
                })

                count = await self._execute_for_merchant(task, task_id, merchant_id)
                run_finished_at = int(time.time())
                success_merchant_count += 1
                total_collected_count += count
                self.task_run_repo.create({
                    'task_id': task_id,
                    'task_name': task_name,
                    'merchant_id': merchant_id,
                    'merchant_name': merchant_name,
                    'status': 'success',
                    'collected_count': count,
                    'message': f'采集完成，{count}条数据',
                    'started_at': run_started_at,
                    'finished_at': run_finished_at,
                    'duration_ms': max((run_finished_at - run_started_at) * 1000, 0),
                })

                self.emit_event('task:progress', {
                    'taskId': task_id, 'merchantId': merchant_id, 'status': 'success',
                    'progress': int(((idx + 1) / total_merchants) * 100),
                    'message': f'✅ [{merchant_name}] 采集完成，{count}条数据'
                })

            except Exception as e:
                err_msg = f'❌ [{merchant_name or merchant_id}] 执行失败: {e}'
                run_finished_at = int(time.time())
                error_messages.append(err_msg)
                logger.error(f"[Task {task_id}] 商家 {merchant_id} 失败: {e}")
                logger.error(f"[Task {task_id}] 堆栈信息:\n{traceback.format_exc()}")
                self.task_run_repo.create({
                    'task_id': task_id,
                    'task_name': task_name,
                    'merchant_id': merchant_id,
                    'merchant_name': merchant_name or merchant_id,
                    'status': 'error',
                    'collected_count': 0,
                    'message': str(e),
                    'started_at': run_started_at,
                    'finished_at': run_finished_at,
                    'duration_ms': max((run_finished_at - run_started_at) * 1000, 0),
                })
                self.emit_event('task:progress', {
                    'taskId': task_id, 'merchantId': merchant_id, 'status': 'error',
                    'message': err_msg
                })
                # 单个商家失败不中断其他商家，继续下一个
                continue

        # 全部完成后的汇总状态
        final_status = 'success' if not error_messages else ('error' if success_merchant_count == 0 else 'success')
        result_summary = f'成功 {success_merchant_count} / 共 {total_merchants} 个商家，采集 {total_collected_count} 条数据'
        if error_messages:
            result_summary += f'（{len(error_messages)}个失败）'

        self.task_repo.update(task_id,
                              {'status': final_status, 'last_run_at': int(time.time()), 'last_result': result_summary})
        self.emit_event('task:progress', {
            'taskId': task_id, 'status': final_status, 'progress': 100,
            'message': f'📊 任务完成: {result_summary}'
        })

    async def _execute_for_merchant(self, task: dict, task_id: str, merchant_id: str) -> int:
        """为单个商家执行一次采集（返回采集到的数据条数）"""
        try:
            task_name = task.get('name', '')
            task_type = task.get('task_type', 'curl')

            # ===== 分支：浏览器自动化模式 =====
            if task_type == 'browser':
                logger.info(f"[Task {task_id}] 浏览器自动化模式执行: {task_name}")
                self.emit_event('task:progress', {
                    'taskId': task_id, 'merchantId': merchant_id, 'status': 'running',
                    'progress': 10, 'message': '🌐 启动浏览器自动化...'
                })
                # 浏览器模式内部会自行处理凭证恢复、页面操作、数据提取
                return await self.browser_engine.execute(task_id, task, merchant_id)

            # ===== 原有 CURL/HTTP 模式 =====
            # 1. 确保登录凭证有效
            cookie_header = ''
            if task.get('inject_credential', 1):
                self.emit_event('task:progress', {
                    'taskId': task_id, 'merchantId': merchant_id, 'status': 'running',
                    'progress': 20, 'message': '检查登录凭证...'
                })

                cookie_header = self.credential_mgr.get_cookie_header(merchant_id) or ''

                if not cookie_header:
                    self.emit_event('task:progress', {
                        'taskId': task_id, 'merchantId': merchant_id, 'status': 'running',
                        'progress': 25, 'message': '凭证无效，执行登录...'
                    })
                    login_result = await self.login_engine.login(merchant_id)
                    if not login_result['success']:
                        raise Exception(f'登录失败: {login_result["message"]}')
                    cookie_header = self.credential_mgr.get_cookie_header(merchant_id) or ''

            # 检查取消
            if self._is_cancelled(task_id):
                raise Exception('用户取消了任务')

            # 2. 构建请求
            self.emit_event('task:progress', {
                'taskId': task_id, 'merchantId': merchant_id, 'status': 'running',
                'progress': 40, 'message': '构建请求配置...'
            })

            request_config = self.curl_parser.build_request_config(task, cookie_header)

            if not request_config.get('url'):
                raise Exception('任务配置缺少请求 URL')

            # 打印实际请求配置到日志
            log_url = request_config.get('url', '')
            log_params = request_config.get('params', {})
            log_method = request_config.get('method', 'GET')
            log_body = request_config.get('json', request_config.get('data', ''))
            logger.info(f"[Task {task_id}] === 首次请求 === method={log_method}, url={log_url}")
            if isinstance(log_body, dict):
                logger.info(f"[Task {task_id}] 首次请求 body={json.dumps(log_body, ensure_ascii=False)[:500]}")

            self.emit_event('task:log', {
                'taskId': task_id,
                'merchantId': merchant_id,
                'log': {
                    'level': 'debug',
                    'message': f'请求配置: {log_method} {log_url}\nParams: {json.dumps(log_params, ensure_ascii=False) if log_params else "无"}\nBody: {json.dumps(log_body, ensure_ascii=False) if isinstance(log_body, (dict, list)) else str(log_body)[:500] if log_body else "无"}',
                    'timestamp': time.time()
                }
            })

            # 3. 执行请求
            import httpx
            collected_count = 0
            async with httpx.AsyncClient(timeout=30, follow_redirects=True, verify=False) as client:
                import copy

                # 获取分页配置（在首次请求前读取，用于统一 pageSize）
                pagination_config = task.get('pagination')
                if isinstance(pagination_config, str):
                    try:
                        pagination_config = json.loads(pagination_config)
                    except (json.JSONDecodeError, TypeError):
                        pagination_config = {}

                # 如果启用分页，确保首次请求 pageIndex 从第1页开始
                if pagination_config and pagination_config.get('enabled'):
                    page_field = pagination_config.get('page_field') or 'pageIndex'
                    body_json = request_config.get('json')
                    if body_json and isinstance(body_json, dict):
                        old_page = self.curl_parser._find_first_value(body_json, page_field)
                        if old_page is not None and old_page != 1:
                            self.curl_parser._set_nested_value_recursive(body_json, page_field, 1)
                            logger.info(f"[Task {task_id}] 首次请求前统一 {page_field}: {old_page} => 1")

                # 保存一份干净的基础请求配置供分页复用（在 pop 之前）
                base_for_pagination = copy.deepcopy(request_config)
                method = request_config.pop('method', 'GET')

                for attempt in range(3):
                    try:
                        if method == 'GET':
                            response = await client.get(**request_config)
                        elif method == 'POST':
                            response = await client.post(**request_config)
                        else:
                            response = await client.request(method, **request_config)
                        break
                    except httpx.TimeoutException:
                        if attempt < 2:
                            await asyncio.sleep(2)
                        else:
                            raise Exception('请求超时，已重试3次')

                if response.status_code in (401, 403):
                    self.credential_mgr.invalidate(merchant_id)
                    raise Exception(f'认证失败 (HTTP {response.status_code})，需要重新登录')

                if response.status_code >= 400:
                    raise Exception(f'HTTP 错误 {response.status_code}: {response.text[:200]}')

                # 打印响应内容
                self.emit_event('task:log', {
                    'taskId': task_id,
                    'merchantId': merchant_id,
                    'log': {
                        'level': 'info',
                        'message': f'HTTP {response.status_code} | {len(response.text)} bytes | Content-Type: {response.headers.get("content-type", "unknown")}',
                        'timestamp': time.time()
                    }
                })

                # 尝试打印格式化的 JSON 响应，或截断的文本响应
                try:
                    resp_json = response.json()
                    resp_preview = json.dumps(resp_json, ensure_ascii=False, indent=2)
                    # 限制日志长度，避免超大响应卡住前端
                    if len(resp_preview) > 5000:
                        resp_preview = resp_preview[:5000] + f'\n... (截断，共 {len(resp_preview)} 字符)'
                    self.emit_event('task:log', {
                        'taskId': task_id,
                        'merchantId': merchant_id,
                        'log': {
                            'level': 'info',
                            'message': f'响应内容:\n{resp_preview}',
                            'timestamp': time.time()
                        }
                    })
                except Exception:
                    text_preview = response.text[:3000]
                    if len(response.text) > 3000:
                        text_preview += f'\n... (截断，共 {len(response.text)} 字符)'
                    self.emit_event('task:log', {
                        'taskId': task_id,
                        'merchantId': merchant_id,
                        'log': {
                            'level': 'info',
                            'message': f'响应内容(文本):\n{text_preview}',
                            'timestamp': time.time()
                        }
                    })

                # 4. 解析响应数据
                self.emit_event('task:progress', {
                    'taskId': task_id,
                    'merchantId': merchant_id,
                    'status': 'running',
                    'progress': 75,
                    'message': '解析响应数据...'
                })

                try:
                    json_data = response.json()
                except Exception:
                    json_data = {'raw_content': response.text[:5000]}

                # 获取提取配置
                extract_config = task.get('response_extract')
                if isinstance(extract_config, str):
                    try:
                        extract_config = json.loads(extract_config)
                    except (json.JSONDecodeError, TypeError):
                        extract_config = {}

                # pagination_config 已在首次请求前解析，此处复用

                logger.info(f"[Task {task_id}] pagination_config: {pagination_config}")
                logger.info(f"[Task {task_id}] extract_config: {extract_config}")

                # 如果有分页配置，进入分页循环
                if pagination_config and pagination_config.get('enabled'):
                    logger.info(f"[Task {task_id}] 分页模式已启用，进入分页循环")
                    collected_count += await self._run_paginated_collection(
                        client, base_for_pagination, task_id, merchant_id,
                        task, cookie_header, json_data
                    )
                else:
                    logger.info(f"[Task {task_id}] 单页模式，直接保存数据")
                    # 单页：提取数据并保存
                    collected_count += await self._save_response_data(
                        task_id, merchant_id, task, json_data, extract_config
                    )

            # 返回采集到的数据条数
            return collected_count

        except Exception as e:
            if self._is_cancelled(task_id):
                raise Exception('用户取消了任务')

            logger.error(f"Task execution failed for {task_id} (merchant {merchant_id}): {e}")
            raise e


def main():
    server = JsonRpcServer()
    server.run()


if __name__ == '__main__':
    main()
