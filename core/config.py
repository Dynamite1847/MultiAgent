"""
配置加载器 - 支持多Provider、多模型、角色级模型切换
"""
import os
import yaml
from dotenv import load_dotenv
from typing import Optional


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
        self.json_format_mode = json_format_mode  # chat_completions / responses_api / prompt

    def __repr__(self):
        return f"ModelConfig(provider={self.provider}, model={self.model})"


class Config:
    """全局配置管理器"""

    def __init__(self, config_path: str = "config.yaml"):
        load_dotenv()
        self._config_path = config_path
        self._raw = self._load_yaml(config_path)
        self.providers = self._raw.get("providers", {})
        self.role_models = self._raw.get("role_models", {})
        self.system = self._raw.get("system", {})

    def _load_yaml(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def reload(self):
        """重新加载配置（支持运行时切换模型）"""
        self._raw = self._load_yaml(self._config_path)
        self.providers = self._raw.get("providers", {})
        self.role_models = self._raw.get("role_models", {})
        self.system = self._raw.get("system", {})

    def get_model_for_role(self, role: str) -> ModelConfig:
        """
        根据角色获取模型配置
        role_models 格式: "provider/model" (e.g. "doubao/doubao-seed-2-0-pro-260215")
        """
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

        # 从 .env 读取 API Key
        api_key_env = provider.get("api_key_env", f"{provider_name.upper()}_API_KEY")
        api_key = os.getenv(api_key_env, "")
        if not api_key:
            raise ValueError(
                f"环境变量 '{api_key_env}' 未设置，请在 .env 文件中配置"
            )

        return ModelConfig(
            provider=provider_name,
            model=model_name,
            base_url=provider["base_url"],
            api_key=api_key,
            temperature=self.system.get("temperature", 0.7),
            max_tokens=self.system.get("max_tokens", 4096),
            json_format_mode=provider.get("json_format_mode", "prompt"),
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
                "base_url": provider["base_url"],
                "models": provider.get("models", []),
            }
        return result

    def list_role_models(self) -> dict:
        """列出当前角色-模型映射"""
        return dict(self.role_models)
