#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys


def load_env_file(path: str) -> dict:
    env = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export ") :]
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("\"'")  # best-effort
                env[key] = value
    except FileNotFoundError:
        raise SystemExit(f"ENV file not found: {path}")
    return env


def run_vault_json(cmd: list, env: dict) -> dict:
    proc = subprocess.run(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"vault command failed: {' '.join(cmd)}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON from vault: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Vault secrets vs local env file.")
    parser.add_argument("--env-file", default="env/.env", help="Path to .env file")
    parser.add_argument("--env", dest="env_override", default=None, help="Override VAULT_ENV (e.g. prod)")
    parser.add_argument("--out", default="/tmp", help="Output directory for debug files")
    args = parser.parse_args()

    env_file_vars = load_env_file(args.env_file)

    required = ["VAULT_URL", "VAULT_TOKEN", "VAULT_MOUNT_POINT", "VAULT_ENV", "VAULT_VERSION"]
    for k in required:
        if not env_file_vars.get(k):
            raise SystemExit(f"Missing required env var in {args.env_file}: {k}")

    vault_env = args.env_override or env_file_vars["VAULT_ENV"]
    vault_version = str(env_file_vars["VAULT_VERSION"]).strip()
    secret_path = f"{env_file_vars['VAULT_MOUNT_POINT'].rstrip('/')}/{vault_env}"

    vault_env_vars = os.environ.copy()
    vault_env_vars["VAULT_ADDR"] = env_file_vars["VAULT_URL"]
    vault_env_vars["VAULT_TOKEN"] = env_file_vars["VAULT_TOKEN"]

    cmd = ["vault", "kv", "get", "-format=json", secret_path]
    payload = run_vault_json(cmd, vault_env_vars)

    if vault_version == "2":
        data = payload.get("data", {}).get("data", {})
    else:
        data = payload.get("data", {})

    vault_keys = sorted(data.keys())
    local_keys = sorted(k for k in env_file_vars.keys() if not k.startswith("VAULT_"))

    missing_in_vault = sorted(set(local_keys) - set(vault_keys))
    extra_in_vault = sorted(set(vault_keys) - set(local_keys))

    os.makedirs(args.out, exist_ok=True)
    keys_path = os.path.join(args.out, "vault-keys.txt")
    db_path = os.path.join(args.out, "vault-db.json")

    with open(keys_path, "w", encoding="utf-8") as f:
        f.write("\n".join(vault_keys) + ("\n" if vault_keys else ""))

    db_subset = {k: data.get(k) for k in ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_SSLMODE"]}
    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(db_subset, f, indent=2, ensure_ascii=True)
        f.write("\n")

    print(f"VAULT_ENV used: {vault_env}")
    print(f"Secret path: {secret_path}")
    print(f"Saved keys: {keys_path}")
    print(f"Saved DB subset: {db_path}")

    if missing_in_vault:
        print("Missing in Vault (present in .env):")
        for k in missing_in_vault:
            print(f"  - {k}")
    if extra_in_vault:
        print("Extra in Vault (not in .env):")
        for k in extra_in_vault:
            print(f"  - {k}")

    if not missing_in_vault and not extra_in_vault:
        print("Vault keys match local .env keys (excluding VAULT_*).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
