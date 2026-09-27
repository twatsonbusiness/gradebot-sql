import json
import sqlite3
from pathlib import Path

import pytest

from gradebot.core import (
    ConfigurationError,
    GradeBot,
    GradeBotError,
    OllamaError,
    Settings,
    UnsafeQueryError,
    validate_sql,
)


class FakeClient:
    def __init__(self, replies: list[str | Exception]) -> None:
        self.replies = iter(replies)
        self.calls: list[tuple[list[dict[str, str]], object]] = []

    def chat(self, messages, *, response_format=None):
        self.calls.append((messages, response_format))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


def make_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE course_grades (
            id INTEGER PRIMARY KEY,
            term_code TEXT,
            numeric_term_code REAL,
            subject_code TEXT,
            course_code TEXT,
            course_title TEXT,
            instructors TEXT,
            total_grades REAL,
            amount_of_grades REAL,
            average_grade REAL,
            grade_A REAL
        )"""
    )
    connection.executemany(
        "INSERT INTO course_grades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (1, "FS20", 1204, "LAW", "500M", "Business Enterprises", "A Teacher", 7, 2, 3.5, 1),
            (2, "FS20", 1204, "ACC", "201", "Accounting", "B Teacher", 0, 0, 0, 0),
        ],
    )
    connection.commit()
    connection.close()


def settings(database: Path, *, attempts: int = 2) -> Settings:
    return Settings(database=database, max_sql_attempts=attempts)


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM course_grades",
        "PRAGMA table_info(course_grades)",
        "SELECT * FROM course_grades -- hide something",
        "SELECT * FROM course_grades /* comment */",
    ],
)
def test_validate_sql_rejects_unsafe_shapes(sql: str) -> None:
    with pytest.raises(UnsafeQueryError):
        validate_sql(sql)


def test_ask_executes_structured_read_only_query_and_includes_data_profile(
    tmp_path: Path,
) -> None:
    database = tmp_path / "grades.db"
    make_database(database)
    client = FakeClient([json.dumps({"sql": "SELECT average_grade FROM course_grades;"}), "3.5"])
    bot = GradeBot(settings(database), client=client)

    result = bot.ask("What is the average?")

    assert result.answer == "3.5"
    assert result.columns == ("average_grade",)
    assert result.rows == ((3.5,), (0.0,))
    system_prompt = client.calls[0][0][0]["content"]
    assert "FS=Fall, SS=Spring, US=Summer" in system_prompt
    assert "Subject codes with published grades: LAW" in system_prompt
    assert "filter amount_of_grades > 0" in system_prompt
    assert "not duplicates" in system_prompt


def test_ask_accepts_fenced_sql_from_ollama(tmp_path: Path) -> None:
    database = tmp_path / "grades.db"
    make_database(database)
    client = FakeClient(["```sql\nSELECT COUNT(*) FROM course_grades;\n```", "two rows"])

    result = GradeBot(settings(database), client=client).ask("How many listings?")

    assert result.rows == ((2,),)


def test_invalid_sql_is_repaired_once(tmp_path: Path) -> None:
    database = tmp_path / "grades.db"
    make_database(database)
    client = FakeClient(
        [
            json.dumps({"sql": "DELETE FROM course_grades"}),
            json.dumps({"sql": "SELECT COUNT(*) AS listings FROM course_grades"}),
            "There are two listings.",
        ]
    )

    result = GradeBot(settings(database), client=client).ask("How many listings?")

    assert result.attempts == 2
    assert result.rows == ((2,),)
    assert "previous query was rejected" in client.calls[1][0][1]["content"]
    assert "Only SELECT queries are allowed" in client.calls[1][0][1]["content"]


def test_unusable_sql_reports_bounded_retry_failure(tmp_path: Path) -> None:
    database = tmp_path / "grades.db"
    make_database(database)
    client = FakeClient(["not SQL", "still not SQL"])

    with pytest.raises(GradeBotError, match="after 2 attempts"):
        GradeBot(settings(database), client=client).ask("Impossible request")

    assert len(client.calls) == 2


def test_unaggregated_course_distribution_is_repaired(tmp_path: Path) -> None:
    database = tmp_path / "grades.db"
    make_database(database)
    raw_distribution = "SELECT grade_A FROM course_grades WHERE course_code = '500M'"
    summed_distribution = (
        "SELECT SUM(grade_A) AS grade_A FROM course_grades WHERE course_code = '500M'"
    )
    client = FakeClient(
        [
            json.dumps({"sql": raw_distribution}),
            json.dumps({"sql": summed_distribution}),
            "There was one A grade.",
        ]
    )

    result = GradeBot(settings(database), client=client).ask(
        "Show the grade distribution for LAW 500M."
    )

    assert result.attempts == 2
    assert result.rows == ((1.0,),)
    assert "must SUM each grade bucket" in client.calls[1][0][1]["content"]


def test_incorrect_weighted_average_is_repaired(tmp_path: Path) -> None:
    database = tmp_path / "grades.db"
    make_database(database)
    client = FakeClient(
        [
            json.dumps({"sql": "SELECT AVG(average_grade) FROM course_grades"}),
            json.dumps(
                {
                    "sql": (
                        "SELECT SUM(total_grades) / NULLIF(SUM(amount_of_grades), 0) "
                        "FROM course_grades"
                    )
                }
            ),
            "3.5",
        ]
    )

    result = GradeBot(settings(database), client=client).ask("What is the weighted average?")

    assert result.attempts == 2
    assert result.rows == ((3.5,),)


def test_sqlite_error_is_repaired_once(tmp_path: Path) -> None:
    database = tmp_path / "grades.db"
    make_database(database)
    client = FakeClient(
        [
            json.dumps({"sql": "SELECT fake_column FROM course_grades"}),
            json.dumps({"sql": "SELECT course_title FROM course_grades LIMIT 1"}),
            "Business Enterprises",
        ]
    )

    result = GradeBot(settings(database), client=client).ask("Name a course")

    assert result.attempts == 2
    assert result.rows == (("Business Enterprises",),)
    assert "no such column" in client.calls[1][0][1]["content"]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; DROP TABLE course_grades;",
        "SELECT load_extension('anything') FROM course_grades;",
        "SELECT 1;",
    ],
)
def test_execution_boundary_rejects_unsafe_queries(tmp_path: Path, sql: str) -> None:
    database = tmp_path / "grades.db"
    make_database(database)
    client = FakeClient([json.dumps({"sql": sql})])

    with pytest.raises(GradeBotError, match="couldn't produce a safe, valid query"):
        GradeBot(settings(database, attempts=1), client=client).ask("Unsafe request")

    connection = sqlite3.connect(database)
    assert connection.execute("SELECT COUNT(*) FROM course_grades").fetchone() == (2,)
    connection.close()


def test_authorizer_rejects_other_tables(tmp_path: Path) -> None:
    database = tmp_path / "grades.db"
    make_database(database)
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE secrets (value TEXT)")
    connection.commit()
    connection.close()
    client = FakeClient([json.dumps({"sql": "SELECT * FROM secrets"})])

    with pytest.raises(GradeBotError, match="not authorized|prohibited"):
        GradeBot(settings(database, attempts=1), client=client).ask("Show secrets")


def test_empty_aggregate_returns_deterministic_no_data_answer(tmp_path: Path) -> None:
    database = tmp_path / "grades.db"
    make_database(database)
    client = FakeClient(
        [
            json.dumps(
                {
                    "sql": (
                        "SELECT SUM(total_grades) / NULLIF(SUM(amount_of_grades), 0) "
                        "FROM course_grades WHERE subject_code = 'MTH'"
                    )
                }
            )
        ]
    )

    result = GradeBot(settings(database), client=client).ask("MTH average?")

    assert "couldn't find published data" in result.answer
    assert len(client.calls) == 1


def test_answer_failure_falls_back_to_query_values(tmp_path: Path) -> None:
    database = tmp_path / "grades.db"
    make_database(database)
    client = FakeClient(
        [
            json.dumps({"sql": "SELECT COUNT(*) AS listing_count FROM course_grades"}),
            OllamaError("bad answer"),
        ]
    )

    result = GradeBot(settings(database), client=client).ask("How many listings?")

    assert result.answer == "Listing Count: 2"


def test_missing_database_fails_before_calling_ollama(tmp_path: Path) -> None:
    client = FakeClient([])

    with pytest.raises(GradeBotError, match="Database not found"):
        GradeBot(settings(tmp_path / "missing.db"), client=client).ask("Anything")

    assert client.calls == []


@pytest.mark.parametrize(
    "url",
    ["https://example.com:11434", "http://192.168.1.5:11434", "file:///tmp/ollama"],
)
def test_remote_or_non_http_ollama_urls_are_rejected(url: str) -> None:
    with pytest.raises(ConfigurationError):
        Settings(ollama_url=url)


def test_loopback_ollama_url_without_scheme_is_normalized() -> None:
    assert Settings(ollama_url="127.0.0.1:11434").ollama_url == "http://127.0.0.1:11434"


def test_numeric_configuration_is_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRADEBOT_MAX_ROWS", "many")

    with pytest.raises(ConfigurationError, match="Invalid numeric"):
        Settings.from_env()
