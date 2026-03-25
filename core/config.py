"""
配置加载器 — 统一配置源
- 所有配置从 config.yaml 读取
- API Key 从 .env 环境变量读取 (格式: {PROVIDER}_API_KEY)
"""
import os
import json
import yaml
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

CONFIG_YAML_PATH = Path(__file__).parent.parent / "config.yaml"


class ModelConfig:
    """单个模型的完整配置"""
    def __init__(self, provider: str, model: str, base_url: str, api_key: str,
                 temperature: float = 0.7, max_tokens: int = 4096,
                 json_format_mode: str = "prompt"):
        self.provider = provider
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.json_format_mode = json_format_mode

    def __repr__(self):
        return f"ModelConfig(provider={self.provider}, model={self.model})"


class Config:
    """全局配置管理器 — 统一读取 config.yaml"""

    def __init__(self, config_path: str = None):
        yaml_path = config_path or str(CONFIG_YAML_PATH)
        self._yaml_path = yaml_path
        self._raw = self._load_yaml(yaml_path)

        # Provider 信息
        self.providers = self._raw.get("providers", {})
        # 角色→模型映射 (Agent)
        self.role_models = self._raw.get("role_models", {})
        # 系统参数
        self.system = self._raw.get("system", {})

    def _load_yaml(self, path: str) -> dict:
        p = Path(path)
        if not p.exists():
            return {}
        with open(p, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def reload(self):
        """重新加载配置"""
        self._raw = self._load_yaml(self._yaml_path)
        self.providers = self._raw.get("providers", {})
        self.role_models = self._raw.get("role_models", {})
        self.system = self._raw.get("system", {})

    def get_api_key(self, provider_name: str) -> str:
        """从 .env 读取 provider 的 API Key"""
        env_key = f"{provider_name.upper()}_API_KEY"
        key = os.getenv(env_key, "")
        if not key:
            raise ValueError(f"环境变量 '{env_key}' 未设置")
        return key

    def get_model_for_role(self, role: str) -> ModelConfig:
        """根据角色获取模型配置"""
        role_model_str = self.role_models.get(role)
        if not role_model_str:
            raise ValueError(f"角色 '{role}' 未在 config.yaml 的 role_models 中配置")

        provider_name, model_name = self._parse_role_model(role_model_str)
        provider = self.providers.get(provider_name)
        if not provider:
            raise ValueError(f"Provider '{provider_name}' 未在 config.yaml 中定义")

        if model_name not in provider.get("models", []):
            raise ValueError(
                f"模型 '{model_name}' 不在 provider '{provider_name}' 的可用模型列表中"
            )

        api_key = self.get_api_key(provider_name)
        json_mode = provider.get("json_format_mode", "prompt")

        return ModelConfig(
            provider=provider_name,
            model=model_name,
            base_url=provider.get("base_url", ""),
            api_key=api_key,
            temperature=self.system.get("temperature", 0.7),
            max_tokens=self.system.get("max_tokens", 4096),
            json_format_mode=json_mode,
        )

    def _parse_role_model(self, role_model_str: str) -> tuple[str, str]:
        """解析 'provider/model' 格式"""
        parts = role_model_str.split("/", 1)
        if len(parts) != 2:
            raise ValueError(
                f"role_models 格式错误: '{role_model_str}'，应为 'provider/model'"
            )
        return parts[0], parts[1]

    @property
    def log_level(self) -> str:
        return self.system.get("log_level", "INFO")

    @property
    def output_dir(self) -> str:
        return self.system.get("output_dir", "./outputs")

    @property
    def tavily_api_key(self) -> str:
        key = os.getenv("TAVILY_API_KEY", "")
        if not key:
            raise ValueError("环境变量 'TAVILY_API_KEY' 未设置")
        return key

    def list_providers(self) -> dict:
        """列出所有可用的 provider 和模型"""
        result = {}
        for name, provider in self.providers.items():
            result[name] = {
                "base_url": provider.get("base_url", ""),
                "models": provider.get("models", []),
            }
        return result

    def list_role_models(self) -> dict:
        """列出当前角色-模型映射"""
        return dict(self.role_models)
