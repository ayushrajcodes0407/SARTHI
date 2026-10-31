"""
J.A.R.V.I.S. Database Backup & Disaster Recovery Manager
File: backup_manager.py
Author: Antigravity AI Engineering

Usage:
    Create a backup:
        python backup_manager.py backup [--dest path/to/backup.db]

    Restore a backup:
        python backup_manager.py restore --src path/to/backup.db [--target path/to/restored.db]

    List backups:
        python backup_manager.py list

    Prune old backups (Retention: keep last N backups, default 10):
        python backup_manager.py prune [--keep 10]
"""

import os
import sys
import argparse
import logging
from database import backup_database, restore_database, get_db_path, BASE_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("JARVIS-BackupManager")

BACKUPS_DIR = os.path.join(BASE_DIR, "backups")

def cmd_backup(args):
    dest = args.dest if hasattr(args, 'dest') and args.dest else None
    try:
        saved_path = backup_database(target_path=dest)
        print(f"[SUCCESS] Consistent SQLite backup created at: {saved_path}")
    except Exception as e:
        print(f"[ERROR] Backup failed: {e}", file=sys.stderr)
        sys.exit(1)

def cmd_restore(args):
    if not args.src:
        print("[ERROR] Please provide --src <backup_file_path>", file=sys.stderr)
        sys.exit(1)

    target = args.target if hasattr(args, 'target') and args.target else None
    if not target:
        confirm = input(f"WARNING: This will overwrite the active database at {get_db_path()}. Continue? (y/N): ")
        if confirm.lower() != 'y':
            print("Restore aborted by user.")
            sys.exit(0)

    try:
        restored_path = restore_database(args.src, target_db_path=target)
        print(f"[SUCCESS] Database successfully restored to: {restored_path}")
    except Exception as e:
        print(f"[ERROR] Restore failed: {e}", file=sys.stderr)
        sys.exit(1)

def cmd_list(args):
    if not os.path.exists(BACKUPS_DIR):
        print("No backups directory found.")
        return

    files = [f for f in os.listdir(BACKUPS_DIR) if f.endswith(".db")]
    files.sort(reverse=True)
    if not files:
        print("No database backups found.")
        return

    print("==================================================")
    print(" J.A.R.V.I.S. Local Database Backups")
    print("==================================================")
    for f in files:
        fpath = os.path.join(BACKUPS_DIR, f)
        size_kb = os.path.getsize(fpath) / 1024
        mtime = os.path.getmtime(fpath)
        import datetime
        dt_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"- {f:<35} | {size_kb:8.1f} KB | {dt_str}")

def cmd_prune(args):
    keep = args.keep if hasattr(args, 'keep') and args.keep else 10
    if not os.path.exists(BACKUPS_DIR):
        print("No backups directory found.")
        return

    files = [f for f in os.listdir(BACKUPS_DIR) if f.endswith(".db")]
    files.sort(reverse=True)

    if len(files) <= keep:
        print(f"Total backups ({len(files)}) does not exceed retention limit ({keep}). Nothing pruned.")
        return

    to_prune = files[keep:]
    for f in to_prune:
        p = os.path.join(BACKUPS_DIR, f)
        try:
            os.remove(p)
            print(f"Pruned old backup: {f}")
        except Exception as e:
            print(f"Error removing {f}: {e}", file=sys.stderr)
    print(f"Pruning complete. Kept latest {keep} backups.")

def main():
    parser = argparse.ArgumentParser(description="J.A.R.V.I.S. Database Backup & Disaster Recovery Manager")
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands: backup, restore, list, prune")

    # backup
    p_backup = subparsers.add_parser("backup", help="Create consistent SQLite backup")
    p_backup.add_argument("--dest", help="Destination path for backup file")

    # restore
    p_restore = subparsers.add_parser("restore", help="Restore database from backup file")
    p_restore.add_argument("--src", required=True, help="Source backup file path")
    p_restore.add_argument("--target", help="Target database path (default: active db)")

    # list
    subparsers.add_parser("list", help="List available backups")

    # prune
    p_prune = subparsers.add_parser("prune", help="Prune old backups exceeding retention limit")
    p_prune.add_argument("--keep", type=int, default=10, help="Number of latest backups to retain (default: 10)")

    args = parser.parse_args()
    if args.command == "backup":
        cmd_backup(args)
    elif args.command == "restore":
        cmd_restore(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "prune":
        cmd_prune(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
