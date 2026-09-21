#!/usr/bin/env python3
"""Create the PostgreSQL schema used by the PandaStack App deployment."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.postgres_db import PostgresMemoryDatabase


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="PostgreSQL connection URL; defaults to the DATABASE_URL environment variable",
    )
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("DATABASE_URL is required")
    database = PostgresMemoryDatabase(args.database_url)
    database.initialize()
    print("PostgreSQL schema initialized")


if __name__ == "__main__":
    main()

