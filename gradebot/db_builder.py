"""Build the SQLite grade database from the source CSV."""

from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import tempfile
from pathlib import Path

COLUMN_MAP = {
    "term_code": "term_code", "numeric_term_code": "numeric_term_code",
    "subject_code": "subject_code", "course_code": "course_code",
    "course_title": "course_title", "instructors": "instructors",
    "total_grades": "total_grades", "amount_of_grades": "amount_of_grades",
    "average_grade": "average_grade", "4.0": "grade_4_0", "3.5": "grade_3_5",
    "3.0": "grade_3_0", "2.5": "grade_2_5", "2.0": "grade_2_0",
    "1.5": "grade_1_5", "1.0": "grade_1_0", "0.0": "grade_0_0",
    "A+": "grade_A_plus", "A": "grade_A", "A-": "grade_A_minus",
    "B+": "grade_B_plus", "B": "grade_B", "B-": "grade_B_minus",
    "C+": "grade_C_plus", "C": "grade_C", "C-": "grade_C_minus",
    "D+": "grade_D_plus", "D": "grade_D", "D-": "grade_D_minus",
    "F": "grade_F", "pass": "pass", "no_grade": "no_grade", "deferred": "deferred",
    "satisfactory": "satisfactory", "not_satisfactory": "not_satisfactory",
    "credit": "credit", "no_credit": "no_credit", "incomplete": "incomplete",
    "withdrawn": "withdrawn", "unfinished_work": "unfinished_work",
}

TEXT_COLUMNS = {"term_code", "subject_code", "course_code", "course_title", "instructors"}


def build_database(csv_path: Path, database_path: Path) -> int:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{database_path.name}.",
        suffix=".tmp",
        dir=database_path.parent,
        delete=False,
    ) as temporary_file:
        temporary_path = Path(temporary_file.name)
    try:
        count = _populate_database(csv_path, temporary_path)
        os.replace(temporary_path, database_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return count


def _populate_database(csv_path: Path, database_path: Path) -> int:
    columns = list(COLUMN_MAP.values())
    definitions = [
        f'"{column}" {"TEXT" if original in TEXT_COLUMNS else "REAL"}'
        for original, column in COLUMN_MAP.items()
    ]
    placeholders = ", ".join("?" for _ in columns)
    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    insert_sql = f"INSERT INTO course_grades ({quoted_columns}) VALUES ({placeholders})"

    count = 0
    connection = sqlite3.connect(database_path)
    try:
        with connection:
            connection.execute(
                "CREATE TABLE course_grades (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                + ", ".join(definitions) + ")"
            )
            with csv_path.open(newline="", encoding="utf-8-sig") as csv_file:
                reader = csv.DictReader(csv_file)
                missing = set(COLUMN_MAP) - set(reader.fieldnames or ())
                if missing:
                    raise ValueError(f"CSV is missing columns: {', '.join(sorted(missing))}")
                batch: list[tuple[object, ...]] = []
                for line_number, row in enumerate(reader, start=2):
                    values: list[object] = []
                    for original in COLUMN_MAP:
                        value = row[original].strip()
                        values.append(
                            value
                            if original in TEXT_COLUMNS
                            else _to_number(value, original, line_number)
                        )
                    batch.append(tuple(values))
                    count += 1
                    if len(batch) == 1_000:
                        connection.executemany(insert_sql, batch)
                        batch.clear()
                if batch:
                    connection.executemany(insert_sql, batch)
                if count == 0:
                    raise ValueError("CSV contains no data rows; the database was not replaced.")
            connection.execute("CREATE INDEX idx_course_term ON course_grades(term_code)")
            connection.execute(
                "CREATE INDEX idx_course_subject_code ON course_grades(subject_code, course_code)"
            )
            connection.execute("CREATE INDEX idx_course_title ON course_grades(course_title)")
    finally:
        connection.close()
    return count


def _to_number(value: str, column: str, line_number: int) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid number {value!r} for column {column!r} on CSV line {line_number}."
        ) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Build grades.db from the grade CSV.")
    parser.add_argument("csv", nargs="?", type=Path, default=Path("newgrades.csv"))
    parser.add_argument("--database", type=Path, default=Path("grades.db"))
    args = parser.parse_args()
    count = build_database(args.csv, args.database)
    print(f"Loaded {count:,} rows into {args.database}.")
