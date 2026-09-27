"""Local Ollama-to-SQL pipeline with a read-only SQLite execution boundary."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

TABLE_NAME = "course_grades"
DEFAULT_MODEL = "qwen3.5:9b"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
MAX_SQL_LENGTH = 10_000

ALLOWED_SQL_FUNCTIONS = {
    "abs",
    "avg",
    "coalesce",
    "count",
    "date",
    "datetime",
    "dense_rank",
    "first_value",
    "glob",
    "group_concat",
    "hex",
    "ifnull",
    "instr",
    "lag",
    "last_value",
    "lead",
    "length",
    "like",
    "likely",
    "lower",
    "ltrim",
    "max",
    "min",
    "nth_value",
    "nullif",
    "printf",
    "quote",
    "rank",
    "replace",
    "round",
    "row_number",
    "rtrim",
    "strftime",
    "substr",
    "substring",
    "sum",
    "time",
    "total",
    "trim",
    "typeof",
    "unicode",
    "unlikely",
    "upper",
}

SCHEMA = """course_grades columns:
- id INTEGER: unique listing identifier; it is not a student identifier
- term_code TEXT: semester code (FS=Fall, SS=Spring, US=Summer), e.g. FS20=Fall 2020
- numeric_term_code REAL: sortable semester code
- subject_code TEXT: department code, e.g. LAW
- course_code TEXT: course number, e.g. 500M
- course_title TEXT: course name
- instructors TEXT: one or more names separated by " | "
- total_grades REAL: sum of numeric grade points for students with published grades
- amount_of_grades REAL: number of students with published grades
- average_grade REAL: rounded average for one course listing on a 4.0 scale
- grade_4_0, grade_3_5, grade_3_0, grade_2_5, grade_2_0, grade_1_5,
  grade_1_0, grade_0_0 REAL: student counts at each numeric grade value
- grade_A_plus, grade_A, grade_A_minus, grade_B_plus, grade_B, grade_B_minus,
  grade_C_plus, grade_C, grade_C_minus, grade_D_plus, grade_D, grade_D_minus,
  grade_F REAL: the same graded students expressed as letter-grade counts
- pass, no_grade, deferred, satisfactory, not_satisfactory, credit, no_credit,
  incomplete, withdrawn, unfinished_work REAL: separate non-numeric outcomes
