import os
import sys
from pathlib import Path

if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>&1")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def show_log(lines: int = 30):
    log_path = Path("agent.log")
    if not log_path.exists():
        print("agent.log не найден")
        return
    with open(log_path, encoding="utf-8", errors="replace") as f:
        all_lines = f.readlines()
    for line in all_lines[-lines:]:
        print(line.rstrip())


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    show_log(n)
