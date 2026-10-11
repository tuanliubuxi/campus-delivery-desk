"""Copy a live WAL-mode SQLite database into one self-contained backup file."""

import sqlite3
import sys
from contextlib import closing
from pathlib import Path


def main():
    if len(sys.argv) != 3:
        raise SystemExit("Usage: snapshot_sqlite.py SOURCE DESTINATION")
    source, destination = (Path(argument).resolve() for argument in sys.argv[1:])
    if not source.is_file() or destination.exists():
        raise SystemExit("Source must exist and snapshot destination must not exist")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source)) as live:
        with closing(sqlite3.connect(destination)) as snapshot:
            live.backup(snapshot)
            if snapshot.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise SystemExit("SQLite snapshot integrity check failed")
    print(f"Verified SQLite online snapshot: {destination}")


if __name__ == "__main__":
    main()