"""

SQL_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {"sql": {"type": "string", "description": "One read-only SQLite query"}},
    "required": ["sql"],
    "additionalProperties": False,
}


class GradeBotError(RuntimeError):
    """Base error suitable for presentation to a user."""


class ConfigurationError(GradeBotError):
    """Raised when local configuration is invalid or unsafe."""


class OllamaError(GradeBotError):
    """Raised when Ollama cannot produce a usable response."""


class UnsafeQueryError(GradeBotError):
    """Raised when generated SQL is outside the read-only policy."""

    def __init__(self, message: str, sql: str = "") -> None:
        super().__init__(message)
        self.sql = sql


class QueryExecutionError(GradeBotError):
    """Raised when a safe-looking query cannot be executed."""

    def __init__(self, message: str, sql: str) -> None:
        super().__init__(message)
        self.sql = sql


@dataclass(frozen=True, slots=True)
class Settings:
    model: str = DEFAULT_MODEL
    ollama_url: str = DEFAULT_OLLAMA_URL
    database: Path = Path("grades.db")
    timeout_seconds: float = 120.0
    max_rows: int = 200
    max_vm_steps: int = 5_000_000
    max_sql_attempts: int = 2

    def __post_init__(self) -> None:
        normalized_url = _validate_local_ollama_url(self.ollama_url)
        object.__setattr__(self, "ollama_url", normalized_url)
        object.__setattr__(self, "database", Path(self.database))
        if not self.model.strip():
            raise ConfigurationError("GRADEBOT_MODEL cannot be empty.")
        if not 1 <= self.timeout_seconds <= 600:
            raise ConfigurationError("GRADEBOT_TIMEOUT must be between 1 and 600 seconds.")
        if not 1 <= self.max_rows <= 1_000:
            raise ConfigurationError("GRADEBOT_MAX_ROWS must be between 1 and 1000.")
        if self.max_vm_steps < 10_000:
            raise ConfigurationError("GRADEBOT_MAX_VM_STEPS must be at least 10000.")
        if not 1 <= self.max_sql_attempts <= 3:
            raise ConfigurationError("GRADEBOT_SQL_ATTEMPTS must be between 1 and 3.")

    @classmethod
    def from_env(cls) -> Settings:
        try:
            return cls(
                model=os.getenv("GRADEBOT_MODEL", DEFAULT_MODEL),
                ollama_url=os.getenv("OLLAMA_HOST", DEFAULT_OLLAMA_URL),
                database=Path(os.getenv("GRADEBOT_DB", "grades.db")),
                timeout_seconds=float(os.getenv("GRADEBOT_TIMEOUT", "120")),
                max_rows=int(os.getenv("GRADEBOT_MAX_ROWS", "200")),
                max_vm_steps=int(os.getenv("GRADEBOT_MAX_VM_STEPS", "5000000")),
                max_sql_attempts=int(os.getenv("GRADEBOT_SQL_ATTEMPTS", "2")),
            )
        except ValueError as exc:
            raise ConfigurationError(f"Invalid numeric GradeBot setting: {exc}") from exc


@dataclass(frozen=True, slots=True)
class DataProfile:
    row_count: int
    published_grade_rows: int
    terms: tuple[str, ...]
    subjects_with_grades: tuple[str, ...]

    def prompt_context(self) -> str:
        terms = ", ".join(self.terms)
        subjects = ", ".join(self.subjects_with_grades) or "none"
        return (
            f"This database has {self.row_count:,} course listings and "
            f"{self.published_grade_rows:,} listings with published grades. "
            f"Available terms: {terms}. Subject codes with published grades: {subjects}."
        )


@dataclass(frozen=True, slots=True)
class QueryResult:
    answer: str
    sql: str
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    truncated: bool = False
    attempts: int = 1


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout_seconds: float = 120.0) -> None:
        self.base_url = _validate_local_ollama_url(base_url)
        self.model = model
        self.timeout_seconds = timeout_seconds

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"temperature": 0, "num_predict": 512},
        }
        if response_format is not None:
            payload["format"] = response_format

        request = Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                body = json.load(response)
        except HTTPError as exc:
            detail = _ollama_http_error(exc)
            if exc.code == 404 and "model" in detail.lower():
                detail += f" Run `ollama pull {self.model}` and try again."
            raise OllamaError(f"Ollama returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise OllamaError(
                f"Could not reach local Ollama at {self.base_url}. Start Ollama with "
                "`ollama serve`, then try again."
            ) from exc
        except TimeoutError as exc:
            raise OllamaError(
                f"Ollama did not respond within {self.timeout_seconds:g} seconds. "
                "The model may still be loading; try again or increase GRADEBOT_TIMEOUT."
            ) from exc
        except json.JSONDecodeError as exc:
            raise OllamaError("Ollama returned an invalid HTTP response.") from exc

        if not isinstance(body, dict):
            raise OllamaError("Ollama returned an unexpected response shape.")
        message = body.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise OllamaError("Ollama returned an empty response.")
        return content.strip()


class _ReadOnlyAuthorizer:
    def __init__(self) -> None:
        self.read_grade_table = False

    def __call__(
        self, action: int, arg1: str | None, arg2: str | None, *_: Any
    ) -> int:
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
        recursive = getattr(sqlite3, "SQLITE_RECURSIVE", None)
        if recursive is not None:
            allowed.add(recursive)
        if action == sqlite3.SQLITE_READ:
            if arg1 != TABLE_NAME:
                return sqlite3.SQLITE_DENY
            self.read_grade_table = True
        if (
            action == sqlite3.SQLITE_FUNCTION
            and (arg2 or "").lower() not in ALLOWED_SQL_FUNCTIONS
        ):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY


class GradeBot:
    def __init__(
        self, settings: Settings | None = None, client: OllamaClient | None = None
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.client = client or OllamaClient(
            self.settings.ollama_url,
            self.settings.model,
            self.settings.timeout_seconds,
        )
        self._data_profile: DataProfile | None = None

    def ask(self, question: str) -> QueryResult:
        question = question.strip()
        if not question:
            raise GradeBotError("Please enter a question.")

        profile = self.data_profile()
        feedback: str | None = None
        last_error: UnsafeQueryError | QueryExecutionError | None = None

        for attempt in range(1, self.settings.max_sql_attempts + 1):
            try:
                sql = self._generate_sql(question, profile, feedback)
                columns, rows, truncated = self._execute(sql)
            except (UnsafeQueryError, QueryExecutionError) as exc:
                last_error = exc
                feedback = _repair_feedback(exc)
                continue

            if _result_has_no_data(rows):
                return QueryResult(
                    answer=(
                        "I couldn't find published data matching that question. Course listings "
                        "whose `amount_of_grades` is zero do not have grade results available."
                    ),
                    sql=sql,
                    columns=columns,
                    rows=rows,
                    truncated=truncated,
                    attempts=attempt,
                )

            try:
                answer = self._generate_answer(question, sql, columns, rows, truncated)
            except OllamaError:
                answer = _fallback_answer(columns, rows, truncated)
            return QueryResult(answer, sql, columns, rows, truncated, attempt)

        detail = str(last_error) if last_error else "unknown query error"
        raise GradeBotError(
            f"I couldn't produce a safe, valid query after {self.settings.max_sql_attempts} "
            f"attempts. Last issue: {detail}"
        ) from last_error

    def data_profile(self) -> DataProfile:
        if self._data_profile is not None:
            return self._data_profile
        database = self._database_path()
        try:
            connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
            row_count, published = connection.execute(
                "SELECT COUNT(*), SUM(amount_of_grades > 0) FROM course_grades"
            ).fetchone()
            terms = tuple(
                row[0]
                for row in connection.execute(
                    "SELECT term_code FROM course_grades GROUP BY term_code "
                    "ORDER BY MIN(numeric_term_code)"
                )
            )
            subjects = tuple(
                row[0]
                for row in connection.execute(
                    "SELECT subject_code FROM course_grades WHERE amount_of_grades > 0 "
                    "GROUP BY subject_code ORDER BY subject_code"
                )
            )
        except sqlite3.Error as exc:
            raise GradeBotError(
                f"Could not read the expected `{TABLE_NAME}` table from {database}: {exc}"
            ) from exc
        finally:
            if "connection" in locals():
                connection.close()
        self._data_profile = DataProfile(int(row_count), int(published or 0), terms, subjects)
        return self._data_profile

    def _generate_sql(
        self, question: str, profile: DataProfile, feedback: str | None = None
    ) -> str:
        system = f"""You translate grade-data questions into one SQLite query.

