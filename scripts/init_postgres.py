#!/usr/bin/env python3
"""Create the PostgreSQL schema used by the PandaStack App deployment.

This script intentionally depends only on psycopg, so it can run before the
full web dependency set is installed.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.postgres_schema import SCHEMA_SQL


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="PostgreSQL connection URL; defaults to DATABASE_URL",
    )
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("DATABASE_URL is required")
    try:
        import psycopg
    except ImportError:
        raise SystemExit(
            "psycopg is required; run: pip install psycopg[binary]"
        )
    with psycopg.connect(args.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(SCHEMA_SQL)
    print("PostgreSQL schema initialized")


if __name__ == "__main__":
    main()
