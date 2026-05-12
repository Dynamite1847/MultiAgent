"""
设备绑定加密模块 — 用于保护 .env 文件
自动读取设备唯一硬件 ID 作为密钥进行 AES 加密
"""
import os
import sys
import base64
import hashlib
import platform
import subprocess
from pathlib import Path
import uuid

try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None

def get_hardware_id() -> str:
    """获取设备的唯一机器码"""
    system = platform.system()
    try:
        if system == "Windows":
            # Windows: 尝试获取主板 UUID
            output = subprocess.check_output('wmic csproduct get uuid', shell=True).decode('utf-8')
            lines = output.strip().split('\n')
            if len(lines) > 1:
                return lines[1].strip()
        elif system == "Darwin":
            # macOS: 尝试获取平台 UUID
            output = subprocess.check_output("ioreg -rd1 -c IOPlatformExpertDevice | grep IOPlatformUUID", shell=True).decode('utf-8')
            return output.split('"')[3]
        elif system == "Linux":
            # Linux: 读取 machine-id
            with open('/etc/machine-id', 'r') as f:
                return f.read().strip()
    except Exception as e:
        pass

    # 兜底方案：使用 MAC 地址（跨平台）
    return str(uuid.getnode())

def get_encryption_key() -> bytes:
    """基于硬件 ID 生成 32 字节的 URL 安全 Base64 密钥"""
    hw_id = get_hardware_id()
    # 混入固定盐值，增加抗彩虹表攻击能力
    salt = b"maw0rkb3nch-s3cr3t-s4lt"
    # PBKDF2 算法生成 32 字节密钥
    key = hashlib.pbkdf2_hmac('sha256', hw_id.encode('utf-8'), salt, 100000)
    return base64.urlsafe_b64encode(key)

def encrypt_env():
    """将明文 .env 加密为 .env.enc"""
    if Fernet is None:
        print("错误: 缺少 cryptography 依赖，请运行 'pip install cryptography'")
        sys.exit(1)

    root_dir = Path(__file__).parent.parent
    env_path = root_dir / ".env"
    enc_path = root_dir / ".env.enc"

    if not env_path.exists():
        print(f"未找到明文文件 {env_path}，无需加密。")
        return

    key = get_encryption_key()
    f = Fernet(key)

    with open(env_path, "rb") as file:
        original_data = file.read()

    encrypted_data = f.encrypt(original_data)

    with open(enc_path, "wb") as file:
        file.write(encrypted_data)

    print("==================================================")
    print("[OK] .env 文件加密成功! 生成文件: .env.enc")
    print("==================================================")
    print("[注意] 安全建议:")
    print("1. 您现在可以放心地将原明文 .env 文件删除了。")
    print("2. 注意: .env.enc 已经与当前这台电脑绑定!")
    print("   如果要在其他电脑上运行，请务必在新电脑上重新执行此加密流程。")
    print("==================================================")

def load_encrypted_env() -> bool:
    """读取 .env.enc，在内存中解密并加载到 os.environ"""
    root_dir = Path(__file__).parent.parent
    enc_path = root_dir / ".env.enc"

    if not enc_path.exists():
        return False

    if Fernet is None:
        raise ImportError("加载加密的 .env.enc 需要 cryptography 库，请安装。")

    try:
        key = get_encryption_key()
        f = Fernet(key)

        with open(enc_path, "rb") as file:
            encrypted_data = file.read()

        decrypted_data = f.decrypt(encrypted_data).decode('utf-8')

        # 逐行加载环境变量
        for line in decrypted_data.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                k, v = line.split('=', 1)
                # 不覆盖系统中已有的同名环境变量
                if k.strip() not in os.environ:
                    os.environ[k.strip()] = v.strip()
        return True
    except Exception as e:
        print(f"\n[严重错误] 解密 .env.enc 失败！")
        print(f"可能原因：")
        print(f"1. 该文件是在其他电脑上加密的（设备已绑定）。")
        print(f"2. 文件的内容已被损坏。")
        print(f"详细错误：{e}\n")
        return False

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "encrypt":
        encrypt_env()
    else:
        print("用法: python -m core.secure_env encrypt")