{SCHEMA}
Current data profile:
{profile.prompt_context()}

Accuracy rules:
- A zero `amount_of_grades` means grades are unavailable, not that students earned zero.
- For any grade average, distribution, ranking, or comparison, filter amount_of_grades > 0.
- For an overall average across listings, use the precise weighted calculation
  SUM(total_grades) / NULLIF(SUM(amount_of_grades), 0), not AVG(average_grade).
- Round computed grade averages to three decimal places in SQL for readable results.
- For one specific listing, average_grade is acceptable. It is rounded to one decimal place.
- Numeric and letter grade buckets represent the same students. Never add those two sets.
- "A" means grade_A; "A-range" means grade_A_plus + grade_A + grade_A_minus.
- Count students or issued grades using amount_of_grades; COUNT(*) counts course listings.
- A course is identified by subject_code plus course_code. Use both when supplied.
- Multiple matching rows can be legitimate sections or instructors, not duplicates. For a
  course-, department-, or term-level count or distribution, SUM each requested bucket over
  every matching row. Group only by dimensions the user asked to compare.
- Likewise, aggregate a course-level average across all matching listings with the weighted
  formula unless the user explicitly asks about one instructor or section.
- Match text case-insensitively with LIKE. Instructor fields can contain several names.
- If the requested subject has no published grades, return a query whose aggregate is NULL
  or whose result is empty; do not substitute another subject or invent data.

