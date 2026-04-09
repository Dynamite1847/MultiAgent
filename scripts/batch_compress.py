"""
批量 Observer Memory 压缩脚本。
对 sessions 目录下消息数超过阈值的 session 执行 OM 压缩。
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from memory.observer import ObserverMemory, estimate_messages_tokens
from core.llm_client import LLMClient
from pathlib import Path

SESSIONS_DIR = Path("sessions/user_dongyu")
MIN_MESSAGES = 20   # 只处理消息数 >= 20 的 session
CONTEXT_ROUNDS = 10

def main():
    llm = LLMClient()

    sessions = sorted(SESSIONS_DIR.glob("*.json"))
    print(f"📂 扫描 {len(sessions)} 个 session...")

    for path in sessions:
        with open(path, "r") as f:
            session = json.load(f)

        messages = session.get("messages", [])
        name = session.get("name", path.stem)[:30]
        existing_summary = session.get("observer_summary")

        if len(messages) < MIN_MESSAGES:
            print(f"  ⏭️  {name} ({len(messages)} msgs) — 跳过")
            continue

        tokens_before = estimate_messages_tokens(messages)
        print(f"\n  🔄 {name}")
        print(f"     消息数: {len(messages)}, 估计 tokens: {tokens_before}")

        if existing_summary:
            print(f"     已有摘要 v{existing_summary.get('version', '?')}, 跳过")
            continue

        # 执行压缩
        try:
            summary = ObserverMemory.compact(
                messages=messages,
                llm_client=llm,
                role="orchestrator",
                existing_summary=existing_summary,
                context_rounds=CONTEXT_ROUNDS,
            )

            if summary and summary.get("content"):
                session["observer_summary"] = summary

                # 保存回文件（messages 保持完整！）
                with open(path, "w") as f:
                    json.dump(session, f, ensure_ascii=False, indent=2)

                print(f"     ✅ 压缩完成!")
                print(f"     摘要: {summary['content'][:100]}...")
                print(f"     compressed_up_to: {summary['compressed_up_to']}")
                print(f"     版本: v{summary.get('version', 1)}")
            else:
                print(f"     ⚠️  压缩返回空")

        except Exception as e:
            print(f"     ❌ 压缩失败: {e}")

    print("\n✅ 批量压缩完成!")


if __name__ == "__main__":
    main()
