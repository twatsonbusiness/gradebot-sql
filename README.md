# GradeBot

GradeBot turns natural-language questions into SQLite queries using the local
`qwen3.5:4b` Ollama model. It validates and executes those queries against the local
course-grade database, then presents the results in a CLI or Streamlit chat interface.
LangChain and cloud services are not used.

## Requirements

- Python 3.11 or newer
- [Ollama](https://ollama.com/)
- The `qwen3.5:4b` model

## Setup

Pull the model and create the Python environment:

```powershell
ollama pull qwen3.5:4b
uv venv --python 3.11
uv pip install --python .venv\Scripts\python.exe -e ".[web]"
```

Those commands do not require PowerShell script activation. To activate the environment
anyway, use:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

The execution-policy change lasts only for the current PowerShell window. On macOS or
Linux, create an environment with `python3 -m venv .venv`, activate it with
`source .venv/bin/activate`, and run `pip install -e ".[web]"`.

## Run GradeBot

Make sure the local Ollama application is running. If necessary, start its server:

```powershell
ollama serve
```

Start an interactive terminal session without activating the environment:

```powershell
.\.venv\Scripts\python.exe -m gradebot
```

Type `exit` or `quit` to stop. Use `--show-sql` to inspect each checked query, or ask one
question directly:

```powershell
.\.venv\Scripts\python.exe -m gradebot --show-sql "Who taught Business Enterprises in Fall 2020?"
```

Start the web interface:

```powershell
.\.venv\Scripts\streamlit.exe run app.py
```

Open the local URL printed by Streamlit, normally <http://localhost:8501>. Answers include
an expandable result table, generated SQL, and a CSV download. Conversation history is
displayed, but each question should currently be self-contained.

After activating the environment, the shorter `gradebot` and `streamlit run app.py`
commands work as well. The original `chat-sqlbot.py`, `streamlit_sqlbot.py`, and
`sql-make.py` launchers remain compatible.

## Example questions

- What was the weighted average grade in Fall 2020?
- Which departments have published grades in Fall 2020?
- Who taught Business Enterprises in Fall 2020?
- Show the letter-grade distribution for LAW 500M in Fall 2020.
- How many A-range grades were awarded in LAW courses in Spring 2024?

## Important data semantics

- `FS`, `SS`, and `US` mean Fall, Spring, and Summer. For example, `FS20` is Fall 2020.
- Rows with `amount_of_grades = 0` are course listings without published grade results.
  Their zero averages must not be treated as student performance.
- Overall averages must be weighted as `SUM(total_grades) / SUM(amount_of_grades)` over
  rows with published grades. Averaging the already-rounded `average_grade` values is less
  accurate.
- Numeric and letter-grade buckets are two representations of the same graded students;
  adding both sets double-counts them.
- In the currently checked-in data, course listings span many departments, but published
  grade distributions are populated only for `LAW`. Grade questions about other subjects
  should correctly report that no published data is available.

## Safety and recovery

GradeBot opens SQLite in read-only mode and applies a SQLite authorizer that permits only
`SELECT` operations against `course_grades` and an allowlist of ordinary query functions.
It also limits returned rows and SQLite work. Invalid generated SQL is returned to the
local model for one bounded correction attempt.

`OLLAMA_HOST` is restricted to `localhost` or an explicit loopback IP. This prevents a
configuration mistake from sending questions or query results to a remote model server.
If the answer-summary call fails after a query succeeds, GradeBot displays the raw result
instead of discarding it.

## Configuration

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `GRADEBOT_MODEL` | `qwen3.5:4b` | Installed Ollama model name |
| `OLLAMA_HOST` | `http://localhost:11434` | Local Ollama server URL |
| `GRADEBOT_DB` | `grades.db` | SQLite database path |
| `GRADEBOT_TIMEOUT` | `120` | Ollama timeout in seconds (1–600) |
| `GRADEBOT_MAX_ROWS` | `200` | Maximum returned rows (1–1000) |
| `GRADEBOT_MAX_VM_STEPS` | `5000000` | Approximate SQLite work limit |
| `GRADEBOT_SQL_ATTEMPTS` | `2` | SQL generation attempts (1–3) |

## Database builder

The repository includes `grades.db`; normal use does not rebuild it. To intentionally
recreate it from the source CSV:

```powershell
.\.venv\Scripts\gradebot-build-db.exe newgrades.csv
```

The builder creates a validated temporary database and atomically replaces the target,
validates numeric fields, loads in batches,
and creates indexes for common term/course lookups. It will not silently convert malformed
numeric data to null. The compatibility command `python sql-make.py` is also available.

## Development

```powershell
uv pip install --python .venv\Scripts\python.exe -e ".[dev,web]"
.\.venv\Scripts\pytest.exe
.\.venv\Scripts\ruff.exe check .
```

Tests use temporary databases and do not alter `grades.db` or `newgrades.csv`.

## License

Apache-2.0
