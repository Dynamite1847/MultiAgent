"""
工具注册中心 - 扫描 tools/ 目录，验证 manifest，动态加载工具类
"""
import os
import importlib
import yaml
from core.logger import logger


class ToolRegistry:
    """工具注册中心"""

    def __init__(self, tools_dir: str = "tools"):
        self.tools_dir = tools_dir
        self._tools: dict[str, dict] = {}  # name -> {manifest, instance}

    def discover_and_register(self, config) -> int:
        """扫描目录，发现并注册所有工具"""
        logger.info("Tool Registry 初始化")

        if not os.path.isdir(self.tools_dir):
            logger.warning(f"工具目录不存在: {self.tools_dir}")
            return 0

        registered = 0
        for item in sorted(os.listdir(self.tools_dir)):
            tool_dir = os.path.join(self.tools_dir, item)
            manifest_path = os.path.join(tool_dir, "manifest.yaml")

            if not os.path.isdir(tool_dir) or not os.path.isfile(manifest_path):
                continue

            try:
                manifest = self._load_manifest(manifest_path)
                self._validate_manifest(manifest)
                self._check_config(manifest, config)
                instance = self._load_tool_class(manifest, config)

                self._tools[manifest["name"]] = {
                    "manifest": manifest,
                    "instance": instance,
                }
                logger.debug(f"├─ 注册成功: {manifest['name']} v{manifest.get('version', '?')}")
                registered += 1

            except Exception as e:
                logger.error(f"├─ 加载工具失败 [{item}]: {e}")

        logger.info(f"共注册 {registered} 个工具")
        return registered

    def _load_manifest(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _validate_manifest(self, manifest: dict):
        required = ["name", "entry_point"]
        for field in required:
            if field not in manifest:
                raise ValueError(f"manifest 缺少必须字段: {field}")

    def _check_config(self, manifest: dict, config):
        """检查工具需要的配置项是否齐全"""
        for env_var in manifest.get("config_required", []):
            val = os.getenv(env_var, "")
            if not val:
                raise ValueError(f"缺少必须的环境变量: {env_var}")
            logger.debug(f"│  └─ 检查配置: {env_var} ✓", indent=0)

    def _load_tool_class(self, manifest: dict, config):
        """动态加载工具类并实例化"""
        entry = manifest["entry_point"]  # e.g. "tools.tavily_search.client:TavilySearchTool"
        module_path, class_name = entry.rsplit(":", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        return cls(config)

    def get_tool(self, name: str):
        """获取工具实例"""
        if name not in self._tools:
            raise KeyError(f"工具未注册: {name}")
        return self._tools[name]["instance"]

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())
