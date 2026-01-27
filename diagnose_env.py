#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess
from datetime import datetime

def run(cmd, sink):
    sink.write(f"\n$ {' '.join(cmd)}\n")
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        sink.write(out.strip() + "\n")
    except subprocess.CalledProcessError as e:
        sink.write(e.output.strip() + "\n")
    except FileNotFoundError:
        sink.write("command not found\n")

def main():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(os.getcwd(), f"diagnose_env_{stamp}.txt")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("=== Python ===\n")
        f.write(f"sys.executable: {sys.executable}\n")
        f.write(f"sys.version: {sys.version}\n")

        f.write("\n=== Environment ===\n")
        keys = ["PG_HOST","PG_USER","PG_DATABASE","PG_PORT","PG_PWD","DATABASE_URL"]
        f.write(str({k: ("SET" if os.getenv(k) else "MISSING") for k in keys}) + "\n")

        f.write("\n=== PostgresPool ===\n")
        try:
            from navigator.connections import PostgresPool
            f.write(f"PostgresPool.pool_based: {PostgresPool.pool_based}\n")
        except Exception as e:
            f.write(f"Failed to import navigator.connections.PostgresPool: {e}\n")

        f.write("\n=== Package versions ===\n")
        uv = shutil.which("uv")
        if uv:
            run(["uv", "pip", "list", "--format=freeze"], f)
        else:
            run([sys.executable, "-m", "pip", "freeze"], f)

        f.write("\n=== Targeted packages ===\n")
        if uv:
            run(["uv", "pip", "list", "--format=freeze"], f)
        else:
            run([sys.executable, "-m", "pip", "freeze"], f)

    print(f"Saved report to: {report_path}")

if __name__ == "__main__":
    main()
