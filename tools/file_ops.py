"""
File Operations Tool — 文件读写和目录操作。

降级自 core/internal_tools.py：
- read_file, write_file, list_directory 拆为独立 Tool
- 沙箱安全限制保留
- write_file 设为 PERMISSION_CONFIRM（破坏性操作）
"""
import os
from tools.base import BaseTool
from core.logger import logger


class ReadFileTool(BaseTool):
    """读取文件内容"""

    name = "read_file"
    description = "读取项目目录下的文件内容。用于查看代码、配置文件、文档等。"
    permission = BaseTool.PERMISSION_AUTO

    parameters = {
        "path": {
            "type": "string",
            "description": "文件的相对路径（相对于项目根目录）",
            "required": True,
        },
    }

    def __init__(self, project_root: str):
        self._root = os.path.abspath(project_root)

    def execute(self, path: str) -> str:
        abs_path = os.path.normpath(os.path.join(self._root, path))
        if not abs_path.startswith(self._root):
            return "安全限制：只能访问项目目录内的文件"

        if not os.path.exists(abs_path):
            return f"文件不存在: {path}"
        if not os.path.isfile(abs_path):
            return f"不是文件: {path}"

        size = os.path.getsize(abs_path)
        if size > 100_000:
            return f"文件过大 ({size} 字节)，只显示前 10000 字符"

        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read(10000)
            truncated = "（已截断）" if size > 10000 else ""
            return f"## 文件: {path} ({size} bytes){truncated}\n\n```\n{content}\n```"
        except UnicodeDecodeError:
            return f"无法读取: {path} (非文本文件)"


class WriteFileTool(BaseTool):
    """写入文件内容"""

    name = "write_file"
    description = "写入或修改项目目录下的文件。自动创建不存在的目录。"
    permission = BaseTool.PERMISSION_CONFIRM  # 破坏性操作，需确认

    parameters = {
        "path": {
            "type": "string",
            "description": "文件的相对路径（相对于项目根目录）",
            "required": True,
        },
        "content": {
            "type": "string",
            "description": "要写入的完整文件内容",
            "required": True,
        },
    }

    def __init__(self, project_root: str):
        self._root = os.path.abspath(project_root)

    def execute(self, path: str, content: str) -> str:
        abs_path = os.path.normpath(os.path.join(self._root, path))
        if not abs_path.startswith(self._root):
            return "安全限制：只能写入项目目录内的文件"

        basename = os.path.basename(abs_path)
        if basename in (".env", ".git"):
            return f"安全限制：不允许修改 {basename}"

        if len(content) > 200_000:
            return f"内容过大 ({len(content)} 字符)，请缩减"

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


class ListDirectoryTool(BaseTool):
    """列出目录内容"""

    name = "list_directory"
    description = "列出项目目录下某个路径的文件和子目录。"
    permission = BaseTool.PERMISSION_AUTO

    parameters = {
        "path": {
            "type": "string",
            "description": "目录的相对路径，默认为项目根目录",
            "default": ".",
        },
    }

    def __init__(self, project_root: str):
        self._root = os.path.abspath(project_root)

    def execute(self, path: str = ".") -> str:
        abs_path = os.path.normpath(os.path.join(self._root, path))
        if not abs_path.startswith(self._root):
            return "安全限制：只能访问项目目录内的文件"

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

        return f"## 目录: {path}\n\n" + "\n".join(items)