Safety and output rules:
- Query only course_grades and return exactly one SELECT statement; WITH is allowed.
- Never modify data or configuration and never call external or file-reading functions.
- Do not include SQL comments.
- Select only columns needed for the answer.
- Use LIMIT {self.settings.max_rows} for non-aggregate result lists.
- Respond using the requested JSON schema.
"""
        user_content = question
        if feedback:
            user_content += "\n\nYour previous query was rejected. Correct it using "
            user_content += "this diagnostic:\n" + feedback
        raw = self.client.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            response_format=SQL_RESPONSE_SCHEMA,
        )
        sql = _extract_sql(raw)
        sql = validate_sql(sql)
        if issue := _semantic_sql_issue(question, sql):
            raise UnsafeQueryError(issue, sql)
        return sql

    def _execute(self, sql: str) -> tuple[tuple[str, ...], tuple[tuple[Any, ...], ...], bool]:
        database = self._database_path()
        connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        authorizer = _ReadOnlyAuthorizer()
        connection.set_authorizer(authorizer)
        connection.set_progress_handler(_cancel_query, self.settings.max_vm_steps)
        try:
            cursor = connection.execute(sql)
            columns = tuple(item[0] for item in (cursor.description or ()))
            fetched = cursor.fetchmany(self.settings.max_rows + 1)
        except sqlite3.Error as exc:
            if "interrupted" in str(exc).lower():
                message = "Query exceeded the configured work limit. Make it more selective."
            else:
                message = f"SQLite rejected the query: {exc}"
            raise QueryExecutionError(message, sql) from exc
        finally:
            connection.close()

        if not authorizer.read_grade_table:
            raise QueryExecutionError(f"Query must read from `{TABLE_NAME}`.", sql)
        truncated = len(fetched) > self.settings.max_rows
        return columns, tuple(fetched[: self.settings.max_rows]), truncated

    def _generate_answer(
        self,
        question: str,
        sql: str,
        columns: tuple[str, ...],
        rows: tuple[tuple[Any, ...], ...],
        truncated: bool,
    ) -> str:
        data = {
            "question": question,
            "sql": sql,
            "columns": columns,
            "rows": rows,
            "truncated": truncated,
        }
        system = """Answer the question using only the supplied SQLite result.
