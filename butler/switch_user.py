"""
用户切换脚本
将 profiles/ 下的用户模板复制到 OpenClaw 标准文件位置
用法: python switch_user.py <user_id>
      python switch_user.py list     # 列出可用用户
"""

import os
import sys
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

USERS = {
    "white_collar": {
        "name": "小琴 (白领)",
        "profile": "profiles/users/whitecollar.md",
        "memory": "profiles/memories/whitecollar-memory.md",
        "wardrobe": "profiles/users/whitecollar-wardrobe.md",
    },
    "parent": {
        "name": "小冉 (宝妈)",
        "profile": "profiles/users/parent.md",
        "memory": "profiles/memories/parent-memory.md",
        "wardrobe": "profiles/users/parent-wardrobe.md",
    },
    "student": {
        "name": "小晴 (大学生)",
        "profile": "profiles/users/student.md",
        "memory": "profiles/memories/student-memory.md",
        "wardrobe": "profiles/users/student-wardrobe.md",
    },
}

TARGETS = {
    "profile": "USER.md",
    "memory": "MEMORY.md",
    "wardrobe": "wardrobe.md",
}


def switch_user(user_id: str):
    """将指定用户的画像、记忆、衣橱复制到 OpenClaw 标准位置"""
    if user_id not in USERS:
        print(f"[ERROR] 未知用户: {user_id}")
        print(f"可用: {', '.join(USERS.keys())}")
        return False

    user = USERS[user_id]
    print(f"\n{'='*50}")
    print(f"切换用户 → {user['name']} ({user_id})")
    print(f"{'='*50}")

    for key, target_name in TARGETS.items():
        src = os.path.join(BASE_DIR, user[key])
        dst = os.path.join(BASE_DIR, target_name)

        if not os.path.exists(src):
            print(f"  [WARN] 源文件不存在: {src}")
            continue

        shutil.copy2(src, dst)
        size = os.path.getsize(dst)
        print(f"  [OK] {target_name} ← {os.path.basename(src)} ({size:,} bytes)")

    print(f"\n当前用户已切换为: {user['name']} [OK]")
    print(f"OpenClaw 将读取 USER.md / MEMORY.md / wardrobe.md")
    return True


def list_users():
    """列出所有可用用户"""
    print("\n可用用户:")
    for uid, info in USERS.items():
        exists = all(
            os.path.exists(os.path.join(BASE_DIR, info[k]))
            for k in ["profile", "memory", "wardrobe"]
        )
        status = "[OK]" if exists else "[MISS] (缺少文件)"
        print(f"  {uid:20s} → {info['name']:20s} {status}")


def show_current():
    """显示当前激活的用户"""
    user_md = os.path.join(BASE_DIR, "USER.md")
    if os.path.exists(user_md):
        with open(user_md, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
        # 从第一行标题推断用户
        for uid, info in USERS.items():
            if uid.replace("_", "") in first_line or any(
                w in first_line for w in info["name"].split()
            ):
                print(f"当前用户: {info['name']} ({uid})")
                return
    print("当前未设置用户（USER.md 为空或不存在）")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python switch_user.py <user_id>")
        list_users()
        show_current()
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "list":
        list_users()
        show_current()
    elif cmd == "current":
        show_current()
    elif cmd in USERS:
        switch_user(cmd)
    else:
        print(f"[ERROR] 未知用户 '{cmd}'，可用: {', '.join(USERS.keys())}")
        sys.exit(1)
