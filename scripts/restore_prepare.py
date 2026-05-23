from __future__ import annotations

import getpass
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def safe_extract(tar: tarfile.TarFile, path: Path) -> None:
    base = path.resolve()

    for member in tar.getmembers():
        target = (path / member.name).resolve()
        if not str(target).startswith(str(base)):
            fail(f"Unsafe tar path: {member.name}")

    tar.extractall(path)


def main() -> None:
    if len(sys.argv) != 2:
        fail("Usage: python scripts/restore_prepare.py BACKUP.tar.gz.enc")

    enc_path = Path(sys.argv[1]).expanduser().resolve()
    if not enc_path.exists():
        fail(f"File not found: {enc_path}")

    if shutil.which("openssl") is None:
        fail("openssl not found. Install OpenSSL first.")

    output_root = Path.cwd() / "restored_void_backup"
    output_root.mkdir(exist_ok=True)

    restored_tar = output_root / "restored.tar.gz"

    password = getpass.getpass("Backup password: ")

    print("== Decrypt ==")
    subprocess.run(
        [
            "openssl",
            "enc",
            "-d",
            "-aes-256-cbc",
            "-pbkdf2",
            "-iter",
            "200000",
            "-in",
            str(enc_path),
            "-out",
            str(restored_tar),
            "-pass",
            f"pass:{password}",
        ],
        check=True,
    )

    print("== Extract outer backup ==")
    outer_dir = output_root / "outer"
    if outer_dir.exists():
        shutil.rmtree(outer_dir)
    outer_dir.mkdir()

    with tarfile.open(restored_tar, "r:gz") as tar:
        safe_extract(tar, outer_dir)

    project_archives = list(outer_dir.rglob("project_files.tar.gz"))
    if not project_archives:
        fail("project_files.tar.gz not found inside backup")

    project_archive = project_archives[0]

    print("== Extract project files ==")
    project_dir = output_root / "project"
    if project_dir.exists():
        shutil.rmtree(project_dir)
    project_dir.mkdir()

    with tarfile.open(project_archive, "r:gz") as tar:
        safe_extract(tar, project_dir)

    restored_project = project_dir / "telegram_bot"

    print("")
    print("RESTORE PREPARE OK")
    print(f"Backup root:      {output_root}")
    print(f"Outer backup:     {outer_dir}")
    print(f"Project restored: {restored_project}")
    print("")
    print("Important files:")

    for name in ["botdb.sql", "env.prod", "manifest.txt"]:
        matches = list(outer_dir.rglob(name))
        if matches:
            print(f"- {name}: {matches[0]}")
        else:
            print(f"- {name}: NOT FOUND")

    print("")
    print("Next deploy steps are server-side:")
    print("1. copy restored project to /home/vpn/telegram_bot")
    print("2. copy env.prod to /home/vpn/telegram_bot/.env")
    print("3. restore PostgreSQL from botdb.sql")
    print("4. restore systemd/nginx configs")
    print("5. install venv/deps")
    print("6. run smoke checks")


if __name__ == "__main__":
    main()
