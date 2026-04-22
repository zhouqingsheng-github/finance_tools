"""
AES-256-GCM 加解密工具
用于 Cookie/密码等敏感数据的加密存储
"""

import base64
import hashlib
import hmac
import logging
import os
from typing import Optional

logger = logging.getLogger('finance-tools.crypto')


# 密钥派生参数
KEY_LENGTH = 32  # AES-256 需要 32 字节密钥
SALT_LENGTH = 16  # 盐值长度
ITERATIONS = 100000  # PBKDF2 迭代次数


def _get_machine_fingerprint() -> str:
    """
    获取机器指纹（用于密钥派生）
    结合多个硬件特征生成唯一标识
    """
    try:
        import platform
        import uuid
        
        components = [
            platform.node(),
            platform.machine(),
            platform.processor(),
            str(uuid.getnode())
        ]
        
        fingerprint = '|'.join([c for c in components if c])
        return hashlib.sha256(fingerprint.encode()).hexdigest()
    
    except Exception:
        # 回退方案：使用固定字符串 + 用户目录哈希
        user_dir = os.path.expanduser('~')
        return hashlib.sha256(f"finance-tools-fallback:{user_dir}".encode()).hexdigest()


def get_or_create_key() -> bytes:
    """
    获取或创建加密密钥
    
    密钥存储位置：
    - macOS: ~/Library/Application Support/finance-tools/.key
    - Linux: ~/.config/finance-tools/.key
    - Windows: %APPDATA%/finance-tools/.key
    
    Returns:
        32 字节的 AES 密钥
    """
    import json
    
    key_file_path = _get_key_file_path()
    
    try:
        if os.path.exists(key_file_path):
            with open(key_file_path, 'r') as f:
                stored = json.load(f)
                
            # 验证密钥完整性
            if _verify_stored_key(stored):
                return base64.b64decode(stored['key'])
            
            logger.warning("Stored key verification failed, generating new key")
        
        # 生成新密钥
        new_key = os.urandom(KEY_LENGTH)
        salt = os.urandom(SALT_LENGTH)
        
        stored_data = {
            'key': base64.b64encode(new_key).decode(),
            'salt': base64.b64encode(salt).decode(),
            'fingerprint': _get_machine_fingerprint(),
            'created_at': __import__('time').time(),
            'version': 1
        }
        
        # 计算完整性校验值
        mac = hmac.new(
            new_key,
            f"{stored_data['salt']}{stored_data['fingerprint']}{stored_data['created_at']}".encode(),
            hashlib.sha256
        ).hexdigest()
        stored_data['mac'] = mac
        
        # 确保目录存在
        os.makedirs(os.path.dirname(key_file_path), exist_ok=True)
        
        # 设置文件权限（仅当前用户可读写）
        with open(key_file_path, 'w') as f:
            json.dump(stored_data, f, indent=2)
        
        os.chmod(key_file_path, 0o600)
        
        logger.info(f"Encryption key created and stored at {key_file_path}")
        return new_key
        
    except Exception as e:
        logger.error(f"Key generation error: {e}")
        raise


def _get_key_file_path() -> str:
    """获取密钥文件路径"""
    import platform
    
    system = platform.system()
    
    if system == 'Darwin':
        base_dir = os.path.expanduser('~/Library/Application Support/finance-tools')
    elif system == 'Linux':
        base_dir = os.path.expanduser('~/.config/finance-tools')
    elif system == 'Windows':
        base_dir = os.path.join(os.environ.get('APPDATA', ''), 'finance-tools')
    else:
        base_dir = os.path.expanduser('~/.finance-tools')
    
    return os.path.join(base_dir, '.key')


def _verify_stored_key(stored: dict) -> bool:
    """验证存储的密钥是否有效且未被篡改"""
    try:
        expected_fp = _get_machine_fingerprint()
        
        if stored.get('fingerprint') != expected_fp:
            return False
        
        key = base64.b64decode(stored['key'])
        check_string = f"{stored['salt']}{stored['fingerprint']}{stored['created_at']}"
        expected_mac = hmac.new(key, check_string.encode(), hashlib.sha256).hexdigest()
        
        return hmac.compare_digest(expected_mac, stored.get('mac', ''))
    
    except Exception:
        return False


def encrypt_data(plaintext: str | bytes, key: bytes) -> str:
    """
    使用 AES-256-GCM 加密数据
    
    Args:
        plaintext: 明文数据（字符串或字节）
        key: 32 字节加密密钥
        
    Returns:
        Base64 编码的密文（包含 nonce 和 tag）
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        return _fallback_encrypt(plaintext, key)
    
    if isinstance(plaintext, str):
        plaintext = plaintext.encode('utf-8')
    
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # GCM 推荐使用 12 字节 nonce
    
    ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext, None)
    
    # 格式: base64(nonce || ciphertext_with_tag)
    result = nonce + ciphertext_with_tag
    return base64.b64encode(result).decode('utf-8')


def decrypt_data(ciphertext_b64: str, key: bytes) -> str:
    """
    解密 AES-256-GCM 加密的数据
    
    Args:
        ciphertext_b64: Base64 编码的密文
        key: 32 字节解密密钥
        
    Returns:
        解密后的明文字符串
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        return _fallback_decrypt(ciphertext_b64, key)
    
    try:
        raw = base64.b64decode(ciphertext_b64)
        
        # 提取 nonce (前 12 字节) 和密文+tag
        nonce = raw[:12]
        ciphertext_with_tag = raw[12:]
        
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext_with_tag, None)
        
        return plaintext.decode('utf-8')
        
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        raise ValueError(f'解密失败: {e}')


def _fallback_encrypt(plaintext: str | bytes, key: bytes) -> str:
    """备用加密方案（当 cryptography 库不可用时）"""
    from cryptography.fernet import Fernet
    
    # 将 32 字节密钥转为 Fernet 兼容的 base64 格式
    derived_key = base64.urlsafe_b64encode(
        hashlib.sha256(key + b'finance-tools-fernet').digest()
    )
    
    fernet = Fernet(derived_key)
    
    if isinstance(plaintext, str):
        plaintext = plaintext.encode('utf-8')
    
    encrypted = fernet.encrypt(plaintext)
    return base64.b64encode(b'fernet:' + encrypted).decode()


def _fallback_decrypt(ciphertext_b64: str, key: bytes) -> str:
    """备用解密方案"""
    from cryptography.fernet import Fernet
    
    raw = base64.b64decode(ciphertext_b64)
    
    if raw.startswith(b'fernet:'):
        encrypted = raw[7:]
    else:
        encrypted = raw
    
    derived_key = base64.urlsafe_b64encode(
        hashlib.sha256(key + b'finance-tools-fernet').digest()
    )
    
    fernet = Fernet(derived_key)
    decrypted = fernet.decrypt(encrypted)
    return decrypted.decode('utf-8')
