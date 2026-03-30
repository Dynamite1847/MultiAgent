#!/usr/bin/env python3
"""
用户管理脚本
用法:
  python manage_users.py list                          # 查看所有用户
  python manage_users.py add <用户名> <密码> [显示名]    # 添加用户
  python manage_users.py passwd <用户名> <新密码>        # 修改密码
  python manage_users.py delete <用户名>                # 删除用户
  python manage_users.py reset                         # 重置为默认用户
"""
import sys
import json
import bcrypt
from pathlib import Path

USERS_FILE = Path(__file__).parent / "users.json"


def load_users():
    if not USERS_FILE.exists():
        return []
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_users(users):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)
    print(f"✅ 已保存到 {USERS_FILE}")


def hash_pw(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def cmd_list():
    users = load_users()
    if not users:
        print("暂无用户")
        return
    print(f"{'用户名':<15} {'显示名':<10} {'user_id'}")
    print("-" * 45)
    for u in users:
        print(f"{u['username']:<15} {u.get('display_name', '-'):<10} {u['user_id']}")


def cmd_add(username, password, display_name=None):
    users = load_users()
    for u in users:
        if u["username"] == username:
            print(f"❌ 用户 {username} 已存在，请用 passwd 命令修改密码")
            return
    user_id = f"user_{username}"
    users.append({
        "user_id": user_id,
        "username": username,
        "display_name": display_name or username,
        "password_hash": hash_pw(password),
    })
    save_users(users)
    print(f"✅ 已添加用户: {username} (密码: {password})")


def cmd_passwd(username, new_password):
    users = load_users()
    for u in users:
        if u["username"] == username:
            u["password_hash"] = hash_pw(new_password)
            save_users(users)
            print(f"✅ 已修改 {username} 的密码为: {new_password}")
            return
    print(f"❌ 用户 {username} 不存在")


def cmd_delete(username):
    users = load_users()
    new_users = [u for u in users if u["username"] != username]
    if len(new_users) == len(users):
        print(f"❌ 用户 {username} 不存在")
        return
    save_users(new_users)
    print(f"✅ 已删除用户: {username}")


def cmd_reset():
    users = [
        {
            "user_id": "user_dongyu",
            "username": "dongyu",
            "display_name": "东宇",
            "password_hash": hash_pw("dongyu123"),
        },
        {
            "user_id": "user_wife",
            "username": "miao",
            "display_name": "喵喵",
            "password_hash": hash_pw("miao123"),
        },
    ]
    save_users(users)
    print("✅ 已重置为默认用户 (dongyu/dongyu123, miao/miao123)")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__)
        sys.exit(0)

    cmd = args[0]
    if cmd == "list":
        cmd_list()
    elif cmd == "add":
        if len(args) < 3:
            print("用法: python manage_users.py add <用户名> <密码> [显示名]")
            sys.exit(1)
        cmd_add(args[1], args[2], args[3] if len(args) > 3 else None)
    elif cmd == "passwd":
        if len(args) < 3:
            print("用法: python manage_users.py passwd <用户名> <新密码>")
            sys.exit(1)
        cmd_passwd(args[1], args[2])
    elif cmd == "delete":
        if len(args) < 2:
            print("用法: python manage_users.py delete <用户名>")
            sys.exit(1)
        cmd_delete(args[1])
    elif cmd == "reset":
        cmd_reset()
    else:
        print(f"未知命令: {cmd}")
        print(__doc__)
        sys.exit(1)
