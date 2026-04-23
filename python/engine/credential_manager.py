"""
凭证管理器
负责 Cookie/Token 的加密存储、有效期管理和自动刷新
"""

import json
import logging
import time
from typing import Optional

logger = logging.getLogger('finance-tools.credential')


class CredentialManager:
    """凭证（Cookie/Token）管理器"""

    # Cookie 默认有效期（秒），默认 2 小时
    DEFAULT_EXPIRY = 60 * 24 * 60 * 60

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._encryption_key: Optional[bytes] = None

    def _get_encryption_key(self) -> bytes:
        """获取/生成加密密钥"""
        if self._encryption_key:
            return self._encryption_key

        try:
            from utils.crypto import get_or_create_key
            self._encryption_key = get_or_create_key()
        except Exception as e:
            logger.warning(f"Encryption key generation failed: {e}, using fallback")
            # 使用固定密钥（仅用于开发环境）
            self._encryption_key = b'finance-tools-dev-key-32bytes!!'

        return self._encryption_key

    async def save_credentials(
            self,
            merchant_id: str,
            cookies: list[dict],
            current_url: str,
            expiry_seconds: int | None = None,
            storage_state: dict | None = None
    ) -> dict:
        """
        保存登录凭证到数据库
        
        Args:
            merchant_id: 商家 ID
            cookies: Cookie 列表
            current_url: 当前页面 URL
            expiry_seconds: 自定义过期时间
            storage_state: 完整存储状态（cookies + localStorage），参考 Playwright storage_state()
            
        Returns:
            保存的凭证记录
        """
        try:
            from utils.crypto import encrypt_data

            key = self._get_encryption_key()
            expiry = expiry_seconds or self.DEFAULT_EXPIRY

            # 提取关键 Cookie 信息
            cookie_str = '; '.join([f"{c.get('name', '')}={c.get('value', '')}" for c in cookies])

            # 加密存储
            encrypted_cookies = encrypt_data(json.dumps(cookies), key)
            encrypted_cookie_string = encrypt_data(cookie_str, key)

            # 加密完整存储状态（包含 localStorage）
            encrypted_storage_state = ''
            if storage_state:
                encrypted_storage_state = encrypt_data(json.dumps(storage_state), key)
                logger.info(f"Storage state saved with {len(storage_state.get('origins', []))} origins")

            credential_record = {
                'merchant_id': merchant_id,
                'encrypted_cookies': encrypted_cookies,
                'encrypted_cookie_string': encrypted_cookie_string,
                'encrypted_storage_state': encrypted_storage_state,
                'cookie_domains': list(set([c.get('domain', '') for c in cookies if c.get('domain')])),
                'expires_at': int(time.time()) + expiry,
                'created_at': int(time.time()),
                'source_url': current_url,
                'is_valid': True
            }

            # 保存到数据库
            from db.repositories import CredentialRepository
            repo = CredentialRepository(self.db_path)
            saved = repo.upsert(merchant_id, credential_record)

            # 保存凭证过期时间，供商家列表查询凭证状态
            self._update_merchant_credential_expiry(merchant_id, int(credential_record['expires_at']))

            logger.info(f"Credentials saved for merchant {merchant_id}, expires in {expiry}s")
            return saved

        except Exception as e:
            logger.error(f"Failed to save credentials: {e}")
            raise

    def get_credentials(self, merchant_id: str) -> Optional[dict]:
        """
        获取商家凭证
        
        Args:
            merchant_id: 商家 ID
            
        Returns:
            凭证信息或 None
        """
        try:
            from utils.crypto import decrypt_data
            from db.repositories import CredentialRepository

            repo = CredentialRepository(self.db_path)
            record = repo.get_by_merchant(merchant_id)

            if not record:
                return None

            # 检查是否过期
            if record.get('expires_at', 0) < time.time():
                logger.info(f"Credentials expired for merchant {merchant_id}")
                repo.invalidate(merchant_id)
                return None

            # 解密 Cookie
            key = self._get_encryption_key()
            decrypted = decrypt_data(record['encrypted_cookies'], key)
            cookies = json.loads(decrypted)

            return {
                **record,
                'cookies': cookies,
                'is_expired': False
            }

        except Exception as e:
            logger.error(f"Failed to get credentials: {e}")
            return None

    def get_storage_state(self, merchant_id: str) -> Optional[dict]:
        """
        获取商家的完整存储状态（cookies + localStorage）
        
        Args:
            merchant_id: 商家 ID
            
        Returns:
            storage_state dict 或 None
        """
        try:
            from utils.crypto import decrypt_data
            from db.repositories import CredentialRepository

            repo = CredentialRepository(self.db_path)
            record = repo.get_by_merchant(merchant_id)

            if not record or not record.get('encrypted_storage_state'):
                return None

            # 解密存储状态
            key = self._get_encryption_key()
            decrypted = decrypt_data(record['encrypted_storage_state'], key)
            return json.loads(decrypted)

        except Exception as e:
            logger.warning(f"Failed to get storage state: {e}")
            return None

    def get_cookie_header(self, merchant_id: str) -> Optional[str]:
        """
        获取用于 HTTP 请求的 Cookie Header 字符串
        
        Args:
            merchant_id: 商家 ID
            
        Returns:
            Cookie 字符串 (name=value; name2=value2) 或 None
        """
        cred = self.get_credentials(merchant_id)
        if not cred or not cred.get('cookies'):
            return None

        cookies = cred['cookies']
        cookie_parts = [f"{c['name']}={c['value']}" for c in cookies]
        return '; '.join(cookie_parts)

    def is_credential_valid(self, merchant_id: str) -> bool:
        """检查凭证是否有效（仅检查数据库记录，不发起网络请求）"""
        cred = self.get_credentials(merchant_id)
        return cred is not None and not cred.get('is_expired')

    async def verify_credential_by_request(
            self, merchant_id: str, url: str, login_url: str = ''
    ) -> bool:
        """
        通过实际 HTTP 请求验证凭证是否有效
        
        原理：用已保存的 Cookie 访问商家页面，如果被重定向到登录页则凭证已失效
        
        Args:
            merchant_id: 商家 ID
            url: 商家页面 URL（通常是 dashboard 首页）
            login_url: 登录页面 URL（用于判断是否被重定向到登录页）
            
        Returns:
            True = 凭证有效，False = 凭证无效
        """
        cred = self.get_credentials(merchant_id)
        if not cred:
            logger.info(f"凭证验证: 商家 {merchant_id} 无保存的凭证")
            return False

        cookies = cred.get('cookies', [])
        if not cookies:
            logger.info(f"凭证验证: 商家 {merchant_id} Cookie 列表为空")
            return False

        # 从 login_url 提取路径部分用于模糊匹配
        login_path = ''
        if login_url:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(login_url)
                login_path = parsed.path.rstrip('/')  # e.g. /login, /ebklogin, /user/signin
            except Exception:
                pass

        try:
            import httpx

            cookie_header = '; '.join([f"{c.get('name', '')}={c.get('value', '')}" for c in cookies])

            logger.info(f"凭证验证: 请求 {url}，Cookie 数量: {len(cookies)}")

            async with httpx.AsyncClient(
                    follow_redirects=False,
                    timeout=15.0,
                    verify=False
            ) as client:
                response = await client.get(
                    url,
                    headers={
                        'Cookie': cookie_header,
                        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
                    }
                )

                logger.info(f"凭证验证: 响应状态码 {response.status_code}")

                # 3xx 重定向 → 检查是否跳到了登录页
                if response.status_code in (301, 302, 303, 307, 308):
                    redirect_url = response.headers.get('location', '')
                    logger.info(f"凭证验证: 重定向到 {redirect_url}")

                    # 用商家配置的 login_url 路径模糊匹配
                    is_login_redirect = False

                    # 方式1: login_url 路径模糊匹配（核心逻辑）
                    if login_path and login_path in redirect_url:
                        is_login_redirect = True
                        logger.info(f"凭证验证: 重定向 URL 包含登录路径 {login_path}")

                    # 方式2: 通用登录路径匹配（兜底）
                    if not is_login_redirect:
                        generic_login_paths = ['/login', '/signin', '/sign-in', '/auth', '/sso', '/cas/']
                        redirect_lower = redirect_url.lower()
                        for path in generic_login_paths:
                            if path in redirect_lower:
                                is_login_redirect = True
                                logger.info(f"凭证验证: 重定向 URL 包含通用登录路径 {path}")
                                break

                    if is_login_redirect:
                        logger.info(f"凭证验证失败: 访问 {url} 被重定向到登录页 {redirect_url}")
                        self.invalidate(merchant_id)
                        return False

                    # 重定向到其他页面（非登录页），说明凭证有效
                    logger.info(f"凭证验证: 重定向到非登录页，凭证有效")
                    return True

                # 200 → 检查响应内容
                if response.status_code == 200:
                    content = response.text.lower()
                    content_type = response.headers.get('content-type', '')

                    # 如果是 JSON 响应，检查是否包含未认证的错误码
                    if 'application/json' in content_type:
                        try:
                            json_data = response.json()
                            code = json_data.get('code', json_data.get('status', ''))
                            msg = json_data.get('message', json_data.get('msg', ''))
                            # 常见未认证错误码
                            if code in (401, 403, 4010, 4011) or str(code) in ('401', '403', '4010', '4011'):
                                logger.info(f"凭证验证失败: API 返回未认证 code={code}, msg={msg}")
                                self.invalidate(merchant_id)
                                return False
                            # 有有效数据返回，凭证有效
                            return True
                        except Exception:
                            pass

                    # 如果是 HTML 响应，检查是否包含登录表单
                    if 'text/html' in content_type or '<html' in content or '<!doctype' in content:
                        has_login_form = any(indicator in content for indicator in [
                            'type="password"', 'name="password"',
                            'id="login"', 'class="login-form"', 'login-page'
                        ])
                        has_dashboard = any(kw in content for kw in [
                            'dashboard', 'welcome', '首页', '控制台', '工作台'
                        ])
                        if has_login_form and not has_dashboard:
                            logger.info(f"凭证验证失败: 页面包含登录表单")
                            self.invalidate(merchant_id)
                            return False

                    # SPA 应用通常返回空壳 HTML，无法通过 HTTP 内容判断登录状态
                    # 必须用浏览器实际访问才能确认，返回 False 触发浏览器验证流程
                    logger.info(f"凭证验证: 200 响应无法确认登录状态，需要打开浏览器验证")
                    return False

                # 401/403 → 凭证无效
                if response.status_code in (401, 403):
                    logger.info(f"凭证验证失败: HTTP {response.status_code}")
                    self.invalidate(merchant_id)
                    return False

                # 其他状态码，保守认为有效
                logger.info(f"凭证验证: 状态码 {response.status_code}，保守认为有效")
                return True

        except ImportError:
            logger.warning("httpx 未安装，降级为仅检查数据库凭证有效期")
            return self.is_credential_valid(merchant_id)
        except Exception as e:
            logger.warning(f"凭证网络验证异常: {e}，降级为数据库检查")
            # 网络异常时保守处理：有未过期凭证认为有效，否则无效
            return self.is_credential_valid(merchant_id)

    def invalidate(self, merchant_id: str):
        """标记凭证为失效"""
        try:
            from db.repositories import CredentialRepository
            repo = CredentialRepository(self.db_path)
            repo.invalidate(merchant_id)
            # 同步清空 merchants 表的凭证过期时间
            self._update_merchant_credential_expiry(merchant_id, 0)
        except Exception as e:
            logger.error(f"Failed to invalidate credentials: {e}")

    def _update_merchant_credential_expiry(self, merchant_id: str, expires_at: int):
        """更新 merchants 表的 credential_expires_at 字段"""
        try:
            from db.repositories import MerchantRepository
            repo = MerchantRepository(self.db_path)
            repo.update_last_login(merchant_id, int(time.time()), credential_expires_at=expires_at)
        except Exception as e:
            logger.warning(f"Failed to update merchant credential_expires_at: {e}")

    def refresh_if_needed(self, merchant_id: str, threshold_seconds: int = 300) -> bool:
        """
        如果凭证即将过期则刷新（返回 True 表示需要重新登录）
        
        Args:
            merchant_id: 商家 ID
            threshold_seconds: 过期前多少秒视为需要刷新
            
        Returns:
            是否需要重新登录
        """
        cred = self.get_credentials(merchant_id)
        if not cred:
            return True

        remaining = cred.get('expires_at', 0) - int(time.time())
        return remaining < threshold_seconds
