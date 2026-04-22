"""
Playwright 登录引擎
- 检查凭证是否有效，有效则直接复用
- 无效则打开浏览器、自动填写账号密码
- 验证码由用户手动处理
- 登录成功后保存凭证供后续复用
"""

import logging
import time

from playwright.async_api import async_playwright

from engine.config_parser import ConfigParser

logger = logging.getLogger('finance-tools.login')

# 默认选择器
DEFAULT_SELECTORS = {
    'username': '#username',
    'password': '#password',
    'submit': '.btn-login, #submitBtn, button[type="submit"]',
}


class LoginEngine:
    """登录引擎：自动填表 → 用户处理验证码 → 保存凭证"""

    def __init__(self, merchant_repo, credential_manager, event_callback=None):
        self.merchant_repo = merchant_repo
        self.credential_mgr = credential_manager
        self.event_callback = event_callback
        self.config_parser = ConfigParser()

    async def login(self, merchant_id: str) -> dict:
        """
        执行登录流程：
        1. 检查凭证是否有效，有效则直接复用
        2. 无效则打开浏览器，自动填写账号密码
        3. 验证码由用户手动处理
        4. 检测登录成功后保存凭证

        Returns:
            {'success': bool, 'message': str}
        """
        try:
            raw_config = self.merchant_repo.get_by_id(merchant_id)
            if not raw_config:
                return {'success': False, 'message': f'商家配置不存在: {merchant_id}'}

            config = self.config_parser.parse(raw_config)
            login_url = config['login_url'] or config['url']
            target_url = config['url']  # 商家主页 URL，用于验证凭证

            self.emit_event('task:log', {
                'merchantId': merchant_id,
                'log': {'level': 'info', 'message': f'🔍 开始验证凭证有效性，访问 {target_url}', 'timestamp': time.time()}
            })

            # 1️⃣ 先通过网络请求验证凭证是否有效
            cred_valid = await self.credential_mgr.verify_credential_by_request(
                merchant_id, target_url, login_url
            )
            if cred_valid:
                self.emit_event('task:log', {
                    'merchantId': merchant_id,
                    'log': {'level': 'info', 'message': '✅ 凭证有效，无需重新登录', 'timestamp': time.time()}
                })
                return {'success': True, 'message': '凭证有效'}

            # 2️⃣ 凭证无效/不存在 → 打开浏览器自动填写 + 等待用户处理验证码
            logger.info(f"[{config.get('name', merchant_id)}] 凭证无效或不存在，需要重新登录")
            self.emit_event('task:log', {
                'merchantId': merchant_id,
                'log': {'level': 'warn', 'message': '⚠️ 凭证已失效或不存在，需要重新登录', 'timestamp': time.time()}
            })

            self.emit_event('task:progress', {
                'merchantId': merchant_id,
                'status': 'logging_in',
                'progress': 10,
                'message': '🔓 正在打开浏览器...'
            })

            cookies = await self._open_browser_and_wait_for_login(merchant_id, login_url, config)

            if not cookies:
                return {'success': False, 'message': '登录超时或未检测到登录成功'}

            logger.info(f"[{config.get('name', merchant_id)}] 登录成功，凭证已保存")
            return {'success': True, 'message': '登录成功，凭证已保存'}

        except Exception as e:
            logger.error(f"Login failed for {merchant_id}: {e}")
            self.emit_event('task:log', {
                'merchantId': merchant_id,
                'log': {'level': 'error', 'message': f'❌ 登录异常: {str(e)}', 'timestamp': time.time()}
            })
            return {'success': False, 'message': f'登录失败: {str(e)}'}

    async def test_login(self, merchant_id: str) -> tuple[bool, str]:
        """测试登录（同 login）"""
        result = await self.login(merchant_id)
        return result['success'], result['message']

    async def _open_browser_and_wait_for_login(
        self, merchant_id: str, login_url: str, config: dict
    ) -> list | None:
        """
        打开浏览器 → 注入已有 Cookie 访问商家页面 → 
        如果已登录则直接成功，否则自动填写表单 → 等待用户处理验证码 → 提取 cookie
        """

        async with async_playwright() as p:
            # 优先使用系统 Chrome，失败则用 Chromium
            launch_args = [
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process',
                '--disable-site-isolation-trials',
                '--start-maximized'
            ]
            try:
                browser = await p.chromium.launch(
                    headless=False,
                    channel='chrome',
                    args=launch_args
                )
                self.emit_event('task:log', {
                    'merchantId': merchant_id,
                    'log': {'level': 'info', 'message': '🌐 使用系统 Chrome 浏览器', 'timestamp': time.time()}
                })
            except Exception:
                browser = await p.chromium.launch(
                    headless=False,
                    args=launch_args
                )
                self.emit_event('task:log', {
                    'merchantId': merchant_id,
                    'log': {'level': 'info', 'message': '🌐 使用 Chromium 浏览器', 'timestamp': time.time()}
                })

            context = await browser.new_context(
                no_viewport=True,  # 不限制 viewport，使用实际窗口大小
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                locale='zh-CN',
                timezone_id='Asia/Shanghai',
                is_mobile=False
            )

            # 注入反检测脚本
            await self._inject_anti_detection(context)

            # 注入已保存的 Cookie + localStorage（如果有的话）
            saved_cookies, saved_origins = await self._get_saved_storage_for_playwright(merchant_id)
            if saved_cookies:
                await context.add_cookies(saved_cookies)
                self.emit_event('task:log', {
                    'merchantId': merchant_id,
                    'log': {'level': 'info', 'message': f'🍪 已注入 {len(saved_cookies)} 个已保存的 Cookie', 'timestamp': time.time()}
                })

            page = await context.new_page()

            # 恢复 localStorage（需要在页面加载后执行）
            if saved_origins:
                await self._restore_local_storage(page, saved_origins, config['url'])

            try:
                # 1️⃣ 先访问商家主页（而非登录页），看 Cookie 是否还有效
                target_url = config['url']
                self.emit_event('task:log', {
                    'merchantId': merchant_id,
                    'log': {'level': 'info', 'message': f'🌐 正在访问商家页面: {target_url}', 'timestamp': time.time()}
                })
                await page.goto(target_url, wait_until='networkidle', timeout=30000)

                current_url = page.url
                logger.info(f"访问商家页面后 URL: {current_url}")
                self.emit_event('task:log', {
                    'merchantId': merchant_id,
                    'log': {'level': 'info', 'message': f'📄 页面已加载: {current_url}', 'timestamp': time.time()}
                })

                # 提取 login_url 的路径部分用于判断
                login_path = self._extract_login_path(login_url)
                is_on_login_page = self._is_login_page(current_url, login_path)

                # 也检查 iframe 是否跳转到登录页
                if not is_on_login_page:
                    for frame in page.frames:
                        if frame.url and frame.url != 'about:blank':
                            if self._is_login_page(frame.url, login_path):
                                is_on_login_page = True
                                break

                if not is_on_login_page:
                    # Cookie 有效，页面没有跳转到登录页 → 直接成功
                    self.emit_event('task:log', {
                        'merchantId': merchant_id,
                        'log': {'level': 'info', 'message': '✅ Cookie 有效，页面未跳转到登录页', 'timestamp': time.time()}
                    })
                    cookies = await self._extract_credentials(context, merchant_id, current_url)
                    return cookies

                # 2️⃣ Cookie 失效，页面跳转到了登录页 → 自动填写表单
                self.emit_event('task:log', {
                    'merchantId': merchant_id,
                    'log': {'level': 'warn', 'message': f'⚠️ Cookie 已失效，页面跳转到了登录页: {current_url}', 'timestamp': time.time()}
                })

                # 如果当前 URL 不是登录页但 iframe 是，可能需要特殊处理
                # 确保在正确的页面上
                if self._is_login_page(current_url, login_path):
                    # 已经在登录页，直接填表
                    pass
                else:
                    # 主页面不在登录页但 iframe 在，或者需要跳转到登录页
                    # 导航到登录页
                    self.emit_event('task:log', {
                        'merchantId': merchant_id,
                        'log': {'level': 'info', 'message': f'🌐 导航到登录页: {login_url}', 'timestamp': time.time()}
                    })
                    await page.goto(login_url, wait_until='networkidle', timeout=30000)
                    current_url = page.url
                    self.emit_event('task:log', {
                        'merchantId': merchant_id,
                        'log': {'level': 'info', 'message': f'📄 登录页已加载: {current_url}', 'timestamp': time.time()}
                    })

                # 检查页面中有多少 iframe
                iframe_count = len(page.frames) - 1  # 减去 main_frame
                if iframe_count > 0:
                    self.emit_event('task:log', {
                        'merchantId': merchant_id,
                        'log': {'level': 'info', 'message': f'📋 检测到 {iframe_count} 个 iframe，将在所有 frame 中查找登录元素', 'timestamp': time.time()}
                    })

                # 自动填写账号密码
                username = config.get('username', '')
                password = config.get('password', '')
                selectors = config.get('selectors', DEFAULT_SELECTORS)

                if username or password:
                    self.emit_event('task:log', {
                        'merchantId': merchant_id,
                        'log': {'level': 'info', 'message': f'📝 开始自动填写，选择器: 用户名={selectors.get("username", "#username")}, 密码={selectors.get("password", "#password")}, 提交={selectors.get("submit", "...")}', 'timestamp': time.time()}
                    })
                    fill_result = await self._fill_login_form(page, username, password, selectors, merchant_id)
                    if fill_result['filled']:
                        self.emit_event('task:progress', {
                            'merchantId': merchant_id,
                            'status': 'logging_in',
                            'progress': 20,
                            'message': '✅ 已自动填写并点击登录，如有验证码请手动处理'
                        })
                        self.emit_event('task:log', {
                            'merchantId': merchant_id,
                            'log': {
                                'level': 'info',
                                'message': '📝 已填写账号密码并点击登录按钮',
                                'timestamp': time.time()
                            }
                        })
                        self.emit_event('task:log', {
                            'merchantId': merchant_id,
                            'log': {
                                'level': 'warn',
                                'message': '🔐 如有验证码，请在浏览器中手动完成',
                                'timestamp': time.time()
                            }
                        })
                    else:
                        self.emit_event('task:log', {
                            'merchantId': merchant_id,
                            'log': {
                                'level': 'warn',
                                'message': f'⚠️ 自动填写失败: {fill_result["error"]}',
                                'timestamp': time.time()
                            }
                        })
                        self.emit_event('task:log', {
                            'merchantId': merchant_id,
                            'log': {
                                'level': 'warn',
                                'message': '✏️ 请在浏览器中手动输入账号密码并登录',
                                'timestamp': time.time()
                            }
                        })
                else:
                    # 未配置账号密码 → 纯手动模式
                    self.emit_event('task:log', {
                        'merchantId': merchant_id,
                        'log': {'level': 'warn', 'message': '⚠️ 未配置账号密码，请在浏览器中手动登录', 'timestamp': time.time()}
                    })
                    self.emit_event('task:progress', {
                        'merchantId': merchant_id,
                        'status': 'logging_in',
                        'progress': 15,
                        'message': '⏳ 未检测到账号密码配置，请手动完成登录'
                    })

                # 轮询等待登录成功（最长 5 分钟）
                max_wait = 300  # 5 分钟
                poll_interval = 3  # 每 3 秒检查一次
                waited = 0

                self.emit_event('task:log', {
                    'merchantId': merchant_id,
                    'log': {'level': 'info', 'message': f'⏳ 等待登录完成（最长 {max_wait}s）...', 'timestamp': time.time()}
                })

                while waited < max_wait:
                    await page.wait_for_timeout(poll_interval * 1000)
                    waited += poll_interval

                    current_url = page.url

                    # 检测登录成功：URL 不再是登录页
                    is_success = not self._is_login_page(current_url, login_path)

                    # 如果主 URL 仍在登录页，检查 iframe 是否已跳转到非登录页
                    if not is_success:
                        for frame in page.frames:
                            frame_url = frame.url
                            if frame_url and frame_url != 'about:blank' and not self._is_login_page(frame_url, login_path):
                                is_success = True
                                logger.info(f"检测到 iframe 跳转: {frame_url}")
                                break

                    # 也检查页面内容是否有登录错误提示
                    content = await page.content()
                    has_error = any(err in content.lower() for err in
                                    ['密码错误', '账号不存在', '验证码错误', '登录失败'])

                    if has_error:
                        logger.warning("检测到页面有错误提示")
                        self.emit_event('task:log', {
                            'merchantId': merchant_id,
                            'log': {'level': 'error', 'message': '❌ 检测到登录错误提示（密码错误/验证码错误等），请修正后重试', 'timestamp': time.time()}
                        })
                        continue

                    if is_success and waited > 5:  # 至少等 5 秒避免误判
                        logger.info(f"检测到登录成功! URL: {current_url} (等待 {waited}s)")

                        # 提取完整凭证（cookies + localStorage）
                        cookies = await self._extract_credentials(context, merchant_id, current_url)

                        self.emit_event('task:progress', {
                            'merchantId': merchant_id,
                            'status': 'logged_in',
                            'progress': 50,
                            'message': '✅ 登录成功，凭证已保存'
                        })
                        self.emit_event('task:log', {
                            'merchantId': merchant_id,
                            'log': {'level': 'info',
                                    'message': f'✅ 登录成功 ({waited}s)，已保存 {len(cookies)} 个 cookie',
                                    'timestamp': time.time()}
                        })

                        return cookies

                    # 每 30 秒提醒一次还在等
                    if waited % 30 == 0 and waited > 0:
                        logger.info(f"等待用户登录... 已等待 {waited}s/{max_wait}s, 当前URL: {current_url}")
                        self.emit_event('task:progress', {
                            'merchantId': merchant_id,
                            'status': 'logging_in',
                            'progress': 25,
                            'message': f'⏳ 等待中... 已等待 {waited}s / 最长 {max_wait}s'
                        })

                # 超时
                logger.warning(f"登录等待超时 ({max_wait}s)，当前URL: {page.url}")
                self.emit_event('task:log', {
                    'merchantId': merchant_id,
                    'log': {'level': 'error', 'message': f'⏰ 登录超时（{max_wait}s 未完成），当前页面: {page.url}', 'timestamp': time.time()}
                })
                self.emit_event('task:progress', {
                    'merchantId': merchant_id,
                    'status': 'error',
                    'progress': 0,
                    'message': '⏰ 登录超时（5分钟未完成）'
                })
                return None

            finally:
                await context.close()
                await browser.close()

    async def _fill_login_form(
        self, page, username: str, password: str, selectors: dict, merchant_id: str = ''
    ) -> dict:
        """
        使用 Playwright 自动填写登录表单（支持 iframe）
        
        查找策略：
        1. 先在主 frame 查找
        2. 找不到则遍历所有 iframe 查找
        3. 验证码等 iframe 内元素也需要用户在 iframe 内手动操作
        
        Args:
            page: Playwright Page 对象
            username: 用户名
            password: 密码
            selectors: CSS 选择器字典 {'username': ..., 'password': ..., 'submit': ...}
            
        Returns:
            {'filled': bool, 'error': str}
        """
        try:
            user_sel = selectors.get('username', DEFAULT_SELECTORS['username'])
            pass_sel = selectors.get('password', DEFAULT_SELECTORS['password'])

            # 收集所有 frame（主 frame + 子 iframe）
            frames = [page.main_frame] + page.frames
            # 去重（main_frame 可能也在 page.frames 中）
            seen = set()
            unique_frames = []
            for f in frames:
                if id(f) not in seen:
                    seen.add(id(f))
                    unique_frames.append(f)

            logger.info(f"Searching across {len(unique_frames)} frames for login form elements")

            # 找到用户名输入框所在的 frame
            user_frame = None
            pass_frame = None

            # 填写用户名
            if username:
                user_frame, user_input = await self._locate_element(unique_frames, user_sel)
                if user_frame is None:
                    self.emit_event('task:log', {
                        'merchantId': merchant_id,
                        'log': {'level': 'warn', 'message': f'⚠️ 找不到用户名输入框 ({user_sel})，已搜索所有 {len(unique_frames)} 个 frame', 'timestamp': time.time()}
                    })
                    return {'filled': False, 'error': f'找不到用户名输入框 ({user_sel})，包括所有 iframe'}

                # 如果匹配到的是容器 div 而非 input，尝试在容器内查找 input
                user_input = await self._ensure_input_element(user_frame, user_input, user_sel)

                frame_name = '主页面' if user_frame == page.main_frame else f'iframe({user_frame.url[:60]})'
                await user_input.click()
                await user_input.fill('')
                await user_input.type(username, delay=50)
                logger.info(f"Username filled in {frame_name} with selector: {user_sel}")
                self.emit_event('task:log', {
                    'merchantId': merchant_id,
                    'log': {'level': 'info', 'message': f'✏️ 已填写用户名 → {frame_name} [{user_sel}]', 'timestamp': time.time()}
                })

            # 填写密码
            if password:
                pass_frame, pass_input = await self._locate_element(unique_frames, pass_sel)
                if pass_frame is None:
                    self.emit_event('task:log', {
                        'merchantId': merchant_id,
                        'log': {'level': 'warn', 'message': f'⚠️ 找不到密码输入框 ({pass_sel})，已搜索所有 {len(unique_frames)} 个 frame', 'timestamp': time.time()}
                    })
                    return {'filled': False, 'error': f'找不到密码输入框 ({pass_sel})，包括所有 iframe'}

                # 如果匹配到的是容器 div 而非 input，尝试在容器内查找 input
                pass_input = await self._ensure_input_element(pass_frame, pass_input, pass_sel)

                frame_name = '主页面' if pass_frame == page.main_frame else f'iframe({pass_frame.url[:60]})'
                await pass_input.click()
                await pass_input.fill('')
                await pass_input.type(password, delay=30)
                logger.info(f"Password filled in {frame_name} with selector: {pass_sel}")
                self.emit_event('task:log', {
                    'merchantId': merchant_id,
                    'log': {'level': 'info', 'message': f'🔑 已填写密码 → {frame_name} [{pass_sel}]', 'timestamp': time.time()}
                })

            # 点击登录按钮
            submit_sel = selectors.get('submit', DEFAULT_SELECTORS['submit'])
            submit_frame, submit_btn = await self._locate_element(unique_frames, submit_sel)
            if submit_frame is not None:
                # 确保匹配到的是可点击元素（button/a），而非容器
                submit_btn = await self._ensure_clickable_element(submit_frame, submit_btn, submit_sel)
                frame_name = '主页面' if submit_frame == page.main_frame else f'iframe({submit_frame.url[:60]})'
                await submit_btn.click()
                logger.info(f"Submit button clicked in {frame_name} with selector: {submit_sel}")
                self.emit_event('task:log', {
                    'merchantId': merchant_id,
                    'log': {'level': 'info', 'message': f'🔘 已点击登录按钮 → {frame_name} [{submit_sel}]', 'timestamp': time.time()}
                })
            else:
                logger.warning(f"Submit button not found ({submit_sel})，用户需手动点击登录")
                self.emit_event('task:log', {
                    'merchantId': merchant_id,
                    'log': {'level': 'warn', 'message': f'⚠️ 找不到登录按钮 ({submit_sel})，请手动点击登录', 'timestamp': time.time()}
                })
                # 尝试回车提交作为备选
                if pass_frame is not None:
                    await pass_frame.locator(pass_sel).first.press('Enter')
                    logger.info("Tried pressing Enter on password field as fallback")
                    self.emit_event('task:log', {
                        'merchantId': merchant_id,
                        'log': {'level': 'info', 'message': '↩️ 已尝试在密码框按回车提交', 'timestamp': time.time()}
                    })

            return {'filled': True, 'error': ''}

        except Exception as e:
            error_msg = str(e)
            logger.warning(f"Auto-fill failed: {error_msg}")
            return {'filled': False, 'error': error_msg}

    async def _locate_element(self, frames: list, selector: str, timeout: int = 3000):
        """
        在多个 frame 中定位元素
        
        Args:
            frames: frame 列表（主 frame + iframe）
            selector: CSS 选择器
            timeout: 每个 frame 的等待超时（毫秒）
            
        Returns:
            (frame, locator) 元组，找不到返回 (None, None)
        """
        for frame in frames:
            try:
                locator = frame.locator(selector).first
                # 等待元素出现（短超时，快速跳过不包含该元素的 frame）
                await locator.wait_for(state='visible', timeout=timeout)
                return frame, locator
            except Exception:
                continue
        return None, None

    async def _ensure_input_element(self, frame, locator, original_selector: str):
        """
        确保定位到的是可输入的元素，如果不是则自动在容器内查找
        
        覆盖场景：
        - 携程: #rc_select_0 同时在 div 和 input 上 → 匹配到 div，需找内部 input
        - Ant Design Select: div[role="combobox"] → 内部有隐藏 input
        - contenteditable div → 可直接输入但标签不是 input
        - 自定义组件容器 → 需在内部找 input/textarea
        
        Args:
            frame: Playwright Frame 对象
            locator: 当前定位到的 locator
            original_selector: 原始 CSS 选择器
            
        Returns:
            可输入的 locator（原 locator 或容器内找到的 input）
        """
        try:
            tag_name = await locator.evaluate('el => el.tagName.toLowerCase()')
            
            # 本身就是 input / textarea → 直接用
            if tag_name in ('input', 'textarea'):
                return locator

            # contenteditable 元素 → 可直接用 Playwright 的 fill/type
            is_editable = await locator.evaluate(
                'el => el.isContentEditable || el.getAttribute("contenteditable") === "true"'
            )
            if is_editable:
                logger.info(f"选择器 {original_selector} 匹配到 contenteditable <{tag_name}>，可直接输入")
                return locator

            # role="textbox" 的元素 → 可输入
            role = await locator.evaluate('el => el.getAttribute("role") || ""')
            if role == 'textbox':
                logger.info(f"选择器 {original_selector} 匹配到 role=textbox 的 <{tag_name}>，可直接输入")
                return locator

            # 匹配到的是容器元素（div / span 等），按优先级在内部查找可输入子元素
            logger.info(f"选择器 {original_selector} 匹配到 <{tag_name}>，在容器内查找可输入子元素")

            # 优先级1: type=text/password/email/tel 的 input（排除 hidden/submit/button）
            for input_type in ['input[type="text"]', 'input[type="password"]', 'input[type="email"]',
                               'input[type="tel"]', 'input[type="number"]', 'input:not([type])']:
                try:
                    inner = locator.locator(input_type).first
                    await inner.wait_for(state='visible', timeout=1000)
                    inner_tag = await inner.evaluate('el => el.tagName.toLowerCase()')
                    logger.info(f"在容器内找到 <{inner_tag}>({input_type}) 子元素")
                    return inner
                except Exception:
                    continue

            # 优先级2: 任意可见 input
            try:
                inner = locator.locator('input:visible').first
                await inner.wait_for(state='visible', timeout=1000)
                logger.info(f"在容器内找到可见 input 子元素")
                return inner
            except Exception:
                pass

            # 优先级3: textarea
            try:
                inner = locator.locator('textarea').first
                await inner.wait_for(state='visible', timeout=1000)
                logger.info(f"在容器内找到 textarea 子元素")
                return inner
            except Exception:
                pass

            # 优先级4: contenteditable 子元素
            try:
                inner = locator.locator('[contenteditable="true"]').first
                await inner.wait_for(state='visible', timeout=1000)
                logger.info(f"在容器内找到 contenteditable 子元素")
                return inner
            except Exception:
                pass

            # 都没找到 → 先点击容器激活，再返回原始 locator 尝试 type
            logger.warning(f"容器内未找到可输入子元素，尝试点击激活后直接输入")
            try:
                await locator.click()
                await frame.wait_for_timeout(500)
            except Exception:
                pass
            return locator

        except Exception as e:
            logger.warning(f"检查元素类型失败: {e}，使用原始 locator")
            return locator

    async def _ensure_clickable_element(self, frame, locator, original_selector: str):
        """
        确保定位到的是可点击的按钮元素，如果不是则在容器内查找
        
        覆盖场景：
        - 选择器匹配到容器 div 而非 button → 在内部找 button / a / [role="button"]
        - Ant Design: .btn-wrap 匹配到外层 → 内部有 button
        
        Args:
            frame: Playwright Frame 对象
            locator: 当前定位到的 locator
            original_selector: 原始 CSS 选择器
            
        Returns:
            可点击的 locator
        """
        try:
            tag_name = await locator.evaluate('el => el.tagName.toLowerCase()')
            
            # 本身就是 button / a / input[type=submit] → 直接用
            if tag_name in ('button', 'a'):
                return locator
            if tag_name == 'input':
                input_type = await locator.evaluate('el => el.getAttribute("type") || ""')
                if input_type in ('submit', 'button', 'image'):
                    return locator

            # role="button" → 可点击
            role = await locator.evaluate('el => el.getAttribute("role") || ""')
            if role == 'button':
                return locator

            # 匹配到容器，在内部查找可点击元素
            logger.info(f"提交选择器 {original_selector} 匹配到 <{tag_name}>，在容器内查找可点击子元素")

            # 优先级1: button
            for sel in ['button', 'a[role="button"]', '[role="button"]', 'input[type="submit"]', 'a']:
                try:
                    inner = locator.locator(sel).first
                    await inner.wait_for(state='visible', timeout=1500)
                    logger.info(f"在容器内找到 {sel} 子元素")
                    return inner
                except Exception:
                    continue

            # 没找到 → 返回原始 locator 尝试直接 click
            logger.warning(f"容器内未找到可点击子元素，尝试直接点击原始元素")
            return locator

        except Exception as e:
            logger.warning(f"检查元素类型失败: {e}，使用原始 locator")
            return locator

    def emit_event(self, event: str, data: dict):
        """发送事件通知"""
        if self.event_callback:
            self.event_callback(event, data)

    async def _inject_anti_detection(self, context):
        """注入反自动化检测脚本（参考 ota_credential_tool.py）"""
        anti_detection_script = """
            // 移除 webdriver 标识
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            
            // 添加 chrome 对象
            window.navigator.chrome = {
                runtime: {},
                loadTimes: function() {},
                csi: function() {},
                app: {}
            };
            
            // 修改 plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [
                    {
                        0: {type: "application/x-google-chrome-pdf", suffixes: "pdf", description: "Portable Document Format"},
                        description: "Portable Document Format",
                        filename: "internal-pdf-viewer",
                        length: 1,
                        name: "Chrome PDF Plugin"
                    },
                    {
                        0: {type: "application/pdf", suffixes: "pdf", description: ""},
                        description: "",
                        filename: "mhjfbmdgcfjbbpaeojofohoefgiehjai",
                        length: 1,
                        name: "Chrome PDF Viewer"
                    },
                    {
                        0: {type: "application/x-nacl", suffixes: "", description: "Native Client Executable"},
                        1: {type: "application/x-pnacl", suffixes: "", description: "Portable Native Client Executable"},
                        description: "",
                        filename: "internal-nacl-plugin",
                        length: 2,
                        name: "Native Client"
                    }
                ]
            });
            
            // 修改 languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['zh-CN', 'zh', 'en-US', 'en']
            });
            
            // 伪装 WebGL 指纹
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                if (parameter === 37445) return 'Intel Inc.';
                if (parameter === 37446) return 'Intel Iris OpenGL Engine';
                return getParameter.call(this, parameter);
            };
            
            // 添加 connection 属性
            Object.defineProperty(navigator, 'connection', {
                get: () => ({
                    effectiveType: '4g',
                    rtt: 50,
                    downlink: 10,
                    saveData: false
                })
            });
        """
        await context.add_init_script(anti_detection_script)
        logger.info("Anti-detection script injected")

    async def _extract_credentials(self, context, merchant_id: str, current_url: str) -> list[dict]:
        """
        提取完整凭证（cookies + localStorage），参考 ota_credential_tool.py 的 storage_state()
        
        Returns:
            Cookie 列表（兼容后续流程）
        """
        try:
            # 获取完整存储状态（cookies + localStorage + origins）
            storage_state = await context.storage_state()
            cookies = storage_state.get('cookies', [])
            origins = storage_state.get('origins', [])

            logger.info(f"提取凭证: {len(cookies)} 个 Cookie, {len(origins)} 个 Origin 的 localStorage")

            # 保存凭证到数据库（内部会同步更新 merchants 表的 last_login_at 和 credential_expires_at）
            await self.credential_mgr.save_credentials(
                merchant_id, cookies, current_url,
                storage_state=storage_state  # 传递完整存储状态
            )

            self.emit_event('task:progress', {
                'merchantId': merchant_id,
                'status': 'logged_in',
                'progress': 50,
                'message': '✅ 登录成功，凭证已保存'
            })
            self.emit_event('task:log', {
                'merchantId': merchant_id,
                'log': {'level': 'info', 'message': f'✅ 已保存 {len(cookies)} 个 Cookie + {len(origins)} 个 localStorage', 'timestamp': time.time()}
            })

            return cookies

        except Exception as e:
            logger.warning(f"storage_state() 失败: {e}，降级为 cookies()")
            cookies = await context.cookies()
            # save_credentials 内部会同步更新 merchants 表的 last_login_at 和 credential_expires_at
            await self.credential_mgr.save_credentials(merchant_id, cookies, current_url)

            self.emit_event('task:progress', {
                'merchantId': merchant_id,
                'status': 'logged_in',
                'progress': 50,
                'message': '✅ 登录成功，凭证已保存'
            })
            self.emit_event('task:log', {
                'merchantId': merchant_id,
                'log': {'level': 'info', 'message': f'✅ 已保存 {len(cookies)} 个 Cookie', 'timestamp': time.time()}
            })

            return cookies

    def _extract_login_path(self, login_url: str) -> str:
        """从 login_url 提取路径部分，用于模糊匹配"""
        if not login_url:
            return '/login'
        try:
            from urllib.parse import urlparse
            parsed = urlparse(login_url)
            return parsed.path.rstrip('/') or '/login'
        except Exception:
            return '/login'

    def _is_login_page(self, url: str, login_path: str = '') -> bool:
        """
        判断 URL 是否是登录页面
        
        Args:
            url: 当前页面 URL
            login_path: 商家配置的登录页路径（如 /login, /ebklogin）
        """
        if not url or url == 'about:blank':
            return False

        url_lower = url.lower()

        # 方式1: 匹配商家配置的 login_url 路径
        if login_path and login_path in url_lower:
            return True

        # 方式2: 通用登录路径兜底
        generic_login_paths = ['/login', '/signin', '/sign-in', '/auth/login', '/sso', '/cas/']
        for path in generic_login_paths:
            if path in url_lower:
                return True

        return False

    async def _get_saved_storage_for_playwright(self, merchant_id: str) -> tuple[list[dict], list[dict]]:
        """
        获取已保存的 Cookie 和 localStorage，转换为 Playwright 可用格式
        
        Returns:
            (cookies, origins) 元组
            - cookies: Playwright add_cookies 格式的列表
            - origins: localStorage 数据列表 [{origin, localStorage: [{name, value}]}]
        """
        try:
            cred = self.credential_mgr.get_credentials(merchant_id)
            if not cred or not cred.get('cookies'):
                return [], []

            playwright_cookies = []
            for c in cred['cookies']:
                pc = {
                    'name': c.get('name', ''),
                    'value': c.get('value', ''),
                    'domain': c.get('domain', ''),
                    'path': c.get('path', '/'),
                }
                if c.get('expires') and c['expires'] > 0:
                    pc['expires'] = c['expires']
                if c.get('httpOnly'):
                    pc['httpOnly'] = True
                if c.get('secure'):
                    pc['secure'] = True
                if c.get('sameSite'):
                    pc['sameSite'] = c['sameSite'].capitalize()
                playwright_cookies.append(pc)

            # 获取 localStorage 数据
            origins = []
            try:
                storage_state = self.credential_mgr.get_storage_state(merchant_id)
                if storage_state:
                    origins = storage_state.get('origins', [])
            except Exception as e:
                logger.warning(f"获取 localStorage 数据失败: {e}")

            return playwright_cookies, origins

        except Exception as e:
            logger.warning(f"获取已保存存储状态失败: {e}")
            return [], []

    async def _restore_local_storage(self, page, origins: list[dict], target_url: str):
        """恢复 localStorage 数据到页面"""
        if not origins:
            return

        try:
            from urllib.parse import urlparse
            target_origin = urlparse(target_url).scheme + '://' + urlparse(target_url).hostname

            restored_count = 0
            for origin_data in origins:
                origin = origin_data.get('origin', '')
                # 只恢复与目标网站同源的 localStorage
                if target_origin not in origin:
                    continue

                local_storage = origin_data.get('localStorage', [])
                if not local_storage:
                    continue

                # 通过 JS 恢复 localStorage
                for item in local_storage:
                    name = item.get('name', '')
                    value = item.get('value', '')
                    if name:
                        try:
                            await page.evaluate(
                                '([name, value]) => localStorage.setItem(name, value)',
                                [name, value]
                            )
                            restored_count += 1
                        except Exception:
                            pass

            if restored_count > 0:
                logger.info(f"已恢复 {restored_count} 个 localStorage 条目")
                self.emit_event('task:log', {
                    'merchantId': '',
                    'log': {'level': 'info', 'message': f'💾 已恢复 {restored_count} 个 localStorage 条目', 'timestamp': time.time()}
                })

        except Exception as e:
            logger.warning(f"恢复 localStorage 失败: {e}")
