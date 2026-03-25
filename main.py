"""
PM Multi-Agent Workbench - CLI 入口
"""
import sys
import os
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config import Config
from core.logger import logger
from core.llm_client import LLMClient
from core.tool_registry import ToolRegistry
from core.agent_registry import AgentRegistry
from core.internal_tools import InternalTools
from orchestrator.orchestrator import Orchestrator

console = Console()

BANNER = """
╔══════════════════════════════════════════╗
║     🤖 Multi-Agent Workbench            ║
║     多Agent智能工作台                    ║
╚══════════════════════════════════════════╝
"""


def check_system(config, tool_registry, agent_registry):
    """系统检查模式"""
    console.print("\n[bold cyan]🔍 系统检查[/bold cyan]\n")

    # Provider 信息
    console.print("[bold]📡 已配置的 Provider:[/bold]")
    for name, info in config.list_providers().items():
        models = ", ".join(info["models"])
        console.print(f"  • {name}: {info['base_url']} [{models}]")

    # 角色-模型映射
    console.print("\n[bold]🎭 角色-模型映射:[/bold]")
    for role, model in config.list_role_models().items():
        console.print(f"  • {role}: {model}")

    # 工具
    console.print(f"\n[bold]🔧 已注册工具: {len(tool_registry.list_tools())}[/bold]")
    for tool in tool_registry.list_tools():
        console.print(f"  • {tool}")

    # Agent
    console.print(f"\n[bold]🤖 已注册Agent: {len(agent_registry.list_agents())}[/bold]")
    for agent_name in agent_registry.list_agents():
        manifest = agent_registry.get_manifest(agent_name)
        console.print(f"  • {manifest.get('display_name', agent_name)} ({agent_name})")

    console.print("\n[green]✅ 系统检查完成[/green]\n")


def startup():
    """系统启动，初始化所有组件"""
    console.print(BANNER, style="bold cyan")
    logger.info("Multi-Agent Workbench 启动")

    # 1. 加载配置
    config = Config()
    logger.set_level(config.log_level)
    logger.debug("加载配置: config.yaml")

    # 2. 初始化 Tool Registry
    tool_registry = ToolRegistry()
    tool_registry.discover_and_register(config)

    # 3. 初始化 LLM Client
    llm_client = LLMClient(config)

    # 4. 初始化 Agent Registry
    agent_registry = AgentRegistry()
    agent_registry.discover_and_register(config, llm_client, tool_registry)

    # 5. 初始化内部工具（沙箱限制在项目根目录，传入 registry 引用）
    project_root = os.path.dirname(os.path.abspath(__file__))
    internal_tools = InternalTools(
        project_root,
        tool_registry=tool_registry,
        agent_registry=agent_registry,
        config=config,
        llm_client=llm_client,
    )

    # 6. 初始化 Orchestrator
    orchestrator = Orchestrator(config, llm_client, agent_registry, internal_tools)
    orchestrator.initialize()

    # 7. 反向引用（reload_registry 需要刷新 Orchestrator 的 prompt）
    internal_tools.set_orchestrator(orchestrator)

    logger.info("系统就绪，等待用户输入")

    return config, tool_registry, agent_registry, orchestrator


def main():
    """主函数"""
    # 检查是否是系统检查模式
    check_mode = "--check" in sys.argv

    config, tool_registry, agent_registry, orchestrator = startup()

    if check_mode:
        check_system(config, tool_registry, agent_registry)
        return

    # 交互循环
    console.print()
    console.print("[bold]告诉我你想做什么，我来帮你规划和执行。[/bold]")
    console.print("[dim]支持自然语言交互，我能理解你的意思。[/dim]")
    console.print()

    while True:
        try:
            user_input = Prompt.ask("\n[bold green]📝 你的需求[/bold green]")

            if not user_input.strip():
                continue

            # 仅保留最基本的英文快捷键作为保底（不经过 LLM）
            cmd = user_input.strip().lower()
            if cmd in ("q", "quit", "exit"):
                console.print("\n[dim]再见！👋[/dim]\n")
                break

            # 所有自然语言输入都交给 Orchestrator 理解
            console.print("\n[yellow]CLI 交互模式已移除，请使用 Web 界面：[/yellow]")
            console.print("[bold]  🌐 http://localhost:3000[/bold]")
            console.print("[dim]  运行 ./start.sh 启动服务[/dim]\n")

        except KeyboardInterrupt:
            console.print("\n\n[dim]任务中断，返回主界面[/dim]")
            continue
        except SystemExit:
            console.print("\n[dim]再见！👋[/dim]\n")
            break
        except Exception as e:
            logger.error(f"未处理的异常: {e}")
            console.print(f"\n[red]❌ 发生错误: {e}[/red]")
            import traceback
            traceback.print_exc()
            continue


if __name__ == "__main__":
    main()
