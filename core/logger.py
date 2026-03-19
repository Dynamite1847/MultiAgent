"""
结构化日志系统 - 支持树形缩进、彩色控制台输出 + 本地文件写入
"""
import logging
import os
from datetime import datetime
from rich.console import Console
from rich.text import Text

console = Console()

# 自定义日志格式
LEVEL_ICONS = {
    "DEBUG": "🔍",
    "INFO": "ℹ️ ",
    "WARNING": "⚠️ ",
    "ERROR": "❌",
}

LEVEL_COLORS = {
    "DEBUG": "dim",
    "INFO": "cyan",
    "WARNING": "yellow",
    "ERROR": "red bold",
}


class PMLogger:
    """PM Workbench 专用日志器"""

    def __init__(self, name: str = "PMWorkbench", level: str = "DEBUG",
                 log_dir: str = "logs"):
        self.name = name
        self._level = getattr(logging, level.upper(), logging.DEBUG)
        self._indent = 0
        self._log_dir = log_dir
        self._log_file = None
        self._init_file_logging()

    def _init_file_logging(self):
        """初始化文件日志"""
        os.makedirs(self._log_dir, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_path = os.path.join(self._log_dir, f"{date_str}.log")
        self._log_file = open(log_path, "a", encoding="utf-8")
        self._log_path = log_path

    def _should_log(self, level: int) -> bool:
        return level >= self._level

    def _log(self, level_name: str, message: str, indent: int = 0):
        level_num = getattr(logging, level_name.upper(), logging.DEBUG)
        if not self._should_log(level_num):
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prefix = "  " * (self._indent + indent)

        # ── 控制台输出（彩色）──
        icon = LEVEL_ICONS.get(level_name, "")
        color = LEVEL_COLORS.get(level_name, "white")

        text = Text()
        text.append(f"[{timestamp}] ", style="dim")
        text.append(f"[{level_name:7s}] ", style=color)
        text.append(f"{prefix}{message}")

        console.print(text)

        # ── 文件输出（纯文本）──
        if self._log_file and not self._log_file.closed:
            file_line = f"[{timestamp}] [{level_name:7s}] {prefix}{message}\n"
            self._log_file.write(file_line)
            self._log_file.flush()

    def debug(self, message: str, indent: int = 0):
        self._log("DEBUG", message, indent)

    def info(self, message: str, indent: int = 0):
        self._log("INFO", message, indent)

    def warning(self, message: str, indent: int = 0):
        self._log("WARNING", message, indent)

    def error(self, message: str, indent: int = 0):
        self._log("ERROR", message, indent)

    def indent(self):
        """增加缩进层级"""
        self._indent += 1
        return self

    def dedent(self):
        """减少缩进层级"""
        self._indent = max(0, self._indent - 1)
        return self

    def set_level(self, level: str):
        """运行时切换日志级别"""
        self._level = getattr(logging, level.upper(), logging.DEBUG)

    def section(self, title: str):
        """输出分隔段落"""
        console.print(f"\n{'─' * 50}", style="dim")
        self.info(title)
        console.print(f"{'─' * 50}", style="dim")

    def close(self):
        """关闭日志文件"""
        if self._log_file and not self._log_file.closed:
            self._log_file.close()

    @property
    def log_path(self) -> str:
        return self._log_path


# 全局日志实例
logger = PMLogger()
