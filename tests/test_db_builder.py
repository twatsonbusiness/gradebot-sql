import csv
import sqlite3
from pathlib import Path

import pytest

from gradebot.db_builder import COLUMN_MAP, build_database


def write_csv(path: Path) -> None:
    row = {column: "0" for column in COLUMN_MAP}
    row.update(
        {
            "term_code": "FS20",
            "numeric_term_code": "1204",
            "subject_code": "LAW",
            "course_code": "500M",
            "course_title": "Business Enterprises",
            "instructors": "A Teacher",
            "total_grades": "7",
            "amount_of_grades": "2",
            "average_grade": "3.5",
        }
    )
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=COLUMN_MAP)
        writer.writeheader()
        writer.writerow(row)


def test_builder_is_idempotent_and_creates_query_indexes(tmp_path: Path) -> None:
    csv_path = tmp_path / "grades.csv"
    database = tmp_path / "grades.db"
    write_csv(csv_path)

    assert build_database(csv_path, database) == 1
    assert build_database(csv_path, database) == 1

    connection = sqlite3.connect(database)
    assert connection.execute("SELECT COUNT(*) FROM course_grades").fetchone() == (1,)
    indexes = {row[1] for row in connection.execute("PRAGMA index_list(course_grades)")}
    connection.close()
    assert indexes == {"idx_course_term", "idx_course_subject_code", "idx_course_title"}


def test_invalid_csv_does_not_replace_existing_data(tmp_path: Path) -> None:
    csv_path = tmp_path / "grades.csv"
    database = tmp_path / "grades.db"
    write_csv(csv_path)
    build_database(csv_path, database)

    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    rows[0]["average_grade"] = "not-a-number"
    with csv_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=COLUMN_MAP)
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(ValueError, match="average_grade"):
        build_database(csv_path, database)

    connection = sqlite3.connect(database)
    assert connection.execute("SELECT average_grade FROM course_grades").fetchone() == (3.5,)
    connection.close()