Be concise and plainspoken. Preserve course codes, names, and counts. Show computed grade
averages to no more than three decimal places.
Do not infer facts absent from the rows, and never dismiss legitimate rows as duplicates.
Mention truncation when true.
Do not show SQL unless the question specifically asks for SQL."""
        return self.client.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(data, default=str)},
            ]
        )

    def _database_path(self) -> Path:
        database = self.settings.database.expanduser().resolve()
        if not database.is_file():
            raise GradeBotError(
                f"Database not found at {database}. Run `gradebot-build-db` first."
            )
        return database


def validate_sql(sql: Any) -> str:
    if not isinstance(sql, str):
        raise UnsafeQueryError("The model did not return SQL text.")
    sql = sql.strip()
    if not sql:
        raise UnsafeQueryError("The model returned an empty SQL query.", sql)
    if len(sql) > MAX_SQL_LENGTH:
        raise UnsafeQueryError("The generated SQL is unreasonably long.", sql)
    if "\x00" in sql:
        raise UnsafeQueryError("The query contains an invalid null byte.", sql)
    if "--" in sql or "/*" in sql or "*/" in sql:
        raise UnsafeQueryError("SQL comments are not allowed.", sql)
    if not re.match(r"^(SELECT|WITH)\b", sql, flags=re.IGNORECASE):
        raise UnsafeQueryError("Only SELECT queries are allowed.", sql)
    return sql


def _extract_sql(raw: str) -> str:
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, dict) and isinstance(decoded.get("sql"), str):
        return decoded["sql"]
    fenced = re.fullmatch(r"```(?:sql)?\s*(.*?)\s*```", raw.strip(), flags=re.I | re.S)
    return fenced.group(1) if fenced else raw


def _repair_feedback(error: UnsafeQueryError | QueryExecutionError) -> str:
    sql = error.sql[:2_000] if error.sql else "(no usable SQL was returned)"
    return f"Rejected SQL:\n{sql}\nReason: {error}"


def _semantic_sql_issue(question: str, sql: str) -> str | None:
    question_lower = question.lower()
    compact_sql = re.sub(r"\s+", "", sql.lower())
    if "weighted average" in question_lower and not (
        "sum(total_grades)" in compact_sql and "sum(amount_of_grades)" in compact_sql
    ):
        return (
            "A weighted-average question must divide SUM(total_grades) by "
            "SUM(amount_of_grades)."
        )

    asks_for_bucket_total = "distribution" in question_lower or bool(
        re.search(r"\b(how many|number of|total)\b.*\bgrades?\b", question_lower)
    )
    asks_for_individual_rows = any(
        phrase in question_lower
        for phrase in ("each section", "by section")
    )
    if (
        asks_for_bucket_total
        and "grade_" in compact_sql
        and "sum(" not in compact_sql
        and not asks_for_individual_rows
    ):
        return (
            "A course-, department-, or term-level grade distribution must SUM each grade "
            "bucket across all matching listings."
        )
    return None


def _result_has_no_data(rows: tuple[tuple[Any, ...], ...]) -> bool:
    return not rows or all(value is None for row in rows for value in row)


def _fallback_answer(
    columns: tuple[str, ...], rows: tuple[tuple[Any, ...], ...], truncated: bool
) -> str:
    if len(columns) == 1 and len(rows) == 1:
        return f"{columns[0].replace('_', ' ').title()}: {rows[0][0]}"
    previews = []
    for row in rows[:5]:
        fields = (f"{name}={value}" for name, value in zip(columns, row, strict=True))
        previews.append(", ".join(fields))
    suffix = " Results were truncated." if truncated else ""
    return "The query succeeded. " + "; ".join(previews) + suffix


def _validate_local_ollama_url(value: str) -> str:
    value = value.strip()
    if "://" not in value:
        value = "http://" + value
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ConfigurationError("OLLAMA_HOST must be an HTTP URL for a local Ollama server.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ConfigurationError("OLLAMA_HOST cannot contain credentials, a query, or a fragment.")
    if parsed.path not in {"", "/"}:
        raise ConfigurationError("OLLAMA_HOST cannot contain a URL path.")
    try:
        local = parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        local = False
    if not local:
        raise ConfigurationError(
            "OLLAMA_HOST must resolve explicitly to localhost or a loopback IP so grade data "
            "cannot be sent to a remote service."
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise ConfigurationError(f"OLLAMA_HOST has an invalid port: {exc}") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ConfigurationError("OLLAMA_HOST port must be between 1 and 65535.")
    return value.rstrip("/")


def _ollama_http_error(error: HTTPError) -> str:
    raw = error.read().decode("utf-8", errors="replace")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        return raw[:500] or error.reason
    detail = body.get("error") if isinstance(body, dict) else None
    return str(detail or error.reason)[:500]


def _cancel_query() -> int:
    return 1
