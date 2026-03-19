"""
Agent注册中心 - 扫描 agents/ 目录，验证 manifest，检查工具依赖，动态加载 Agent 类
"""
import os
import importlib
import yaml
from core.logger import logger


class AgentRegistry:
    """Agent 注册中心"""

    def __init__(self, agents_dir: str = "agents"):
        self.agents_dir = agents_dir
        self._agents: dict[str, dict] = {}  # name -> {manifest, instance}

    def discover_and_register(self, config, llm_client, tool_registry) -> int:
        """扫描目录，发现并注册所有 Agent"""
        logger.info("Agent Registry 初始化")
        logger.debug(f"├─ 扫描目录: {self.agents_dir}/")

        if not os.path.isdir(self.agents_dir):
            logger.warning(f"Agent目录不存在: {self.agents_dir}")
            return 0

        registered = 0
        for item in sorted(os.listdir(self.agents_dir)):
            agent_dir = os.path.join(self.agents_dir, item)
            manifest_path = os.path.join(agent_dir, "manifest.yaml")

            # Skip non-directories and special files
            if not os.path.isdir(agent_dir) or item.startswith("__") or item == "base.py":
                continue
            if not os.path.isfile(manifest_path):
                continue

            try:
                manifest = self._load_manifest(manifest_path)
                self._validate_manifest(manifest)
                self._check_tool_deps(manifest, tool_registry)

                # 加载 system prompt
                prompts_path = os.path.join(agent_dir, "prompts.md")
                system_prompt = ""
                if os.path.isfile(prompts_path):
                    with open(prompts_path, "r", encoding="utf-8") as f:
                        system_prompt = f.read()

                instance = self._load_agent_class(
                    manifest, config, llm_client, tool_registry, system_prompt
                )

                self._agents[manifest["name"]] = {
                    "manifest": manifest,
                    "instance": instance,
                    "system_prompt": system_prompt,
                }

                logger.debug(f"├─ 发现Agent: {manifest['name']}")
                logger.debug(f"│  ├─ 验证manifest: ✓")
                if manifest.get("tools_required"):
                    for tool in manifest["tools_required"]:
                        logger.debug(f"│  ├─ 检查依赖工具: {tool} ✓")
                logger.debug(
                    f"│  └─ 注册成功: {manifest['name']} v{manifest.get('version', '?')}"
                )
                registered += 1

            except Exception as e:
                logger.error(f"├─ 加载Agent失败 [{item}]: {e}")

        logger.info(f"共注册 {registered} 个Agent")
        return registered

    def _load_manifest(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _validate_manifest(self, manifest: dict):
        required = ["name", "entry_point", "description", "when_to_use"]
        for field in required:
            if field not in manifest:
                raise ValueError(f"manifest 缺少必须字段: {field}")

    def _check_tool_deps(self, manifest: dict, tool_registry):
        """检查 Agent 依赖的工具是否已注册"""
        for tool_name in manifest.get("tools_required", []):
            if not tool_registry.has_tool(tool_name):
                raise ValueError(f"依赖工具未注册: {tool_name}")

    def _load_agent_class(self, manifest, config, llm_client, tool_registry, system_prompt):
        """动态加载 Agent 类并实例化"""
        entry = manifest["entry_point"]
        module_path, class_name = entry.rsplit(":", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        return cls(
            config=config,
            llm_client=llm_client,
            tool_registry=tool_registry,
            system_prompt=system_prompt,
            manifest=manifest,
        )

    def get_agent(self, name: str):
        """获取 Agent 实例"""
        if name not in self._agents:
            raise KeyError(f"Agent 未注册: {name}")
        return self._agents[name]["instance"]

    def get_manifest(self, name: str) -> dict:
        """获取 Agent 的 manifest"""
        if name not in self._agents:
            raise KeyError(f"Agent 未注册: {name}")
        return self._agents[name]["manifest"]

    def has_agent(self, name: str) -> bool:
        return name in self._agents

    def list_agents(self) -> list[str]:
        return list(self._agents.keys())

    def get_all_manifests(self) -> dict[str, dict]:
        """获取所有 Agent 的 manifest（供 Prompt Builder 使用）"""
        return {name: info["manifest"] for name, info in self._agents.items()}
