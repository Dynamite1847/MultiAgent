"""
内部工具 - 通用的沙箱化文件操作原语 + 动态注册能力
Orchestrator 通过组合这些原语完成具体任务
"""
import os
import importlib
from core.logger import logger


class InternalTools:
    """
    Orchestrator 的内部工具集。
    通用原语：read_file / write_file / list_directory
    动态注册：reload_registry（热加载新工具/Agent）
    所有文件操作限制在项目根目录沙箱内。
    """

    def __init__(self, project_root: str,
                 tool_registry=None, agent_registry=None,
                 config=None, llm_client=None):
        self.project_root = os.path.abspath(project_root)
        self._tool_registry = tool_registry
        self._agent_registry = agent_registry
        self._config = config
        self._llm_client = llm_client
        self._orchestrator = None  # 由 Orchestrator 初始化后反向设置

    def set_orchestrator(self, orchestrator):
        """反向引用 Orchestrator，用于 reload 后刷新 system prompt"""
        self._orchestrator = orchestrator

    # ────────────────────────────────────────
    # 工具定义（供 LLM 了解可用能力）
    # ────────────────────────────────────────

    def get_tool_definitions(self) -> list[dict]:
        """返回所有内部工具的定义"""
        return [
            {
                "name": "read_file",
                "description": "读取项目目录下的文件内容",
                "parameters": {"path": "文件相对路径"},
            },
            {
                "name": "write_file",
                "description": "写入或修改项目目录下的文件内容",
                "parameters": {
                    "path": "文件相对路径",
                    "content": "要写入的完整文件内容",
                },
            },
            {
                "name": "list_directory",
                "description": "列出项目目录下某个路径的文件和子目录",
                "parameters": {"path": "目录相对路径，默认为项目根目录"},
            },
            {
                "name": "reload_registry",
                "description": "重新扫描 tools/ 和 agents/ 目录，热加载新创建的工具和Agent。在用 write_file 创建新工具代码后调用此工具来注册",
            },
        ]

    # ────────────────────────────────────────
    # 统一调用入口
    # ────────────────────────────────────────

    def call(self, tool_name: str, params: dict = None) -> str:
        """调用指定的内部工具"""
        params = params or {}
        method = getattr(self, f"_tool_{tool_name}", None)
        if not method:
            return f"未知工具: {tool_name}"
        try:
            result = method(**params)
            logger.debug(f"内部工具调用: {tool_name} → {len(str(result))}字符", indent=1)
            return result
        except Exception as e:
            logger.error(f"内部工具 {tool_name} 执行失败: {e}")
            return f"工具执行失败: {e}"

    # ────────────────────────────────────────
    # 安全校验
    # ────────────────────────────────────────

    def _check_sandbox(self, path: str) -> tuple[str, str]:
        """
        校验路径在沙箱内，返回 (abs_path, error)。
        error 为空表示通过。
        """
        abs_path = os.path.normpath(os.path.join(self.project_root, path))
        if not abs_path.startswith(self.project_root):
            return abs_path, f"安全限制：只能访问项目目录内的文件"
        return abs_path, ""

    # ────────────────────────────────────────
    # 三个通用原语
    # ────────────────────────────────────────

    def _tool_read_file(self, path: str = "") -> str:
        """读取文件内容"""
        if not path:
            return "错误：请指定文件路径"

        abs_path, err = self._check_sandbox(path)
        if err:
            return err

        if not os.path.exists(abs_path):
            return f"文件不存在: {path}"
        if not os.path.isfile(abs_path):
            return f"不是文件: {path}，请使用 list_directory 查看目录内容"

        size = os.path.getsize(abs_path)
        if size > 50000:  # 50KB
            return f"文件过大 ({size} 字节)，只显示前 5000 字符"

        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read(5000)
            return f"## 文件: {path}\n\n```\n{content}\n```"
        except UnicodeDecodeError:
            return f"无法读取: {path} (非文本文件)"

    def _tool_write_file(self, path: str = "", content: str = "") -> str:
        """写入文件内容"""
        if not path:
            return "错误：请指定文件路径"
        if not content:
            return "错误：请指定文件内容"

        abs_path, err = self._check_sandbox(path)
        if err:
            return err

        # 禁止写入敏感文件
        basename = os.path.basename(abs_path)
        if basename in (".env", ".git"):
            return f"安全限制：不允许修改 {basename}"

        if len(content) > 100000:  # 100KB
            return f"内容过大 ({len(content)} 字符)，请缩减后重试"

        # 自动创建目录
        dir_path = os.path.dirname(abs_path)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)

        try:
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
            size = os.path.getsize(abs_path)
            logger.info(f"文件写入: {path} ({size} bytes)")
            return f"✅ 文件已写入: {path} ({size} bytes)"
        except Exception as e:
            return f"写入失败: {e}"

    def _tool_list_directory(self, path: str = "") -> str:
        """列出目录内容"""
        abs_path, err = self._check_sandbox(path)
        if err:
            return err

        if not os.path.exists(abs_path):
            return f"目录不存在: {path}"
        if not os.path.isdir(abs_path):
            return f"不是目录: {path}"

        items = []
        try:
            for name in sorted(os.listdir(abs_path)):
                if name.startswith("."):
                    continue
                full = os.path.join(abs_path, name)
                if os.path.isdir(full):
                    items.append(f"📁 {name}/")
                else:
                    size = os.path.getsize(full)
                    items.append(f"📄 {name} ({size} bytes)")
        except PermissionError:
            return f"无权限访问: {path}"

        display_path = path or "."
        return f"## 目录: {display_path}\n\n" + "\n".join(items)

    # ────────────────────────────────────────
    # 动态注册
    # ────────────────────────────────────────

    def _tool_reload_registry(self) -> str:
        """重新扫描 tools/ 和 agents/ 目录，增量注册新发现的工具和Agent"""
        results = []

        # ── 增量加载工具 ──
        if self._tool_registry and self._config:
            tools_dir = os.path.join(self.project_root, "tools")
            if os.path.isdir(tools_dir):
                existing = set(self._tool_registry.list_tools())
                new_count = 0
                for item in sorted(os.listdir(tools_dir)):
                    tool_dir = os.path.join(tools_dir, item)
                    manifest_path = os.path.join(tool_dir, "manifest.yaml")
                    if not os.path.isdir(tool_dir) or not os.path.isfile(manifest_path):
                        continue
                    try:
                        import yaml
                        with open(manifest_path, "r", encoding="utf-8") as f:
                            manifest = yaml.safe_load(f)
                        name = manifest.get("name", item)
                        if name in existing:
                            continue  # 已注册，跳过
                        # 动态加载
                        entry = manifest["entry_point"]
                        module_path, class_name = entry.rsplit(":", 1)
                        # 强制重新导入（防止缓存）
                        module = importlib.import_module(module_path)
                        importlib.reload(module)
                        cls = getattr(module, class_name)
                        instance = cls(self._config)
                        self._tool_registry._tools[name] = {
                            "manifest": manifest,
                            "instance": instance,
                        }
                        new_count += 1
                        logger.info(f"动态注册工具: {name}")
                        results.append(f"✅ 工具 {name} 注册成功")
                    except Exception as e:
                        logger.error(f"动态加载工具失败 [{item}]: {e}")
                        results.append(f"❌ 工具 {item} 加载失败: {e}")
                if new_count == 0:
                    results.append("工具: 无新增")

        # ── 增量加载 Agent ──
        if self._agent_registry and self._config and self._llm_client:
            agents_dir = os.path.join(self.project_root, "agents")
            if os.path.isdir(agents_dir):
                existing = set(self._agent_registry.list_agents())
                new_count = 0
                for item in sorted(os.listdir(agents_dir)):
                    agent_dir = os.path.join(agents_dir, item)
                    manifest_path = os.path.join(agent_dir, "manifest.yaml")
                    if not os.path.isdir(agent_dir) or item.startswith("__"):
                        continue
                    if not os.path.isfile(manifest_path):
                        continue
                    try:
                        import yaml
                        with open(manifest_path, "r", encoding="utf-8") as f:
                            manifest = yaml.safe_load(f)
                        name = manifest.get("name", item)
                        if name in existing:
                            continue

                        # 读取 system prompt
                        prompts_path = os.path.join(agent_dir, "prompts.md")
                        system_prompt = ""
                        if os.path.isfile(prompts_path):
                            with open(prompts_path, "r", encoding="utf-8") as f:
                                system_prompt = f.read()

                        # 动态加载
                        entry = manifest["entry_point"]
                        module_path, class_name = entry.rsplit(":", 1)
                        module = importlib.import_module(module_path)
                        importlib.reload(module)
                        cls = getattr(module, class_name)
                        instance = cls(
                            config=self._config,
                            llm_client=self._llm_client,
                            tool_registry=self._tool_registry,
                            system_prompt=system_prompt,
                            manifest=manifest,
                        )
                        self._agent_registry._agents[name] = {
                            "manifest": manifest,
                            "instance": instance,
                            "system_prompt": system_prompt,
                        }
                        new_count += 1
                        logger.info(f"动态注册Agent: {name}")
                        results.append(f"✅ Agent {name} 注册成功")
                    except Exception as e:
                        logger.error(f"动态加载Agent失败 [{item}]: {e}")
                        results.append(f"❌ Agent {item} 加载失败: {e}")
                if new_count == 0:
                    results.append("Agent: 无新增")

        # ── 刷新 Orchestrator 的 System Prompt ──
        if self._orchestrator and (results and any("✅" in r for r in results)):
            try:
                self._orchestrator.initialize()
                results.append("✅ Orchestrator System Prompt 已刷新")
            except Exception as e:
                results.append(f"⚠️ Prompt 刷新失败: {e}")

        return "\n".join(results) if results else "无变化"
