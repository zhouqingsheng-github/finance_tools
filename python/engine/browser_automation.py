"""
Playwright 浏览器自动化采集引擎
- 复用登录凭证（storage_state）打开已登录的浏览器上下文
- 支持操作步骤：填写输入框(fill)、点击按钮(click)、等待(wait)、下拉选择(select)、滚动(scroll)
- 支持从页面 DOM 提取表格/列表数据（CSS 选择器定位）
- 支持翻页：点击下一页按钮循环获取所有页数据
"""

import json
import logging
import time
import os
import asyncio

from playwright.async_api import async_playwright, Page, BrowserContext

logger = logging.getLogger('finance-tools.browser')


class BrowserAutomationEngine:
    """浏览器自动化采集引擎"""

    def __init__(self, merchant_repo, credential_manager, event_callback=None):
        self.merchant_repo = merchant_repo
        self.credential_mgr = credential_manager
        self.event_callback = event_callback

    def emit_event(self, event: str, data=None):
        if self.event_callback and callable(self.event_callback):
            try:
                self.event_callback(event, data)
            except Exception as e:
                logger.warning(f'[BrowserEngine] emit_event failed: {e}')

    async def execute(self, task_id: str, task: dict, merchant_id: str) -> int:
        """
        执行浏览器自动化采集任务

        Args:
            task_id: 任务ID
            task: 任务配置（包含 browser_config）
            merchant_id: 商家ID

        Returns:
            采集到的数据条数
        """
        # 解析 browser_config
        browser_config = task.get('browser_config', {})
        if isinstance(browser_config, str):
            try:
                browser_config = json.loads(browser_config)
            except:
                browser_config = {}

        target_url = browser_config.get('target_url', '')
        if not target_url:
            raise Exception('浏览器自动化模式缺少目标页面 URL')

        actions = browser_config.get('actions', [])
        wait_after_load = browser_config.get('wait_after_load', 3000)

        # ===== 解析 API 监听器列表 =====
        # 新版: api_listeners 数组；旧版: 单一 api_url（向后兼容）
        api_listeners = browser_config.get('api_listeners', [])
        if not api_listeners:
            legacy_api_url = browser_config.get('api_url', '')
            if legacy_api_url:
                # 兼容旧版：将单一 api_url 转为 capture 模式监听器
                api_listeners = [{'api_url': legacy_api_url, 'mode': 'capture'}]

        self.emit_event('task:log', {
            'taskId': task_id, 'merchantId': merchant_id,
            'log': {'level': 'info',
                    'message': f'🌐 浏览器模式启动: {target_url} | 监听器: {len(api_listeners)}个',
                    'timestamp': time.time()}
        })

        collected_count = 0
        all_records: list[dict] = []
        # 跨监听器共享变量：extract 提取的首条记录字段，供后续监听器的 $引用 使用
        extracted_vars: dict[str, any] = {}
        async with async_playwright() as p:
            launch_args = [
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-web-security',
                '--start-maximized'
            ]

            browser = None
            for channel in ['chrome', 'chromium']:
                try:
                    browser = await p.chromium.launch(
                        headless=False,
                        channel=channel,
                        args=launch_args
                    )
                    break
                except Exception as e:
                    logger.info(f"Browser channel '{channel}' not available: {e}")
                    continue

            if browser is None:
                raise Exception('未找到可用浏览器（需要安装 Chrome）')

            context = await browser.new_context(
                no_viewport=True,
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                locale='zh-CN',
                timezone_id='Asia/Shanghai'
            )

            await self._restore_credentials(context, merchant_id)
            page = await context.new_page()

            try:
                # === Step 1: 打开目标页面 ===
                self.emit_event('task:progress', {
                    'taskId': task_id, 'merchantId': merchant_id,
                    'status': 'running', 'progress': 10,
                    'message': f'正在打开目标页面: {target_url[:60]}...'
                })
                await page.goto(target_url, wait_until='domcontentloaded', timeout=60000)
                if wait_after_load > 0:
                    await asyncio.sleep(wait_after_load / 1000)
                self.emit_event('task:log', {
                    'taskId': task_id, 'merchantId': merchant_id,
                    'log': {'level': 'info', 'message': f'✅ 页面加载完成: {page.url}', 'timestamp': time.time()}
                })

                # === Step 2: 循环处理每个 操作+监听 一体化单元 ===
                total_listeners = len(api_listeners)
                for li_idx, listener in enumerate(api_listeners):
                    l_api_url = listener.get('api_url', '')
                    l_mode = listener.get('mode', 'capture')
                    l_action = listener.get('action', {}) or {}
                    l_extract_cfg = listener.get('response_extract', {})
                    l_pagination_cfg = listener.get('pagination', {})

                    # 标准化子配置
                    if isinstance(l_extract_cfg, str):
                        try:
                            l_extract_cfg = json.loads(l_extract_cfg)
                        except:
                            l_extract_cfg = {}
                    if isinstance(l_pagination_cfg, str):
                        try:
                            l_pagination_cfg = json.loads(l_pagination_cfg)
                        except:
                            l_pagination_cfg = {}

                    listener_label = l_api_url[:60] or f'监听器#{li_idx + 1}'
                    base_progress = 25 + int(65 * li_idx // max(total_listeners, 1))

                    if not l_api_url:
                        logger.warning(f'[Listener #{li_idx}] 缺少 api_url，跳过')
                        continue

                    # ---- 2a: 执行操作（action）----
                    action_type = l_action.get('type', 'immediate')
                    action_selector = l_action.get('selector', '')

                    if action_type == 'click' and action_selector:
                        self.emit_event('task:progress', {
                            'taskId': task_id, 'merchantId': merchant_id,
                            'status': 'running', 'progress': base_progress - 5,
                            'message': f'[{li_idx + 1}/{total_listeners}] 点击 [{action_selector}]...'
                        })
                        self.emit_event('task:log', {
                            'taskId': task_id, 'merchantId': merchant_id,
                            'log': {'level': 'info',
                                    'message': f'🖱️ [步骤 {li_idx + 1}] 点击 [{action_selector}] 后开始监听: {l_api_url}',
                                    'timestamp': time.time()}
                        })
                        try:
                            locator = page.locator(action_selector).first
                            await locator.wait_for(state='visible', timeout=10000)
                            await locator.scroll_into_view_if_needed()
                            await asyncio.sleep(0.3)
                            await locator.click()
                            await asyncio.sleep(1.5)  # 等待点击后请求发出
                        except Exception as e:
                            logger.warning(f'[Listener {li_idx}] click action failed: {e}')
                            self.emit_event('task:log', {
                                'taskId': task_id, 'merchantId': merchant_id,
                                'log': {'level': 'warn',
                                        'message': f'⚠️ [步骤 {li_idx + 1}] 点击失败: {e}',
                                        'timestamp': time.time()}
                            })
                    else:
                        # immediate 模式：直接开始监听
                        self.emit_event('task:log', {
                            'taskId': task_id, 'merchantId': merchant_id,
                            'log': {'level': 'info',
                                    'message': f'⚡ [步骤 {li_idx + 1}] 立即监听: {listener_label}',
                                    'timestamp': time.time()}
                        })

                    # ---- 2b: 开始监听接口 ----
                    self.emit_event('task:progress', {
                        'taskId': task_id, 'merchantId': merchant_id,
                        'status': 'running', 'progress': base_progress,
                        'message': f'🔍 [{li_idx + 1}/{total_listeners}] {l_mode.upper()}: {listener_label}'
                    })

                    if l_mode == 'extract':
                        # ----- extract 模式：拦截响应 → 提取数据（支持分页） -----
                        l_field_mapping = listener.get('field_mapping', {}) or {}
                        # 解析 $变量引用（从之前 extract 监听器的提取结果中取值）
                        resolved_fm = self._resolve_field_mapping_refs(l_field_mapping,
                                                                       extracted_vars) if l_field_mapping else None
                        records = await self._extract_from_response(
                            page, l_api_url, l_extract_cfg, l_pagination_cfg,
                            task_id, merchant_id, base_progress,
                            field_mapping=resolved_fm
                        )
                        if records:
                            all_records.extend(records)
                            self.emit_event('task:log', {
                                'taskId': task_id, 'merchantId': merchant_id,
                                'log': {'level': 'info',
                                        'message': f'📊 [{li_idx + 1}] 提取到 {len(records)} 条数据',
                                        'timestamp': time.time()}
                            })
                            # 将首条记录的提取结果存入跨监听器共享变量（供后续 $引用）
                            if records[0]:
                                extracted_vars.update(
                                    {k: v for k, v in records[0].items() if v is not None and v != ''})
                                ref_names = list(records[0].keys())
                                logger.info(f'[Listener #{li_idx}] extracted_vars updated: {ref_names}')

                    else:
                        # ----- capture 模式：拦截请求 → 生成 CURL -----
                        l_field_mapping = listener.get('field_mapping', {}) or {}
                        # 解析 $变量引用（从之前 extract 监听器的提取结果中取值）
                        resolved_mapping = self._resolve_field_mapping_refs(l_field_mapping,
                                                                            extracted_vars) if l_field_mapping else {}
                        await self._capture_api_as_curl(
                            page, l_api_url, task_id, merchant_id,
                            field_mapping=resolved_mapping if resolved_mapping else None
                        )

                collected_count = len(all_records)

                # === Step 4: 保存数据 ===
                if collected_count > 0:
                    from db.repositories import DataRepository
                    _env_db = os.environ.get('FINANCE_TOOLS_DB')
                    if _env_db:
                        db_path = _env_db
                    else:
                        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'shared', 'db',
                                               'finance_tools.db')
                    merchant = self.merchant_repo.get_by_id(merchant_id)
                    merchant_name = merchant.get('name', '') if merchant else ''
                    data_repo = DataRepository(db_path)
                    final_raw_data = {
                        '_count': collected_count,
                        '_records': [r if isinstance(r, dict) else {'value': r} for r in all_records]
                    }
                    data_repo.create({
                        'task_id': task_id,
                        'merchant_id': merchant_id,
                        'merchant_name': merchant_name,
                        'raw_data': final_raw_data,
                        'collected_at': int(time.time())
                    })
                    self.emit_event('task:log', {
                        'taskId': task_id, 'merchantId': merchant_id,
                        'log': {'level': 'info', 'message': f'💾 数据已保存: 共{collected_count}条',
                                'timestamp': time.time()}
                    })
                elif not any(l.get('mode') == 'capture' for l in api_listeners):
                    # 非 capture 模式才提示无数据
                    self.emit_event('task:log', {
                        'taskId': task_id, 'merchantId': merchant_id,
                        'log': {'level': 'warn', 'message': '⚠️ 未提取到任何数据', 'timestamp': time.time()}
                    })

                self.emit_event('task:progress', {
                    'taskId': task_id, 'merchantId': merchant_id,
                    'status': 'success', 'progress': 100,
                    'message': f'完成! 共采集 {collected_count} 条数据'
                })

            finally:
                await context.close()
                await browser.close()

        return collected_count

    async def _execute_action(self, page: Page, action: dict, task_id: str, merchant_id: str,
                              step_num: int, total_steps: int):
        """执行单个操作步骤"""
        action_type = action.get('type', '')
        selector = action.get('selector', '')
        value = action.get('value', '')

        msg_map = {
            'fill': f'📝 填写 [{selector}] = {str(value)[:50]}',
            'click': f'🖱️ 点击 [{selector}]',
            'wait': f'⏳ 等待 {value}ms',
            'select': f'📋 选择 [{selector}] → {value}',
            'scroll': f'📜 滚动到 [{selector}]',
        }
        msg = msg_map.get(action_type, f'❓ 未知操作: {action_type}')

        self.emit_event('task:log', {
            'taskId': task_id, 'merchantId': merchant_id,
            'log': {'level': 'info', 'message': f'[步骤 {step_num}/{total_steps}] {msg}', 'timestamp': time.time()}
        })

        try:
            if action_type == 'fill':
                locator = page.locator(selector).first
                await locator.wait_for(state='visible', timeout=10000)
                await locator.click()
                await locator.fill('')
                await locator.fill(value)

            elif action_type == 'click':
                locator = page.locator(selector).first
                await locator.wait_for(state='visible', timeout=10000)
                await locator.scroll_into_view_if_needed()
                await asyncio.sleep(0.3)
                await locator.click()

            elif action_type == 'wait':
                ms = int(value) if value else 1000
                await asyncio.sleep(ms / 1000)

            elif action_type == 'select':
                locator = page.locator(selector).first
                await locator.select_option(value)

            elif action_type == 'scroll':
                locator = page.locator(selector).first
                await locator.scroll_into_view_if_needed()

            else:
                logger.warning(f'Unknown action type: {action_type}')

        except Exception as e:
            logger.warning(f'[BrowserAction] {action_type} on "{selector}" failed: {e}')
            self.emit_event('task:log', {
                'taskId': task_id, 'merchantId': merchant_id,
                'log': {'level': 'warn', 'message': f'⚠️ [步骤 {step_num}] 操作失败: {e}', 'timestamp': time.time()}
            })

    @staticmethod
    def _resolve_field_mapping_refs(field_mapping: dict, extracted_vars: dict) -> dict:
        """
        解析 field_mapping 值中的 $变量引用。

        当值以 $ 开头时（如 "$partnerId"），从 extracted_vars 中查找对应变量并替换。
        支持格式：
          - $partnerId       → 直接取 extracted_vars["partnerId"]
          - ${partnerId}     → 同上（大括号可选）
          - prefix$partnerId → 保留前缀，仅替换 $ 引用部分

        Args:
            field_mapping: 原始参数映射 {参数名: 值}
            extracted_vars: 跨监听器共享的提取变量字典

        Returns:
            解析后的新 mapping 字典
        """
        import re as _re
        resolved = {}
        for key, value in field_mapping.items():
            if isinstance(value, str) and value.startswith('$'):
                # 提取引用名：去掉 $ 或 ${...} 包裹
                ref_name = value
                if ref_name.startswith('${') and ref_name.endswith('}'):
                    ref_name = ref_name[2:-1]
                elif ref_name.startswith('$'):
                    ref_name = ref_name[1:]
                # 从共享变量中取值
                if ref_name and ref_name in extracted_vars:
                    resolved[key] = extracted_vars[ref_name]
                    logger.info(f'[RefResolve] {key}: ${ref_name} → {extracted_vars[ref_name]}')
                else:
                    # 找不到引用变量，保留原值并警告
                    resolved[key] = value
                    logger.warning(f'[RefResolve] ${ref_name} not found in extracted_vars, keeping original')
            else:
                resolved[key] = value
        return resolved

    async def _apply_field_mapping(self, url: str, post_data: str,
                                   field_mapping: dict) -> tuple[str, str]:
        """
        用 field_mapping 替换 URL query 参数 和 POST body 中的同名参数值。

        Args:
            url: 原始请求 URL
            post_data: POST body 字符串（JSON 或 form）
            field_mapping: {参数名: 替换值}，如 {'startDate': '2025-04-23'}

        Returns:
            (new_url, new_post_data) 替换后的元组
        """
        if not field_mapping or not isinstance(field_mapping, dict):
            return url, post_data

        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

        # ---- 1. 替换 URL query 参数 ----
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        changed = False
        for key, new_val in field_mapping.items():
            if key in params:
                old_val = params[key]
                params[key] = [str(new_val)]
                changed = True
                logger.info(f'[FieldMapping] URL param [{key}]: {old_val} → {new_val}')
        if changed:
            flat = {}
            for k, v in params.items():
                flat[k] = v[-1] if v else ''
            new_query = urlencode(flat, doseq=True)
            url = urlunparse(parsed._replace(query=new_query))

        # ---- 2. 替换 POST body 中的参数 ----
        if post_data:
            try:
                # 尝试 JSON body
                body_obj = json.loads(post_data) if isinstance(post_data, str) else post_data
                if isinstance(body_obj, dict):
                    body_changed = False
                    for key, new_val in field_mapping.items():
                        if key in body_obj:
                            old_val = body_obj[key]
                            body_obj[key] = new_val
                            body_changed = True
                            logger.info(f'[FieldMapping] Body param [{key}]: {old_val} → {new_val}')
                    if body_changed:
                        post_data = json.dumps(body_obj, ensure_ascii=False)
                elif isinstance(body_obj, list) and len(body_obj) > 0 and isinstance(body_obj[0], dict):
                    # 数组中第一个对象（如 {"key": "startDate", "value": "xxx"} 格式）
                    item_changed = False
                    for item in body_obj:
                        if not isinstance(item, dict):
                            continue
                        for key, new_val in field_mapping.items():
                            if key in item:
                                old_val = item[key]
                                item[key] = new_val
                                item_changed = True
                                logger.info(f'[FieldMapping] Body[0] param [{key}]: {old_val} → {new_val}')
                    if item_changed:
                        post_data = json.dumps(body_obj, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError):
                # 非JSON body（form-urlencoded 等）：尝试字符串替换
                body_changed = False
                for key, new_val in field_mapping.items():
                    import re as _re
                    # 匹配 key=value 或 key=value& 模式
                    pattern = _re.compile(r'(' + _re.escape(key) + r'=)[^&]*')
                    match = pattern.search(post_data)
                    if match:
                        old_kv = match.group(0)
                        new_kv = f'{key}={str(new_val)}'
                        post_data = pattern.sub(new_kv, post_data, count=1)
                        body_changed = True
                        logger.info(f'[FieldMapping] Form param [{key}]: {old_kv} → {new_kv}')

        return url, post_data

    async def _capture_api_as_curl(self, page: Page, api_url: str,
                                   task_id: str, merchant_id: str,
                                   field_mapping: dict | None = None):
        """
        接口监听模式：打开页面 → 自动抓包 → 生成 CURL 命令

        纯抓包用途，不提取数据、不执行按钮操作。
        生成的 curl 命令通过 browser:curl-captured 事件发送给前端，
        用户可复制后创建 HTTP(CURL) 模式任务来执行。

        特殊处理：
        - 自动从浏览器上下文提取 Cookies，拼入 curl -b 参数（解决登录凭证复用）
        - 过滤无关/冗余请求头，保留业务关键头
        """
        captured_request = None

        def _build_curl(req_info: dict) -> str:
            """根据拦截到的请求信息组装完整 curl 命令"""
            try:
                parts = [f"curl -X {req_info['method']} '{req_info['url']}'"]
                # 跳过的头：浏览器自动添加的、安全策略相关的、与 cookie 冲突的
                skip_headers = {
                    'host',  # curl 自动从 URL 推导
                    'sec-ch-ua',  # 浏览器指纹，无业务意义
                    'sec-ch-ua-mobile',
                    'sec-ch-ua-platform',
                    'sec-fetch-dest',  # 安全策略头
                    'sec-fetch-mode',
                    'sec-fetch-site',
                    'upgrade-insecure-requests',
                    'accept-encoding',  # curl 自动处理压缩
                    'connection',  # curl 自动管理连接
                    'cookie',  # 单独用 -b 参数处理
                    'content-length',  # curl 自动计算
                }
                SQ = "'"
                for k, v in req_info.get('headers', {}).items():
                    if k.lower().strip() not in skip_headers and v:
                        safe_v = v.replace(SQ, SQ + '\\' + SQ)
                        parts.append(f"-H '{k}: {safe_v}'")
                # Cookies (-b 参数)
                cookies_str = req_info.get('cookies', '')
                if cookies_str:
                    parts.append(f"-b '{cookies_str}'")
                # Body (--data-raw)
                post_data = req_info.get('post_data', '')
                if post_data and req_info['method'] in ('POST', 'PUT', 'PATCH'):
                    safe_body = post_data.replace(SQ, SQ + '\\' + SQ)
                    parts.append(f"--data-raw '{safe_body}'")
                return ' \\\n  '.join(parts)
            except Exception as e:
                return f"# 生成CURL失败: {e}"

        def _format_cookies(cookie_list: list, target_domain: str = '') -> str:
            """将 Playwright cookies 列表格式化为 curl -b 可用的字符串: name=value; ..."""
            if not cookie_list:
                return ''
            pairs = []
            for c in cookie_list:
                name = c.get('name', '')
                value = c.get('value', '')
                domain = c.get('domain', '')
                if target_domain and domain:
                    if target_domain not in domain and domain.lstrip('.') not in target_domain:
                        continue
                if name and value is not None:
                    pairs.append(f"{name}={value}")
            return '; '.join(pairs)

        async def on_request(request):
            nonlocal captured_request
            try:
                url = request.url
                if captured_request or api_url not in url:
                    return
                raw_headers = dict(request.headers.items())
                post_data = ''
                try:
                    if request.method in ('POST', 'PUT', 'PATCH'):
                        post_data = (await request.post_data()) or ''
                except Exception:
                    pass
                captured_request = {
                    'url': url,
                    'method': request.method,
                    'headers': raw_headers,
                    'post_data': post_data,
                }
                logger.info(f'[Capture] 拦截到请求: {request.method} {url} '
                            f'(headers={len(raw_headers)}, body={len(post_data)} bytes)')
            except Exception as e:
                logger.warning(f'[Capture] Request handler error: {e}')

        page.on('request', on_request)

        self.emit_event('task:log', {
            'taskId': task_id, 'merchantId': merchant_id,
            'log': {'level': 'info',
                    'message': f'🔍 监听目标: {api_url}\n等待页面自动发起请求（最长30秒）...',
                    'timestamp': time.time()}
        })

        self.emit_event('task:progress', {
            'taskId': task_id, 'merchantId': merchant_id,
            'status': 'running', 'progress': 40,
            'message': '正在监听网络请求...'
        })

        try:
            max_wait = 30.0
            waited = 0
            last_progress_tick = 0
            while not captured_request and waited < max_wait:
                await asyncio.sleep(0.5)
                waited += 0.5
                tick = int(waited)
                if tick % 10 == 0 and tick > 0 and tick != last_progress_tick:
                    last_progress_tick = tick
                    self.emit_event('task:progress', {
                        'taskId': task_id, 'merchantId': merchant_id,
                        'status': 'running', 'progress': 50 + min(tick, 40),
                        'message': f'监听中... 已等待 {tick}s'
                    })

            if captured_request:
                # === 核心：从 context 提取 cookies ===
                context_cookies = ''
                try:
                    context = page.context
                    all_cookies = await context.cookies()
                    if all_cookies:
                        from urllib.parse import urlparse as _up
                        parsed_url = _up(captured_request['url'])
                        target_host = parsed_url.hostname or ''
                        context_cookies = _format_cookies(all_cookies, target_host)
                        cookie_count = len(context_cookies.split(';')) if context_cookies else 0
                        logger.info(f'[Capture] 提取 {len(all_cookies)} cookies, '
                                    f'过滤后 {cookie_count} 个有效')
                        captured_request['cookies'] = context_cookies
                except Exception as e:
                    logger.warning(f'[Capture] 提取 cookies 失败: {e}')
                    captured_request['cookies'] = ''

                # === 应用 field_mapping（替换 URL/body 中的参数值） ===
                if field_mapping:
                    orig_url = captured_request['url'][:80]
                    new_url, new_body = await self._apply_field_mapping(
                        captured_request.get('url', ''),
                        captured_request.get('post_data', ''),
                        field_mapping
                    )
                    captured_request['url'] = new_url
                    captured_request['post_data'] = new_body
                    logger.info(f'[Capture] field_mapping applied: {orig_url} → {new_url[:80]}')

                curl_cmd = _build_curl(captured_request)

                cap_url = captured_request['url'][:120]
                cap_method = captured_request['method']
                cap_hlen = len(captured_request['headers'])
                cap_blen = len(captured_request['post_data'])
                cap_clen = len(captured_request.get('cookies', ''))

                self.emit_event('task:log', {
                    'taskId': task_id, 'merchantId': merchant_id,
                    'log': {'level': 'info',
                            'message': (f'✅ 抓包成功！\n'
                                        f'📌 URL: {cap_url}\n'
                                        f'📋 方法: {cap_method} | '
                                        f'请求头: {cap_hlen}个 | '
                                        f'Body: {cap_blen} bytes | '
                                        f'Cookies: {cap_clen} chars\n\n'
                                        f'━━━ CURL 命令 ━━━\n{curl_cmd}'),
                            'timestamp': time.time()}
                })

                self.emit_event('task:progress', {
                    'taskId': task_id, 'merchantId': merchant_id,
                    'status': 'success', 'progress': 100,
                    'message': f'CURL 命令已生成！请查看日志复制使用'
                })

                self.emit_event('browser:curl-captured', {
                    'taskId': task_id,
                    'merchantId': merchant_id,
                    'page': 1,
                    'curl_command': curl_cmd,
                    'url': captured_request['url'],
                    'method': captured_request['method'],
                    'headers': captured_request['headers'],
                    'post_data': captured_request['post_data'],
                    'cookies': captured_request.get('cookies', ''),
                })
            else:
                self.emit_event('task:log', {
                    'taskId': task_id, 'merchantId': merchant_id,
                    'log': {'level': 'warn',
                            'message': f'⚠️ {max_wait}s 内未拦截到匹配 {api_url} 的请求。\n'
                                       f'可能原因：\n'
                                       f'1. 页面未自动发起该接口请求\n'
                                       f'2. api_url 不匹配（当前配置: {api_url}）\n'
                                       f'3. 需要先手动操作页面触发请求',
                            'timestamp': time.time()}
                })
                self.emit_event('task:progress', {
                    'taskId': task_id, 'merchantId': merchant_id,
                    'status': 'error', 'progress': 0,
                    'message': f'未拦截到目标接口请求'
                })
        finally:
            try:
                page.remove_listener('request', on_request)
            except Exception:
                pass

    async def _extract_from_response(self, page: Page, api_url: str,
                                     extract_config: dict, pagination_config: dict,
                                     task_id: str, merchant_id: str,
                                     base_progress: int = 30,
                                     field_mapping: dict | None = None):
        """
        extract 模式：监听 API 响应 → 提取数据（支持自动分页）

        流程：
        1. 监听页面网络请求，匹配 api_url
        2. 拦截到响应后，解析 JSON
        3. 按 response_extract 配置提取字段映射
        4. 如有分页配置，修改请求参数循环获取所有页

        Args:
            page: 已加载目标页面的 Playwright Page 对象
            api_url: 匹配的关键 URL（字符串包含）
            extract_config: {enabled, list_path, fields: [{target, source}]}
            pagination_config: {enabled, page_field, size_field, ...}
            base_progress: 基础进度百分比

        Returns:
            提取到的记录列表
        """
        all_records: list[dict] = []
        captured_responses: list[dict] = []  # 存储拦截到的响应信息

        def _parse_and_extract(response_body: str) -> list[dict]:
            """从响应体 JSON 中提取记录"""
            return self._extract_from_json(response_body, extract_config, task_id, merchant_id)

        # --- 监听响应 ---
        async def on_response(response):
            try:
                url = response.url
                if api_url not in url:
                    return
                content_type = response.headers.get('content-type', '')
                if 'json' not in content_type.lower() and 'javascript' not in content_type.lower() and 'text' not in content_type.lower():
                    return
                try:
                    body = await response.text()
                except Exception:
                    return
                if body:
                    captured_responses.append({
                        'url': url,
                        'status': response.status,
                        'body': body,
                    })
                    logger.info(f'[Extract] 拦截到响应: {url} (status={response.status}, body={len(body)} bytes)')
            except Exception as e:
                logger.warning(f'[Extract] Response handler error: {e}')

        page.on('response', on_response)

        try:
            max_wait = 30.0
            waited = 0
            last_tick = 0
            while waited < max_wait:
                await asyncio.sleep(0.5)
                waited += 0.5
                tick = int(waited)
                if tick % 10 == 0 and tick > 0 and tick != last_tick:
                    last_tick = tick
                    self.emit_event('task:progress', {
                        'taskId': task_id, 'merchantId': merchant_id,
                        'status': 'running',
                        'progress': min(base_progress + tick, 90),
                        'message': f'等待接口响应... ({tick}s)'
                    })
                if captured_responses:
                    break

            if not captured_responses:
                self.emit_event('task:log', {
                    'taskId': task_id, 'merchantId': merchant_id,
                    'log': {'level': 'warn',
                            'message': f'⚠️ {max_wait}s 内未拦截到匹配 {api_url} 的响应',
                            'timestamp': time.time()}
                })
                return []

            # 处理第一个响应
            first_resp = captured_responses[0]
            records = _parse_and_extract(first_resp['body'])
            all_records.extend(records)

            # === 分页逻辑（无 max_pages 限制，根据 total_field 自动判断结束） ===
            is_paged = pagination_config.get('enabled', False)
            if is_paged and records:
                page_field = pagination_config.get('page_field', '')
                size_field = pagination_config.get('size_field', '')
                total_field = pagination_config.get('total_field', '')
                is_total_page = pagination_config.get('is_total_page', False)

                self.emit_event('task:log', {
                    'taskId': task_id, 'merchantId': merchant_id,
                    'log': {'level': 'info',
                            'message': f'📄 首页获取 {len(records)} 条，开始分页循环...',
                            'timestamp': time.time()}
                })

                # 从首次响应中提取总数/总页数
                total_count_or_pages = 0
                if total_field:
                    try:
                        resp_data = json.loads(first_resp['body']) if isinstance(first_resp['body'], str) else \
                            first_resp['body']
                        current = resp_data
                        for seg in total_field.split('.'):
                            if isinstance(current, dict) and seg in current:
                                current = current[seg]
                            else:
                                current = None
                                break
                        if current is not None:
                            total_count_or_pages = int(current)
                    except Exception as e:
                        logger.warning(f'[Extract] 解析 total_field 失败: {e}')

                # 计算总页数
                target_total = 1
                if is_total_page and total_count_or_pages > 0:
                    target_total = total_count_or_pages
                elif total_count_or_pages > 0 and size_field:
                    # 从首次 URL 中提取 pageSize 来计算总页数
                    try:
                        first_url_parsed = self._parse_qs_from_url(first_resp['url'])
                        page_size_val = int(first_url_parsed.get(size_field, ['20'])[0])
                        target_total = (total_count_or_pages + page_size_val - 1) // page_size_val
                    except Exception:
                        target_total = max(total_count_or_pages // 20, 1)

                pg = 2
                while True:
                    # 如果有总数信息且已超过目标总页数，停止
                    if target_total > 1 and pg > target_total:
                        break

                    self.emit_event('task:progress', {
                        'taskId': task_id, 'merchantId': merchant_id,
                        'status': 'running',
                        'progress': min(base_progress + 40 + int(50 * pg / max(target_total, pg)), 95),
                        'message': f'正在翻到第 {pg}/{target_total or "?"} 页... ({len(all_records)}条)'
                    })

                    # 清空上一轮捕获
                    captured_responses.clear()

                    # 通过 JS 触发下一页请求（应用 field_mapping）
                    try:
                        first_url = first_resp['url']
                        paginated_url = first_url
                        if field_mapping:
                            paginated_url, _ = await self._apply_field_mapping(
                                first_url, '', field_mapping
                            )
                        inject_js = self._build_pagination_fetch_js(
                            paginated_url, page_field, size_field, pg
                        )
                        await page.evaluate(inject_js)
                        # 等待新响应
                        await asyncio.sleep(2)
                        paginated_wait = 15.0
                        pw = 0
                        while pw < paginated_wait and not captured_responses:
                            await asyncio.sleep(0.5)
                            pw += 0.5
                    except Exception as e:
                        logger.warning(f'[Extract] 分页请求第{pg}页失败: {e}')
                        break

                    if captured_responses:
                        pg_body = captured_responses[0]['body']
                        pg_records = _parse_and_extract(pg_body)
                        if pg_records:
                            all_records.extend(pg_records)
                            logger.info(f'[Extract] 第{pg}页提取 {len(pg_records)} 条')
                        else:
                            # 无数据说明已到末尾
                            logger.info(f'[Extract] 第{pg}页无数据，停止翻页')
                            break
                    else:
                        logger.warning(f'[Extract] 第{pg}页未收到响应')
                        break

                self.emit_event('task:log', {
                    'taskId': task_id, 'merchantId': merchant_id,
                    'log': {'level': 'info',
                            'message': f'📊 分页完成: 共 {len(all_records)} 条数据',
                            'timestamp': time.time()}
                })

            return all_records

        finally:
            try:
                page.remove_listener('response', on_response)
            except Exception:
                pass

    @staticmethod
    def _parse_qs_from_url(url: str) -> dict[str, list[str]]:
        """从 URL 中提取 query 参数（返回 list 形式，兼容 parse_qs）"""
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(url)
        return parse_qs(parsed.query, keep_blank_values=True)

    @staticmethod
    def _build_pagination_fetch_js(url: str, page_field: str, size_field: str,
                                   page_num: int) -> str:
        """生成 JS 代码：用修改后的分页参数重新 fetch 接口"""
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        # 转换为单值（parse_qs 返回 list）
        flat_params = {}
        for k, v in params.items():
            flat_params[k] = v[-1] if v else ''
        if page_field:
            flat_params[page_field] = str(page_num)
        # size_field 不再修改，保留原始 pageSize
        new_query = urlencode(flat_params, doseq=True)
        new_url = urlunparse(parsed._replace(query=new_query))
        # 返回 JS fetch 代码
        return f"""
        (() => {{
            fetch('{new_url}', {{ credentials: 'include' }})
                .then(r => r.text())
                .catch(e => console.error('[PaginationFetch]', e));
        }})()
        """

    async def _extract_from_json(self, json_str: str, extract_config: dict,
                                 task_id: str, merchant_id: str) -> list[dict]:
        """
        从 JSON 响应中提取并映射数据（复用 CURL 模式的提取逻辑）

        Args:
            json_str: API 响应 JSON 字符串
            extract_config: 提取配置 {enabled, list_path, fields}
        """
        import re as _re

        records = []

        try:
            # 尝试直接解析
            if isinstance(json_str, str):
                # 处理可能的 BOM / 非法字符
                cleaned = json_str.strip()
                if cleaned.startswith('\ufeff'):
                    cleaned = cleaned[1:]
                # 尝试提取 JSON（如果被包裹在回调中）
                json_match = _re.search(r'[\{\[]', cleaned)
                if json_match:
                    cleaned = cleaned[json_match.start():]
                    # 找到最后一个 } 或 ]
                    last_brace = max(
                        cleaned.rfind('}'),
                        cleaned.rfind(']')
                    )
                    if last_brace > 0:
                        cleaned = cleaned[:last_brace + 1]

                data = json.loads(cleaned)
            else:
                data = json_str

            if not isinstance(data, dict):
                raise Exception(f'Expected dict, got {type(data).__name__}')

        except json.JSONDecodeError as e:
            self.emit_event('task:log', {
                'taskId': task_id, 'merchantId': merchant_id,
                'log': {'level': 'error',
                        'message': f'❌ JSON 解析失败: {str(e)[:100]}',
                        'timestamp': time.time()}
            })
            return records
        except Exception as e:
            self.emit_event('task:log', {
                'taskId': task_id, 'merchantId': merchant_id,
                'log': {'level': 'error',
                        'message': f'❌ 数据解析异常: {str(e)[:100]}',
                        'timestamp': time.time()}
            })
            return records

        # 按 list_path 定位数据列表
        list_path = extract_config.get('list_path', '') if extract_config else ''
        fields = extract_config.get('fields', []) if extract_config else []

        if list_path:
            # 按路径定位: "data.records" → data['data']['records']
            current = data
            path_parts = [p for p in list_path.split('.') if p]

            for part in path_parts:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                elif isinstance(current, list) and part.isdigit():
                    idx = int(part)
                    if idx < len(current):
                        current = current[idx]
                    else:
                        current = None
                        break
                else:
                    current = None
                    break

            items = current if isinstance(current, list) else ([current] if current else [])
        else:
            # 无 list_path: 如果顶层是列表直接用；如果是字典则包装成单条
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                # 尝试自动发现数组字段
                array_keys = [k for k, v in data.items() if isinstance(v, list)]
                if len(array_keys) == 1:
                    items = data[array_keys[0]]
                else:
                    items = [data]  # 整个对象作为一条记录
            else:
                items = [data]

        # 字段映射提取
        for item in items:
            if not isinstance(item, dict):
                continue

            row_data = {}

            if fields:
                for field_def in fields:
                    target_name = field_def.get('target', '')
                    source_path = field_def.get('source', '')

                    if not source_path:
                        continue

                    # 支持多级路径: "orderNo" 或 "order.no"
                    val = item
                    for seg in source_path.split('.'):
                        if isinstance(val, dict) and seg in val:
                            val = val[seg]
                        else:
                            val = None
                            break

                    row_data[target_name] = val if val is not None else ''

            else:
                # 无字段配置：保留所有原始键值
                row_data = {k: v for k, v in item.items() if not isinstance(v, (dict, list))}

            if any(v for v in row_data.values() if v != '' and v is not None):
                records.append(row_data)

        if records:
            self.emit_event('task:log', {
                'taskId': task_id, 'merchantId': merchant_id,
                'log': {'level': 'info',
                        'message': f'📊 从响应中提取 {len(records)} 条记录',
                        'timestamp': time.time()}
            })

        return records

    async def _extract_page_data(self, page: Page, extract_config: dict,
                                 task_id: str, merchant_id: str) -> list[dict]:
        """从当前页面提取数据"""
        rows = []

        if not extract_config or not extract_config.get('enabled'):
            rows = await self._auto_detect_table(page)
            self.emit_event('task:log', {
                'taskId': task_id, 'merchantId': merchant_id,
                'log': {'level': 'info', 'message': f'📊 自动检测到 {len(rows)} 条数据', 'timestamp': time.time()}
            })
            return rows

        list_selector = extract_config.get('list_path', '')
        fields = extract_config.get('fields', [])

        if list_selector:
            row_elements = page.locator(list_selector)
            count = await row_elements.count()

            if count == 0:
                self.emit_event('task:log', {
                    'taskId': task_id, 'merchantId': merchant_id,
                    'log': {'level': 'warn', 'message': f'⚠️ 未找到数据行: {list_selector}', 'timestamp': time.time()}
                })
                return []

            for i in range(count):
                row_el = row_elements.nth(i)
                row_data = {}

                for field_def in fields:
                    target_name = field_def.get('target', '')
                    source_sel = field_def.get('source', '')

                    if source_sel:
                        try:
                            cell = row_el.locator(source_sel).first
                            if await cell.count() > 0:
                                text_val = await cell.inner_text()
                                row_data[target_name] = text_val.strip()
                            else:
                                row_data[target_name] = ''
                        except Exception:
                            row_data[target_name] = ''
                    else:
                        row_data[target_name] = ''

                if any(v for v in row_data.values()):
                    rows.append(row_data)

            self.emit_event('task:log', {
                'taskId': task_id, 'merchantId': merchant_id,
                'log': {'level': 'info', 'message': f'📊 当前页提取 {len(rows)} 条数据', 'timestamp': time.time()}
            })

        return rows

    async def _extract_paginated_data(self, page: Page, extract_config: dict,
                                      pagination_config: dict, task_id: str, merchant_id: str) -> list[dict]:
        """分页提取数据"""
        all_records = []

        max_pages = pagination_config.get('max_pages', 20)
        current_page = 1

        first_page_records = await self._extract_page_data(page, extract_config, task_id, merchant_id)
        all_records.extend(first_page_records)

        while current_page < max_pages:
            try:
                next_btn = page.locator('.next-page, .btn-next, [aria-label="Next"]').first
                if await next_btn.count() == 0:
                    break

                is_disabled = await next_btn.evaluate('''el => {
                    return el.disabled ||
                           el.classList.contains('disabled') ||
                           el.classList.contains('is-disabled') ||
                           el.getAttribute('aria-disabled') === 'true' ||
                           el.style.opacity === '0.5' ||
                           el.style.pointerEvents === 'none'
                }''')

                if is_disabled:
                    self.emit_event('task:log', {
                        'taskId': task_id, 'merchantId': merchant_id,
                        'log': {'level': 'info', 'message': f'📄 下一页按钮已禁用，停止翻页', 'timestamp': time.time()}
                    })
                    break

                current_page += 1
                self.emit_event('task:progress', {
                    'taskId': task_id, 'merchantId': merchant_id,
                    'status': 'running', 'progress': min(60 + int(30 * current_page / max_pages), 95),
                    'message': f'正在翻到第 {current_page} 页 ({len(all_records)}条)...'
                })

                await next_btn.scroll_into_view_if_needed()
                await asyncio.sleep(0.5)
                await next_btn.click()
                await asyncio.sleep(2)

                page_records = await self._extract_page_data(page, extract_config, task_id, merchant_id)

                if not page_records:
                    break

                all_records.extend(page_records)

            except Exception as e:
                logger.warning(f'[Pagination] Page {current_page} error: {e}')
                break

        self.emit_event('task:log', {
            'taskId': task_id, 'merchantId': merchant_id,
            'log': {'level': 'info', 'message': f'📊 分页完成: 共{current_page}页, {len(all_records)}条数据',
                    'timestamp': time.time()}
        })

        return all_records

    async def _auto_detect_table(self, page: Page) -> list[dict]:
        """自动检测页面中的 HTML 表格并提取数据"""
        records = []
        try:
            tables = page.locator('table')
            count = await tables.count()
            if count > 0:
                rows = tables.first.locator('tbody tr, tr')
                row_count = await rows.count()
                if row_count > 1:
                    headers = []
                    header_row = rows.nth(0)
                    th_cells = await header_row.locator('th, td').all_text_contents()
                    headers = [h.strip() for h in th_cells]

                    for i in range(1, min(row_count, 101)):
                        row_el = rows.nth(i)
                        cells = await row_el.locator('td, th').all_text_contents()
                        cell_texts = [c.strip() for c in cells]

                        if headers:
                            record = {}
                            for j, h in enumerate(headers):
                                if j < len(cell_texts):
                                    record[h] = cell_texts[j]
                            if record:
                                records.append(record)
                        else:
                            records.append({'raw': '|'.join(cell_texts)})
        except Exception as e:
            logger.warning(f'Auto-detect table failed: {e}')

        return records

    async def _restore_credentials(self, context: BrowserContext, merchant_id: str):
        """恢复登录凭证到浏览器上下文（cookies + localStorage）"""
        # 获取已解密的 cookies
        cred = self.credential_mgr.get_credentials(merchant_id)
        if not cred or not cred.get('cookies'):
            logger.warning(f'No valid credentials for merchant {merchant_id}')
            return

        try:
            # 1. 恢复 cookies
            cookies = cred.get('cookies', [])
            if cookies:
                await context.add_cookies(cookies)
                logger.info(f'Restored {len(cookies)} cookies for {merchant_id}')

            # 2. 恢复 localStorage（通过 init_script 注入）
            storage_state = self.credential_mgr.get_storage_state(merchant_id)
            if storage_state and 'origins' in storage_state:
                for origin in storage_state.get('origins', []):
                    origin_str = origin.get('origin', '')
                    ls_items = origin.get('localStorage', [])
                    if not origin_str or not ls_items:
                        continue
                    # 将 localStorage 数据序列化为 JS 赋值语句
                    js_statements = []
                    for item in ls_items:
                        name = item.get('name', '')
                        value = item.get('value', '')
                        js_statements.append(
                            f"window.localStorage.setItem({json.dumps(name)}, {json.dumps(value)});"
                        )
                    if js_statements:
                        await context.add_init_script('\n'.join(js_statements))
                        logger.info(f'Restored {len(ls_items)} localStorage items for {origin_str}')

        except Exception as e:
            logger.warning(f'Restore credentials failed for {merchant_id}: {e}')
