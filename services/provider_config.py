"""
Provider 配置管理 — 统一读写 config.yaml
前端设置面板通过此模块的 load_config / save_config 管理配置
API Key 从 .env 环境变量读取
"""
import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

from core.secure_env import load_encrypted_env

env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv()
else:
    load_encrypted_env()

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def load_config() -> dict:
    """加载配置供前端使用（注入 API Key）"""
    raw = _load_yaml()
    providers = raw.get("providers", {})

    # 注入 .env 中的 API Key
    for name, prov in providers.items():
        env_key = f"{name.upper()}_API_KEY"
        prov["api_key"] = os.getenv(env_key, "")

    return {
        "providers": providers,
        "default_provider": raw.get("default_provider", ""),
        "default_model": raw.get("default_model", ""),
        "global_system_prompt": raw.get("global_system_prompt", ""),
        "default_params": raw.get("default_params", {}),
        "context_strategy": raw.get("context_strategy", "rounds"),
        "context_rounds": raw.get("context_rounds", 10),
        "context_token_threshold": raw.get("context_token_threshold", 8000),
        "max_single_message_tokens": raw.get("max_single_message_tokens", 30000),
        "max_total_tokens": raw.get("max_total_tokens", 60000),
        "role_models": raw.get("role_models", {}),
    }


def save_config(config: dict) -> None:
    """保存前端修改的配置回 config.yaml"""
    raw = _load_yaml()

    # 更新 providers（去掉 api_key，不保存到 yaml）
    if "providers" in config:
        providers = {}
        for name, prov in config["providers"].items():
            cleaned = {k: v for k, v in prov.items() if k != "api_key"}
            providers[name] = cleaned
        raw["providers"] = providers

    # 更新其他字段
    for key in ["default_provider", "default_model", "global_system_prompt",
                "default_params", "context_strategy", "context_rounds",
                "context_token_threshold", "max_single_message_tokens", "max_total_tokens"]:
        if key in config:
            raw[key] = config[key]

    _save_yaml(raw)


def get_provider_config(provider: str) -> dict:
    """获取指定 provider 的配置（含 API Key）"""
    cfg = load_config()
    return cfg.get("providers", {}).get(provider, {})


def _load_yaml() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _save_yaml(data: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
