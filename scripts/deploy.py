"""
deploy.py — push local spider_robot/ code to the Pi and restart the service.

Usage:
    python3 deploy.py

Reads credentials from environment variables (set once per machine):
    SPIDER_BOT_HOST   e.g. 192.168.4.81 or spiderbot.local
    SPIDER_BOT_USER   e.g. spider
    SPIDER_BOT_PASS   e.g. Divine

Requires: paramiko   (pip install paramiko)
"""

import os
import sys
from pathlib import Path

import paramiko

LOCAL_PACKAGE_DIR = Path(__file__).parent.parent / "spider_robot"
REMOTE_PACKAGE_DIR = "spider_robot"  # relative to the Pi user's home dir
SERVICE_NAME = "spider-robot"
SKIP_DIRS = {"__pycache__"}


def get_credentials():
    host = os.environ.get("SPIDER_BOT_HOST")
    user = os.environ.get("SPIDER_BOT_USER")
    password = os.environ.get("SPIDER_BOT_PASS")
    missing = [name for name, val in [
        ("SPIDER_BOT_HOST", host),
        ("SPIDER_BOT_USER", user),
        ("SPIDER_BOT_PASS", password),
    ] if not val]
    if missing:
        print(f"Missing environment variable(s): {', '.join(missing)}")
        print("Set them, then open a NEW terminal before running this script.")
        sys.exit(1)
    return host, user, password


def upload_directory(sftp: paramiko.SFTPClient, local_dir: Path, remote_dir: str):
    """Recursively upload a local directory to the Pi via SFTP, creating
    remote subfolders as needed. Overwrites files that already exist."""
    try:
        sftp.mkdir(remote_dir)
    except IOError:
        pass  # already exists — fine

    for item in sorted(local_dir.iterdir()):
        if item.name in SKIP_DIRS:
            continue
        remote_path = f"{remote_dir}/{item.name}"
        if item.is_dir():
            upload_directory(sftp, item, remote_path)
        else:
            print(f"  uploading {item.relative_to(local_dir.parent)}")
            sftp.put(str(item), remote_path)


def run_remote_command(client: paramiko.SSHClient, command: str, password: str, sudo: bool = False):
    full_cmd = f"sudo -S {command}" if sudo else command
    stdin, stdout, stderr = client.exec_command(full_cmd, get_pty=True)
    if sudo:
        stdin.write(f"{password}\n")
        stdin.flush()
    exit_status = stdout.channel.recv_exit_status()
    out = stdout.read().decode(errors="ignore")
    err = stderr.read().decode(errors="ignore")
    return exit_status, out, err


def main():
    host, user, password = get_credentials()

    if not LOCAL_PACKAGE_DIR.is_dir():
        print(f"Can't find local package folder: {LOCAL_PACKAGE_DIR}")
        print("Run this script from the folder containing spider_robot/.")
        sys.exit(1)

    print(f"Connecting to {host} as {user}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=host, username=user, password=password, timeout=10)

    print(f"Uploading {LOCAL_PACKAGE_DIR.name}/ -> ~/{REMOTE_PACKAGE_DIR}/ ...")
    sftp = client.open_sftp()
    upload_directory(sftp, LOCAL_PACKAGE_DIR, REMOTE_PACKAGE_DIR)
    sftp.close()
    print("Upload complete.")

    print(f"Restarting {SERVICE_NAME} service...")
    status, out, err = run_remote_command(
        client, f"systemctl restart {SERVICE_NAME}", password, sudo=True
    )
    if status != 0:
        print(f"Restart FAILED (exit {status}):\n{err}")
        client.close()
        sys.exit(1)

    status, out, err = run_remote_command(
        client, f"systemctl is-active {SERVICE_NAME}", password, sudo=True
    )
    print(f"Service state: {out.strip() or err.strip()}")

    client.close()
    print("Done.")


if __name__ == "__main__":
    main()
