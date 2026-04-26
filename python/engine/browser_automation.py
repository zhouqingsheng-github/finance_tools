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

                    # ---- 2a: 准备触发动作（真正执行放到监听器挂好之后，避免漏抓请求）----
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
                                    'message': f'🖱️ [步骤 {li_idx + 1}] 监听就绪后点击 [{action_selector}]: {l_api_url}',
                                    'timestamp': time.time()}
                        })
                    else:
                        # immediate 模式：直接开始监听
                        self.emit_event('task:log', {
                            'taskId': task_id, 'merchantId': merchant_id,
                            'log': {'level': 'info',
                                    'message': f'⚡ [步骤 {li_idx + 1}] 监听就绪后刷新页面: {listener_label}',
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
                        # 先采集浏览器状态快照，再按配置解析 $storage / $session / $cookie
                        if l_field_mapping:
                            await self._resolve_browser_state_refs(page, l_field_mapping, extracted_vars, task_id, merchant_id)
                        # 解析 $变量引用（从之前 extract 监听器的提取结果中取值）
                        resolved_fm = self._resolve_field_mapping_refs(l_field_mapping,
                                                                       extracted_vars) if l_field_mapping else None
                        records = await self._extract_from_response(
                            page, l_api_url, l_extract_cfg, l_pagination_cfg,
                            task_id, merchant_id, base_progress,
                            field_mapping=resolved_fm,
                            action=l_action,
                            step_num=li_idx + 1
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
                        # 先采集浏览器状态快照，再按配置解析 $storage / $session / $cookie
                        if l_field_mapping:
                            await self._resolve_browser_state_refs(page, l_field_mapping, extracted_vars, task_id, merchant_id)
                        # 解析 $变量引用（从之前 extract 监听器的提取结果中取值）
                        resolved_mapping = self._resolve_field_mapping_refs(l_field_mapping,
                                                                            extracted_vars) if l_field_mapping else {}
                        records = await self._capture_api_as_curl(
                            page, l_api_url, task_id, merchant_id,
                            field_mapping=resolved_mapping if resolved_mapping else None,
                            extract_config=l_extract_cfg,
                            pagination_config=l_pagination_cfg,
                            action=l_action,
                            step_num=li_idx + 1
                        )
                        if records:
                            all_records.extend(records)
                            self.emit_event('task:log', {
                                'taskId': task_id, 'merchantId': merchant_id,
                                'log': {'level': 'info',
                                        'message': f'📊 [{li_idx + 1}] CURL 重放提取到 {len(records)} 条数据',
                                        'timestamp': time.time()}
                            })
                            if records[0]:
                                extracted_vars.update(
                                    {k: v for k, v in records[0].items() if v is not None and v != ''})
                                logger.info(f'[Listener #{li_idx}] extracted_vars updated from capture replay')

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
    def _normalize_storage_ref(value: str) -> str:
        """容错清理 storage/session 引用里的空格，如 value. partnerId -> value.partnerId。"""
        if not isinstance(value, str):
            return value
        import re as _re
        value = _re.sub(r'(\$(?:storage|session):\S+)\s+\.\s*', r'\1.', value)
        value = _re.sub(r'(\$(?:storage|session):\S+\.)\s+', r'\1', value)
        return value

    @staticmethod
    def _parse_storage_ref(ref: str):
        """
        解析 storage/session 引用。
        格式：
          $storage:key.path
          $storage:https://host:key.path
        """
        if not isinstance(ref, str) or not ref.startswith('$'):
            return None
        import re as _re
        normalized = BrowserAutomationEngine._normalize_storage_ref(ref.strip())
        match = _re.match(r'^\$(storage|session):(.+)$', normalized)
        if not match:
            return None
        storage_type = match.group(1)
        rest = match.group(2).strip()
        origin = ''
        if rest.startswith('http://') or rest.startswith('https://'):
            origin_match = _re.match(r'^(https?://[^:\s]+):(.*)$', rest)
            if not origin_match:
                return None
            origin = origin_match.group(1).rstrip('/')
            path_str = origin_match.group(2).strip()
        else:
            path_str = rest
        path_str = _re.sub(r'\s*\.\s*', '.', path_str)
        parts = path_str.split('.', 1)
        storage_key = parts[0].strip()
        json_path = parts[1].strip() if len(parts) > 1 else ''
        if not storage_key:
            return None
        return {
            'storage_type': storage_type,
            'origin': origin,
            'storage_key': storage_key,
            'json_path': json_path,
            'full_ref': normalized,
        }

    @staticmethod
    def _parse_cookie_ref(ref: str):
        """
        解析 cookie 引用。
        格式：
          $cookie:name
          $cookie:https://host:name
        """
        if not isinstance(ref, str) or not ref.startswith('$cookie:'):
            return None
        import re as _re
        normalized = ref.strip()
        rest = normalized[len('$cookie:'):].strip()
        origin = ''
        if rest.startswith('http://') or rest.startswith('https://'):
            origin_match = _re.match(r'^(https?://[^:\s]+):(.*)$', rest)
            if not origin_match:
                return None
            origin = origin_match.group(1).rstrip('/')
            cookie_name = origin_match.group(2).strip()
        else:
            cookie_name = rest
        if not cookie_name:
            return None
        return {
            'origin': origin,
            'cookie_name': cookie_name,
            'full_ref': normalized,
        }

    @staticmethod
    def _get_storage_json_path_value(raw: any, json_path: str):
        """读取 storage JSON 路径，遇到嵌套 JSON 字符串会自动继续解析。"""
        if not json_path:
            return raw

        current = raw
        for segment in [p for p in json_path.split('.') if p]:
            if isinstance(current, str):
                text = current.strip()
                if (text.startswith('{') and text.endswith('}')) or (text.startswith('[') and text.endswith(']')):
                    current = json.loads(text)
            current = BrowserAutomationEngine._get_path_value(current, segment, None)
            if current is None:
                return None
        return current

    async def _collect_browser_state(self, page: Page, task_id: str = '', merchant_id: str = '') -> dict:
        """一次性采集当前浏览器上下文中的 cookies、所有 frame 的 localStorage/sessionStorage。"""
        from urllib.parse import urlparse

        def frame_origin(frame) -> str:
            try:
                parsed = urlparse(frame.url)
                if parsed.scheme and parsed.netloc:
                    return f'{parsed.scheme}://{parsed.netloc}'
            except Exception:
                pass
            return ''

        state = {
            'cookies': [],
            'frames': [],
        }

        try:
            state['cookies'] = await page.context.cookies()
        except Exception as e:
            logger.warning(f'[BrowserState] 读取 cookies 失败: {e}')

        for frame in page.frames:
            origin = frame_origin(frame)
            if not origin:
                continue
            try:
                frame_state = await frame.evaluate('''() => {
                    const dump = (store) => {
                        const data = {};
                        for (let i = 0; i < store.length; i++) {
                            const key = store.key(i);
                            data[key] = store.getItem(key);
                        }
                        return data;
                    };
                    return {
                        href: location.href,
                        origin: location.origin,
                        localStorage: dump(localStorage),
                        sessionStorage: dump(sessionStorage)
                    };
                }''')
                state['frames'].append(frame_state)
            except Exception as e:
                logger.warning(f'[BrowserState] 读取 frame storage 失败 origin={origin}: {e}')

        cookie_names = sorted({c.get('name', '') for c in state['cookies'] if c.get('name')})
        frame_summaries = [
            {
                'origin': f.get('origin'),
                'localKeys': list((f.get('localStorage') or {}).keys())[:20],
                'sessionKeys': list((f.get('sessionStorage') or {}).keys())[:20],
            }
            for f in state['frames']
        ]
        msg = f'[BrowserState] cookies={cookie_names[:30]} frames={frame_summaries}'
        logger.info(msg)
        if task_id:
            self.emit_event('task:log', {
                'taskId': task_id,
                'merchantId': merchant_id,
                'log': {'level': 'debug', 'message': msg, 'timestamp': time.time()}
            })

        return state

    async def _resolve_browser_state_refs(self, page: Page, field_mapping: dict, extracted_vars: dict,
                                          task_id: str = '', merchant_id: str = '') -> None:
        """先采集浏览器状态快照，再按配置解析 storage/session/cookie 引用。"""
        browser_state = await self._collect_browser_state(page, task_id, merchant_id)

        from urllib.parse import urlparse

        def cookie_matches_origin(cookie: dict, origin: str) -> bool:
            if not origin:
                return True
            host = urlparse(origin).hostname or ''
            domain = (cookie.get('domain') or '').lstrip('.')
            return bool(host and domain and (host == domain or host.endswith('.' + domain) or domain.endswith('.' + host)))

        def select_frames(origin: str) -> list:
            if not origin:
                return browser_state['frames']
            return [f for f in browser_state['frames'] if f.get('origin') == origin.rstrip('/')]

        for fm_key, ref_value in field_mapping.items():
            if not isinstance(ref_value, str):
                continue

            storage_ref = BrowserAutomationEngine._parse_storage_ref(ref_value)
            if storage_ref:
                stype = storage_ref['storage_type']
                storage_key = storage_ref['storage_key']
                json_path = storage_ref['json_path']
                origin = storage_ref['origin']
                store_name = 'localStorage' if stype == 'storage' else 'sessionStorage'
                raw = None
                source_origin = ''
                candidate_frames = select_frames(origin)
                if origin and not candidate_frames:
                    msg = f'[BrowserState] origin={origin} 未匹配到 frame，改为按 key={storage_key} 在所有 frame 中查找'
                    logger.warning(msg)
                    if task_id:
                        self.emit_event('task:log', {
                            'taskId': task_id,
                            'merchantId': merchant_id,
                            'log': {'level': 'warn', 'message': msg, 'timestamp': time.time()}
                        })
                    candidate_frames = browser_state['frames']

                for frame_state in candidate_frames:
                    store = frame_state.get(store_name) or {}
                    if storage_key in store:
                        raw = store.get(storage_key)
                        source_origin = frame_state.get('origin', '')
                        break

                if raw is None and origin:
                    msg = f'[BrowserState] origin={origin} 下未找到 key={storage_key}，改为按 key 在所有 frame 中兜底查找'
                    logger.warning(msg)
                    if task_id:
                        self.emit_event('task:log', {
                            'taskId': task_id,
                            'merchantId': merchant_id,
                            'log': {'level': 'warn', 'message': msg, 'timestamp': time.time()}
                        })
                    for frame_state in browser_state['frames']:
                        store = frame_state.get(store_name) or {}
                        if storage_key in store:
                            raw = store.get(storage_key)
                            source_origin = frame_state.get('origin', '')
                            break

                if raw is None:
                    msg = f'[BrowserState] 未找到 {storage_ref["full_ref"]}，字段={fm_key}'
                    logger.warning(msg)
                    if task_id:
                        self.emit_event('task:log', {
                            'taskId': task_id,
                            'merchantId': merchant_id,
                            'log': {'level': 'warn', 'message': msg, 'timestamp': time.time()}
                        })
                    continue

                raw_preview = raw[:500] if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)[:500]
                raw_msg = (
                    f'[BrowserState] 命中 {store_name} key={storage_key} @ {source_origin}, '
                    f'value_len={len(raw or "")}, value_preview={raw_preview}'
                )
                logger.info(raw_msg)
                if task_id:
                    self.emit_event('task:log', {
                        'taskId': task_id,
                        'merchantId': merchant_id,
                        'log': {'level': 'debug', 'message': raw_msg, 'timestamp': time.time()}
                    })

                try:
                    value = raw
                    if json_path:
                        parsed = json.loads(raw) if isinstance(raw, str) else raw
                        value = BrowserAutomationEngine._get_storage_json_path_value(parsed, json_path)
                    value = '' if value is None else str(value)
                except Exception as e:
                    msg = f'[BrowserState] 解析 {storage_ref["full_ref"]} 失败: {e}'
                    logger.warning(msg)
                    value = ''

                import re as _re
                var_name = _re.split(r'\.', json_path)[-1] if json_path else storage_key
                arr_match = _re.match(r'(\w+)', var_name)
                if arr_match:
                    var_name = arr_match.group(1)
                extracted_vars[fm_key] = value
                extracted_vars[var_name] = value
                extracted_vars[storage_ref['full_ref']] = value
                msg = f'[BrowserState] {storage_ref["full_ref"]} @ {source_origin} -> {var_name}=len({len(value)})'
                logger.info(msg)
                if task_id:
                    self.emit_event('task:log', {
                        'taskId': task_id,
                        'merchantId': merchant_id,
                        'log': {'level': 'debug', 'message': msg, 'timestamp': time.time()}
                    })
                continue

            cookie_ref = BrowserAutomationEngine._parse_cookie_ref(ref_value)
            if cookie_ref:
                cookie_name = cookie_ref['cookie_name']
                origin = cookie_ref['origin']
                matched = [
                    c for c in browser_state['cookies']
                    if c.get('name') == cookie_name and cookie_matches_origin(c, origin)
                ]
                value = matched[0].get('value', '') if matched else ''
                extracted_vars[fm_key] = value
                extracted_vars[cookie_name] = value
                extracted_vars[cookie_ref['full_ref']] = value
                msg = f'[BrowserState] {cookie_ref["full_ref"]} -> {cookie_name}=len({len(value)}) origin={origin or "*"}'
                logger.info(msg)
                if task_id:
                    self.emit_event('task:log', {
                        'taskId': task_id,
                        'merchantId': merchant_id,
                        'log': {'level': 'debug' if value else 'warn', 'message': msg, 'timestamp': time.time()}
                    })

    async def _resolve_storage_refs(self, page: Page, field_mapping: dict, extracted_vars: dict,
                                    task_id: str = '', merchant_id: str = '') -> None:
        """
        扫描 field_mapping 中的 $storage: / $session: 引用，从浏览器 storage 读取值后注入 extracted_vars。

        支持格式：
          - $storage:tokenKey              → 当前页面 localStorage.getItem('tokenKey')
          - $storage:authInfo.access_token → localStorage 取值后 JSON 解析，按路径取 access_token
          - $session:cartData.items[0].id  → sessionStorage 同理，支持数组索引
          - $storage:https://tpt.meituan.com:authInfo.token → 指定域名的 localStorage（跨域）
          - $session:https://me.meituan.com:sid               指定域名的 sessionStorage（跨域）

        跨域读取会临时打开同源页面读取，读完立即关闭。
        读取后的值会以最后一段路径为 key 存入 extracted_vars，供 _resolve_field_mapping_refs 使用。
        """
        # 收集所有需要读取的 storage 引用
        # 按 (storage_type, origin, storage_key) 分组
        storage_reads = {}  # {(type, origin, key): [(fm_key, full_ref, json_path)]}
        for fm_key, value in field_mapping.items():
            if not isinstance(value, str):
                continue
            parsed_ref = BrowserAutomationEngine._parse_storage_ref(value)
            if not parsed_ref:
                continue
            read_key = (
                parsed_ref['storage_type'],
                parsed_ref['origin'],
                parsed_ref['storage_key']
            )
            if read_key not in storage_reads:
                storage_reads[read_key] = []
            storage_reads[read_key].append((fm_key, parsed_ref['full_ref'], parsed_ref['json_path']))

        if not storage_reads:
            return

        raw_values = {}

        def frame_origin(frame) -> str:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(frame.url)
                if parsed.scheme and parsed.netloc:
                    return f'{parsed.scheme}://{parsed.netloc}'
            except Exception:
                pass
            return ''

        async def read_frame_storage(frame, stype: str, sk: str):
            return await frame.evaluate('''(config) => {
                const localKeys = Object.keys(localStorage);
                const sessionKeys = Object.keys(sessionStorage);
                const store = config.isLocal ? localStorage : sessionStorage;
                return {
                    value: store.getItem(config.key),
                    localKeys,
                    sessionKeys,
                    href: location.href,
                    origin: location.origin
                };
            }''', {'isLocal': stype == 'storage', 'key': sk})

        for (stype, origin, sk), refs in storage_reads.items():
            lookup_key = f'{stype}:{sk}'
            target_origin = origin.rstrip('/') if origin else ''
            frames = [f for f in page.frames if frame_origin(f)]
            if target_origin:
                candidates = [f for f in frames if frame_origin(f) == target_origin]
            else:
                candidates = frames

            for frame in candidates:
                try:
                    result = await read_frame_storage(frame, stype, sk)
                    msg = (
                        f'[StorageResolve] frame={result.get("origin")} key={stype}:{sk} '
                        f'value_len={len(result.get("value") or "")} '
                        f'localKeys={result.get("localKeys", [])[:20]} '
                        f'sessionKeys={result.get("sessionKeys", [])[:20]}'
                    )
                    logger.info(msg)
                    if task_id:
                        self.emit_event('task:log', {
                            'taskId': task_id,
                            'merchantId': merchant_id,
                            'log': {'level': 'debug', 'message': msg, 'timestamp': time.time()}
                        })
                    if result.get('value') is not None:
                        raw_values[lookup_key] = result.get('value')
                        break
                except Exception as e:
                    logger.warning(f'[StorageResolve] frame 读取失败 origin={frame_origin(frame)} key={stype}:{sk}: {e}')

            # localStorage 可以用同 browser context 临时打开 origin 兜底；sessionStorage 不共享，兜底意义不大。
            if lookup_key not in raw_values and target_origin and stype == 'storage':
                temp_page = None
                try:
                    temp_page = await page.context.new_page()
                    await temp_page.goto(target_origin, wait_until='domcontentloaded', timeout=10000)
                    result = await read_frame_storage(temp_page.main_frame, stype, sk)
                    raw_values[lookup_key] = result.get('value')
                    msg = (
                        f'[StorageResolve] fallback origin={target_origin} key={stype}:{sk} '
                        f'value_len={len(result.get("value") or "")} '
                        f'localKeys={result.get("localKeys", [])[:20]}'
                    )
                    logger.info(msg)
                    if task_id:
                        self.emit_event('task:log', {
                            'taskId': task_id,
                            'merchantId': merchant_id,
                            'log': {'level': 'debug', 'message': msg, 'timestamp': time.time()}
                        })
                except Exception as e:
                    logger.warning(f'[StorageResolve] fallback 读取失败 origin={target_origin} key={stype}:{sk}: {e}')
                finally:
                    if temp_page:
                        await temp_page.close()

        # 解析每个引用，提取值并注入 extracted_vars
        for (storage_type, origin, storage_key), refs in storage_reads.items():
            lookup_key = f'{storage_type}:{storage_key}'
            raw = raw_values.get(lookup_key)
            if raw is None:
                logger.warning(f'[StorageResolve] {lookup_key} 不存在{(" (" + origin + ")") if origin else ""}，请核对 Application 中的 origin 和 key')
                continue

            for fm_key, full_ref, json_path in refs:
                value = raw
                if json_path:
                    # 尝试 JSON 解析后按路径取值
                    try:
                        parsed = json.loads(raw) if isinstance(raw, str) else raw
                        parsed = BrowserAutomationEngine._get_storage_json_path_value(parsed, json_path)
                        value = str(parsed) if parsed is not None else ''
                    except (json.JSONDecodeError, KeyError, TypeError, IndexError) as e:
                        logger.warning(f'[StorageResolve] 解析 {full_ref} 路径失败: {e}')
                        value = ''
                # 提取变量名：路径最后一段
                import re as _re
                var_name = _re.split(r'\.', json_path)[-1] if json_path else storage_key
                # 清理数组索引
                arr_match = _re.match(r'(\w+)', var_name)
                if arr_match:
                    var_name = arr_match.group(1)
                extracted_vars[var_name] = value
                logger.info(f'[StorageResolve] {full_ref} → {var_name}={value[:80]}')

    async def _resolve_cookie_refs(self, page: Page, field_mapping: dict, extracted_vars: dict,
                                   task_id: str = '', merchant_id: str = '') -> None:
        """读取 $cookie:name / $cookie:https://host:name 并注入 extracted_vars。"""
        cookie_refs = []
        for fm_key, value in field_mapping.items():
            parsed_ref = BrowserAutomationEngine._parse_cookie_ref(value) if isinstance(value, str) else None
            if parsed_ref:
                cookie_refs.append(parsed_ref)

        if not cookie_refs:
            return

        try:
            all_cookies = await page.context.cookies()
        except Exception as e:
            logger.warning(f'[CookieResolve] 读取 cookies 失败: {e}')
            return

        from urllib.parse import urlparse

        def cookie_matches_origin(cookie: dict, origin: str) -> bool:
            if not origin:
                return True
            host = urlparse(origin).hostname or ''
            domain = (cookie.get('domain') or '').lstrip('.')
            return bool(host and domain and (host == domain or host.endswith('.' + domain) or domain.endswith('.' + host)))

        available_names = sorted({c.get('name', '') for c in all_cookies if c.get('name')})
        for ref in cookie_refs:
            cookie_name = ref['cookie_name']
            origin = ref['origin']
            matched = [
                c for c in all_cookies
                if c.get('name') == cookie_name and cookie_matches_origin(c, origin)
            ]
            value = matched[0].get('value', '') if matched else ''
            extracted_vars[cookie_name] = value

            msg = (
                f'[CookieResolve] {ref["full_ref"]} → {cookie_name} '
                f'value_len={len(value)} origin={origin or "*"} '
                f'available={available_names[:30]}'
            )
            logger.info(msg)
            if task_id:
                self.emit_event('task:log', {
                    'taskId': task_id,
                    'merchantId': merchant_id,
                    'log': {'level': 'debug' if value else 'warn', 'message': msg, 'timestamp': time.time()}
                })

    @staticmethod
    def _resolve_field_mapping_refs(field_mapping: dict, extracted_vars: dict) -> dict:
        """
        解析 field_mapping 值中的 $变量引用。

        当值以 $ 开头时（如 "$partnerId"），从 extracted_vars 中查找对应变量并替换。
        支持格式：
          - $partnerId       → 直接取 extracted_vars["partnerId"]
          - ${partnerId}     → 同上（大括号可选）
          - $storage:xxx     → 已由 _resolve_storage_refs 预处理到 extracted_vars 中
          - prefix$partnerId → 保留前缀，仅替换 $ 引用部分

        Args:
            field_mapping: 原始参数映射 {参数名: 值}
            extracted_vars: 跨监听器共享的提取变量字典（含 storage 预读取值）

        Returns:
            解析后的新 mapping 字典
        """
        resolved = {}
        for key, value in field_mapping.items():
            if not isinstance(value, str):
                resolved[key] = value
                continue

            # 处理 $storage: / $session: 引用（可能是值的一部分或全部）
            parsed_ref = BrowserAutomationEngine._parse_storage_ref(value)
            if parsed_ref:
                import re as _re
                json_path = parsed_ref['json_path']
                var_name = _re.split(r'\.', json_path)[-1] if json_path else parsed_ref['storage_key']
                arr_match = _re.match(r'(\w+)', var_name)
                if arr_match:
                    var_name = arr_match.group(1)
                resolved[key] = (
                    extracted_vars.get(key)
                    or extracted_vars.get(parsed_ref['full_ref'])
                    or extracted_vars.get(var_name)
                    or parsed_ref['full_ref']
                )
                continue

            parsed_cookie = BrowserAutomationEngine._parse_cookie_ref(value)
            if parsed_cookie:
                cookie_name = parsed_cookie['cookie_name']
                resolved[key] = (
                    extracted_vars.get(key)
                    or extracted_vars.get(parsed_cookie['full_ref'])
                    or extracted_vars.get(cookie_name)
                    or parsed_cookie['full_ref']
                )
                continue

            # 处理普通 $变量引用
            if value.startswith('$'):
                ref_name = value
                if ref_name.startswith('${') and ref_name.endswith('}'):
                    ref_name = ref_name[2:-1]
                elif ref_name.startswith('$'):
                    ref_name = ref_name[1:]
                if ref_name and ref_name in extracted_vars:
                    resolved[key] = extracted_vars[ref_name]
                    logger.info(f'[RefResolve] {key}: ${ref_name} → {extracted_vars[ref_name]}')
                else:
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

        clean_mapping = {}
        for key, value in field_mapping.items():
            if isinstance(value, str) and value.startswith(('$storage:', '$session:', '$cookie:')):
                logger.warning(f'[FieldMapping] 动态参数 [{key}] 未解析成功，跳过写入: {value}')
                continue
            clean_mapping[key] = value

        # ---- 1. 替换 URL query 参数 ----
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        changed = False
        applied_keys = set()
        for key, new_val in clean_mapping.items():
            if key in params:
                old_val = params[key]
                params[key] = [str(new_val)]
                changed = True
                applied_keys.add(key)
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
                if isinstance(body_obj, (dict, list)):
                    body_changed = False
                    for key, new_val in clean_mapping.items():
                        old_val = self._find_path_value(body_obj, key, None)
                        if self._set_path_value(body_obj, key, new_val):
                            body_changed = True
                            applied_keys.add(key)
                            logger.info(f'[FieldMapping] Body param [{key}]: {old_val} → {new_val}')
                    if body_changed:
                        post_data = json.dumps(body_obj, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError):
                # 非JSON body（form-urlencoded 等）：尝试字符串替换
                body_changed = False
                for key, new_val in clean_mapping.items():
                    import re as _re
                    # 匹配 key=value 或 key=value& 模式
                    pattern = _re.compile(r'(' + _re.escape(key) + r'=)[^&]*')
                    match = pattern.search(post_data)
                    if match:
                        old_kv = match.group(0)
                        new_kv = f'{key}={str(new_val)}'
                        post_data = pattern.sub(new_kv, post_data, count=1)
                        body_changed = True
                        applied_keys.add(key)
                        logger.info(f'[FieldMapping] Form param [{key}]: {old_kv} → {new_kv}')

        missing_keys = [key for key in clean_mapping.keys() if key not in applied_keys]
        if missing_keys:
            logger.warning(f'[FieldMapping] 未在 URL/body 中找到这些动态参数: {missing_keys}')

        return url, post_data

    async def _trigger_listener_action(self, page: Page, action: dict,
                                       task_id: str, merchant_id: str,
                                       step_num: int):
        """在网络监听器挂好后触发页面动作，避免请求先发生、监听后开始。"""
        action = action or {'type': 'immediate'}
        action_type = action.get('type', 'immediate')
        selector = action.get('selector', '')

        try:
            if action_type == 'click' and selector:
                locator = await self._find_clickable_locator(page, selector, timeout_ms=10000)
                if locator is None:
                    raise Exception(f'未找到可见元素: {selector}')
                await locator.scroll_into_view_if_needed()
                await asyncio.sleep(0.3)
                await locator.click()
                return

            # immediate 模式用于抓首屏接口：监听器已挂好后刷新页面，让接口重新发出。
            await page.reload(wait_until='domcontentloaded', timeout=60000)
            await asyncio.sleep(1.0)
        except Exception as e:
            logger.warning(f'[ListenerAction] step={step_num}, type={action_type}, selector={selector} failed: {e}')
            self.emit_event('task:log', {
                'taskId': task_id, 'merchantId': merchant_id,
                'log': {'level': 'warn',
                        'message': f'⚠️ [步骤 {step_num}] 触发动作失败: {e}',
                        'timestamp': time.time()}
            })

    async def _find_clickable_locator(self, page: Page, selector: str, timeout_ms: int = 10000):
        """在主页面和所有 iframe 中查找可见元素。"""
        deadline = time.time() + timeout_ms / 1000
        last_frame_urls: list[str] = []

        while time.time() < deadline:
            frames = page.frames
            last_frame_urls = [f.url for f in frames if f.url and f.url != 'about:blank']

            for frame in frames:
                try:
                    locator = frame.locator(selector).first
                    if await locator.count() > 0 and await locator.is_visible(timeout=500):
                        logger.info(f'[ListenerAction] selector found in frame: {frame.url}')
                        return locator
                except Exception:
                    continue

            await asyncio.sleep(0.3)

        logger.warning(f'[ListenerAction] selector not visible: {selector}; frames={last_frame_urls[:8]}')
        return None

    @staticmethod
    def _get_request_post_data(request) -> str:
        """兼容不同 Playwright 版本读取 request.post_data。"""
        try:
            post_data = getattr(request, 'post_data', '')
            if callable(post_data):
                post_data = post_data()
            return post_data or ''
        except Exception:
            return ''

    @staticmethod
    def _clean_fetch_headers(headers: dict) -> dict:
        """清理浏览器 fetch 不能或不应手动设置的请求头。"""
        skip_headers = {
            'host', 'cookie', 'content-length', 'accept-encoding', 'connection',
            'user-agent', 'referer', 'origin',
            'sec-ch-ua', 'sec-ch-ua-mobile', 'sec-ch-ua-platform',
            'sec-fetch-dest', 'sec-fetch-mode', 'sec-fetch-site',
            'upgrade-insecure-requests',
        }
        return {
            k: v for k, v in (headers or {}).items()
            if k and k.lower().strip() not in skip_headers and v is not None
        }

    async def _replay_captured_request(self, page: Page, req_info: dict,
                                       task_id: str, merchant_id: str) -> dict:
        """在当前浏览器上下文中重放抓到的请求，并返回响应文本。"""
        method = (req_info.get('method') or 'GET').upper()
        headers = self._clean_fetch_headers(req_info.get('headers', {}))
        body = req_info.get('post_data') or ''
        fetch_options = {
            'method': method,
            'headers': headers,
            'credentials': 'include',
        }
        if body and method in ('POST', 'PUT', 'PATCH'):
            fetch_options['body'] = body

        self.emit_event('task:log', {
            'taskId': task_id, 'merchantId': merchant_id,
            'log': {'level': 'info',
                    'message': f'🚀 使用抓到的 CURL 配置发起业务请求: {method} {req_info.get("url", "")[:120]}',
                    'timestamp': time.time()}
        })

        eval_target = req_info.get('_frame') or page
        result = await eval_target.evaluate('''async ({ url, options }) => {
            const response = await fetch(url, options);
            const text = await response.text();
            return {
                status: response.status,
                ok: response.ok,
                contentType: response.headers.get('content-type') || '',
                body: text
            };
        }''', {'url': req_info.get('url', ''), 'options': fetch_options})

        self.emit_event('task:log', {
            'taskId': task_id, 'merchantId': merchant_id,
            'log': {'level': 'info' if result.get('ok') else 'warn',
                    'message': f'HTTP {result.get("status")} | {len(result.get("body") or "")} bytes | Content-Type: {result.get("contentType", "")}',
                    'timestamp': time.time()}
        })

        if not result.get('ok'):
            raise Exception(f'业务请求失败 HTTP {result.get("status")}: {(result.get("body") or "")[:200]}')

        return result

    async def _replay_paginated_captured_request(self, page: Page, base_request: dict,
                                                first_body: str, extract_config: dict,
                                                pagination_config: dict,
                                                task_id: str, merchant_id: str) -> list[dict]:
        """基于抓到的请求继续重放分页，返回第 2 页及之后的数据。"""
        records: list[dict] = []
        page_field = pagination_config.get('page_field') or 'page'
        size_field = pagination_config.get('size_field') or 'pageSize'
        total_field = pagination_config.get('total_field') or ''
        is_total_page = pagination_config.get('is_total_page', False)

        total_value = 0
        if total_field:
            try:
                first_json = json.loads(first_body) if isinstance(first_body, str) else first_body
                total_value = int(self._find_path_value(first_json, total_field, 0) or 0)
            except Exception as e:
                logger.warning(f'[CaptureReplay] 解析 total_field 失败: {e}')

        page_size = self._get_page_size_from_request(base_request, size_field)
        if is_total_page and total_value > 0:
            total_pages = total_value
        elif total_value > 0:
            total_pages = max((total_value + page_size - 1) // page_size, 1)
        else:
            total_pages = pagination_config.get('max_pages') or 50

        self.emit_event('task:log', {
            'taskId': task_id, 'merchantId': merchant_id,
            'log': {'level': 'info',
                    'message': f'📄 CURL 分页执行: page_field={page_field}, pageSize={page_size}, 目标页数={total_pages}',
                    'timestamp': time.time()}
        })

        for page_num in range(2, int(total_pages) + 1):
            next_request = {
                **base_request,
                'url': base_request.get('url', ''),
                'post_data': base_request.get('post_data', ''),
            }
            next_url, next_body = self._set_request_page(next_request['url'], next_request['post_data'],
                                                         page_field, page_num)
            next_request['url'] = next_url
            next_request['post_data'] = next_body

            self.emit_event('task:progress', {
                'taskId': task_id, 'merchantId': merchant_id,
                'status': 'running',
                'progress': min(70 + int(25 * page_num / max(total_pages, page_num)), 94),
                'message': f'正在执行 CURL 第 {page_num}/{total_pages} 页... ({len(records)}条)'
            })

            try:
                result = await self._replay_captured_request(page, next_request, task_id, merchant_id)
                page_records = await self._extract_from_json(result.get('body', ''), extract_config, task_id, merchant_id)
                if not page_records:
                    logger.info(f'[CaptureReplay] 第{page_num}页无数据，停止分页')
                    break
                records.extend(page_records)
            except Exception as e:
                logger.warning(f'[CaptureReplay] 第{page_num}页请求失败: {e}')
                break

            await asyncio.sleep(0.3)

        self.emit_event('task:log', {
            'taskId': task_id, 'merchantId': merchant_id,
            'log': {'level': 'info',
                    'message': f'📊 CURL 分页完成: 后续页提取 {len(records)} 条数据',
                    'timestamp': time.time()}
        })
        return records

    async def _capture_api_as_curl(self, page: Page, api_url: str,
                                   task_id: str, merchant_id: str,
                                   field_mapping: dict | None = None,
                                   extract_config: dict | None = None,
                                   pagination_config: dict | None = None,
                                   action: dict | None = None,
                                   step_num: int = 1):
        """
        接口监听模式：打开页面 → 自动抓包 → 生成 CURL 命令 → 自动重放请求并提取数据

        特殊处理：
        - 自动从浏览器上下文提取 Cookies，拼入 curl -b 参数（解决登录凭证复用）
        - 过滤无关/冗余请求头，保留业务关键头
        """
        captured_request = None
        extracted_records: list[dict] = []

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

        async def on_route(route):
            nonlocal captured_request
            request = route.request
            try:
                url = request.url
                if captured_request or api_url not in url:
                    await route.continue_()
                    return
                raw_headers = dict(request.headers.items())
                post_data = ''
                try:
                    if request.method in ('POST', 'PUT', 'PATCH'):
                        post_data = self._get_request_post_data(request)
                except Exception:
                    pass
                captured_request = {
                    'url': url,
                    'method': request.method,
                    'headers': raw_headers,
                    'post_data': post_data,
                    '_frame': request.frame,
                }
                logger.info(f'[Capture] 拦截到请求: {request.method} {url} '
                            f'(headers={len(raw_headers)}, body={len(post_data)} bytes)')
                await route.abort()
            except Exception as e:
                logger.warning(f'[Capture] Route handler error: {e}')
                try:
                    await route.continue_()
                except Exception:
                    pass

        await page.route('**/*', on_route)

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
            await self._trigger_listener_action(page, action or {'type': 'immediate'}, task_id, merchant_id, step_num)

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

                # 抓包只负责生成 CURL 模板；真正采集从 CURL 模板的第 1 页重新执行。
                extract_config = extract_config or {}
                pagination_config = pagination_config or {}
                if pagination_config.get('enabled'):
                    page_field = pagination_config.get('page_field') or 'page'
                    reset_url, reset_body = self._set_request_page(
                        captured_request.get('url', ''),
                        captured_request.get('post_data', ''),
                        page_field,
                        1
                    )
                    captured_request['url'] = reset_url
                    captured_request['post_data'] = reset_body
                    self.emit_event('task:log', {
                        'taskId': task_id, 'merchantId': merchant_id,
                        'log': {'level': 'info',
                                'message': f'📌 CURL 模板已重置为第 1 页: {page_field}=1',
                                'timestamp': time.time()}
                    })

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
                    'status': 'running', 'progress': 70,
                    'message': 'CURL 已生成，正在执行业务请求...'
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

                # === 自动执行 CURL 模板，按提取/分页配置获取业务数据 ===
                self.emit_event('task:log', {
                    'taskId': task_id, 'merchantId': merchant_id,
                    'log': {'level': 'info',
                            'message': '🧩 抓到的请求只作为 CURL 模板，采集从该模板重新发起',
                            'timestamp': time.time()}
                })
                replay_result = await self._replay_captured_request(page, captured_request, task_id, merchant_id)
                first_body = replay_result.get('body', '')
                first_records = await self._extract_from_json(first_body, extract_config, task_id, merchant_id)
                extracted_records.extend(first_records)

                if pagination_config.get('enabled') and first_records:
                    page_records = await self._replay_paginated_captured_request(
                        page, captured_request, first_body, extract_config, pagination_config,
                        task_id, merchant_id
                    )
                    extracted_records.extend(page_records)

                self.emit_event('task:progress', {
                    'taskId': task_id, 'merchantId': merchant_id,
                    'status': 'running', 'progress': 95,
                    'message': f'CURL 执行完成，提取 {len(extracted_records)} 条数据'
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
                raise Exception(f'未拦截到目标接口请求: {api_url}')
        finally:
            try:
                await page.unroute('**/*', on_route)
            except Exception:
                pass

        return extracted_records

    async def _extract_from_response(self, page: Page, api_url: str,
                                     extract_config: dict, pagination_config: dict,
                                     task_id: str, merchant_id: str,
                                     base_progress: int = 30,
                                     field_mapping: dict | None = None,
                                     action: dict | None = None,
                                     step_num: int = 1):
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
        first_request_info: dict | None = None

        async def _parse_and_extract(response_body: str) -> list[dict]:
            """从响应体 JSON 中提取记录"""
            return await self._extract_from_json(response_body, extract_config, task_id, merchant_id)

        # --- 监听响应 ---
        async def on_response(response):
            nonlocal first_request_info
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
                    request = response.request
                    post_data = ''
                    try:
                        if request.method in ('POST', 'PUT', 'PATCH'):
                            post_data = self._get_request_post_data(request)
                    except Exception:
                        pass
                    request_info = {
                        'url': request.url,
                        'method': request.method,
                        'headers': dict(request.headers.items()),
                        'post_data': post_data,
                        '_frame': request.frame,
                    }
                    if first_request_info is None:
                        first_request_info = request_info
                    captured_responses.append({
                        'url': url,
                        'status': response.status,
                        'body': body,
                        'request': request_info,
                    })
                    logger.info(f'[Extract] 拦截到响应: {url} (status={response.status}, body={len(body)} bytes)')
            except Exception as e:
                logger.warning(f'[Extract] Response handler error: {e}')

        page.on('response', on_response)

        try:
            await self._trigger_listener_action(page, action or {'type': 'immediate'}, task_id, merchant_id, step_num)

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
                self.emit_event('task:progress', {
                    'taskId': task_id, 'merchantId': merchant_id,
                    'status': 'error',
                    'progress': 0,
                    'message': '未拦截到目标接口响应'
                })
                raise Exception(f'未拦截到目标接口响应: {api_url}')

            # 处理第一个响应
            first_resp = captured_responses[0]
            records = await _parse_and_extract(first_resp['body'])
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
                first_request = first_request_info or first_resp.get('request', {})
                if is_total_page and total_count_or_pages > 0:
                    target_total = total_count_or_pages
                elif total_count_or_pages > 0 and size_field:
                    # 从首次请求 URL 或 body 中提取 pageSize 来计算总页数
                    try:
                        page_size_val = self._get_page_size_from_request(first_request, size_field)
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
                        request_info = first_request or first_resp.get('request', {})
                        paginated_url = request_info.get('url') or first_resp['url']
                        paginated_body = request_info.get('post_data', '')
                        if field_mapping:
                            paginated_url, paginated_body = await self._apply_field_mapping(
                                paginated_url, paginated_body, field_mapping
                            )
                        inject_js = self._build_pagination_fetch_js(
                            request_info, paginated_url, paginated_body, page_field, size_field, pg
                        )
                        eval_target = request_info.get('_frame') or page
                        await eval_target.evaluate(inject_js)
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
                        pg_records = await _parse_and_extract(pg_body)
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

    @classmethod
    def _set_request_page(cls, url: str, post_data: str, page_field: str, page_num: int) -> tuple[str, str]:
        """把页码写回 JSON body；如果 body 不是 JSON，则写 URL query。"""
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

        if post_data:
            try:
                body_obj = json.loads(post_data)
                if cls._set_path_value(body_obj, page_field, page_num):
                    return url, json.dumps(body_obj, ensure_ascii=False)
            except Exception:
                pass

        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        flat_params = {}
        for k, v in params.items():
            flat_params[k] = v[-1] if v else ''
        if page_field:
            flat_params[page_field] = str(page_num)
        new_query = urlencode(flat_params, doseq=True)
        return urlunparse(parsed._replace(query=new_query)), post_data

    @staticmethod
    def _get_path_value(obj: any, path: str, default=None):
        """按点号路径读取 dict/list 值。"""
        if not path:
            return default
        current = obj
        for part in path.split('.'):
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
                current = current[int(part)]
            else:
                return default
        return current

    @classmethod
    def _set_path_value(cls, obj: any, path: str, value: any) -> bool:
        """优先按点号路径写入；找不到路径时递归替换同名字段。"""
        if not isinstance(obj, (dict, list)) or not path:
            return False

        parts = [p for p in path.split('.') if p]
        if len(parts) > 1:
            current = obj
            for part in parts[:-1]:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
                    current = current[int(part)]
                else:
                    current = None
                    break
            if isinstance(current, dict):
                current[parts[-1]] = value
                return True
            if isinstance(current, list) and parts[-1].isdigit() and int(parts[-1]) < len(current):
                current[int(parts[-1])] = value
                return True

        key = parts[-1]
        changed = False
        if isinstance(obj, dict):
            if key in obj:
                obj[key] = value
                changed = True
            for child in obj.values():
                if isinstance(child, (dict, list)):
                    changed = cls._set_path_value(child, key, value) or changed
        elif isinstance(obj, list):
            for child in obj:
                if isinstance(child, (dict, list)):
                    changed = cls._set_path_value(child, key, value) or changed
        return changed

    @classmethod
    def _find_path_value(cls, obj: any, path: str, default=None):
        """优先按路径读取；失败时递归查找同名字段。"""
        direct = cls._get_path_value(obj, path, None)
        if direct is not None:
            return direct
        key = path.split('.')[-1] if path else ''
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            for child in obj.values():
                found = cls._find_path_value(child, key, None) if isinstance(child, (dict, list)) else None
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for child in obj:
                found = cls._find_path_value(child, key, None) if isinstance(child, (dict, list)) else None
                if found is not None:
                    return found
        return default

    @classmethod
    def _get_page_size_from_request(cls, request_info: dict, size_field: str) -> int:
        """从 URL query 或 JSON body 中读取 pageSize。"""
        if not size_field:
            return 20
        qs = cls._parse_qs_from_url(request_info.get('url', ''))
        if size_field in qs and qs[size_field]:
            return max(int(qs[size_field][0]), 1)

        body = request_info.get('post_data', '')
        if body:
            try:
                body_obj = json.loads(body)
                value = cls._find_path_value(body_obj, size_field, None)
                if value is not None:
                    return max(int(value), 1)
            except Exception:
                pass
        return 20

    @classmethod
    def _build_pagination_fetch_js(cls, request_info: dict, url: str, post_data: str,
                                   page_field: str, size_field: str,
                                   page_num: int) -> str:
        """生成 JS 代码：按原请求 method/headers/body 重放下一页接口。"""
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
        method = (request_info.get('method') or 'GET').upper()
        clean_headers = cls._clean_fetch_headers(request_info.get('headers') or {})

        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        flat_params = {}
        for k, v in params.items():
            flat_params[k] = v[-1] if v else ''

        body = post_data or ''
        body_obj = None
        if body and method in ('POST', 'PUT', 'PATCH'):
            try:
                body_obj = json.loads(body)
            except Exception:
                body_obj = None

        if page_field and body_obj is not None:
            cls._set_path_value(body_obj, page_field, page_num)
            body = json.dumps(body_obj, ensure_ascii=False)
        elif page_field:
            flat_params[page_field] = str(page_num)

        new_query = urlencode(flat_params, doseq=True)
        new_url = urlunparse(parsed._replace(query=new_query))
        fetch_options = {
            'method': method,
            'headers': clean_headers,
            'credentials': 'include',
        }
        if body and method in ('POST', 'PUT', 'PATCH'):
            fetch_options['body'] = body

        return f"""
        (() => {{
            fetch({json.dumps(new_url)}, {json.dumps(fetch_options, ensure_ascii=False)})
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

            if not isinstance(data, (dict, list)):
                raise Exception(f'Expected JSON object/list, got {type(data).__name__}')

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
