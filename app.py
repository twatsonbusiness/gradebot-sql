"""Streamlit chat interface for GradeBot."""

from __future__ import annotations

import csv
import io
from typing import Any

import streamlit as st

from gradebot import ConfigurationError, GradeBot, GradeBotError, Settings

st.set_page_config(page_title="GradeBot", page_icon="📚", layout="centered")

try:
    settings = Settings.from_env()
except ConfigurationError as exc:
    st.error(f"Configuration error: {exc}")
    st.stop()

st.title("📚 GradeBot")
st.caption("Ask questions about course listings and published grades. Everything stays local.")


@st.cache_resource
def get_bot(config: Settings) -> GradeBot:
    return GradeBot(config)


def _table_rows(message: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(zip(message["columns"], row, strict=True))
        for row in message.get("rows", [])
    ]


def _csv_bytes(message: dict[str, Any]) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(message["columns"])
    writer.writerows(message.get("rows", []))
    return output.getvalue().encode("utf-8")


def render_assistant(message: dict[str, Any], key: str) -> None:
    if message.get("error"):
        st.error(message["content"])
        return

    st.markdown(message["content"])
    if message.get("attempts", 1) > 1:
        st.caption("GradeBot corrected an invalid first query before producing this answer.")

    columns = message.get("columns", [])
    rows = message.get("rows", [])
    if len(columns) == 1 and len(rows) == 1 and rows[0][0] is not None:
        st.metric(columns[0].replace("_", " ").title(), rows[0][0])

    with st.expander("Query and result details"):
        st.code(message["sql"], language="sql")
        if rows:
            st.dataframe(_table_rows(message), width="stretch", hide_index=True)
            st.download_button(
                "Download result as CSV",
                _csv_bytes(message),
                file_name="gradebot-result.csv",
                mime="text/csv",
                key=f"download-{key}",
            )
        else:
            st.info("The query returned no rows.")
        if message.get("truncated"):
            st.warning(f"Only the first {settings.max_rows} rows are shown.")


bot = get_bot(settings)

with st.sidebar:
    st.header("Local configuration")
    st.code(settings.model, language=None)
    st.caption(f"Database: {settings.database}")
    try:
        profile = bot.data_profile()
        st.success("Grade database ready")
        st.metric("Course listings", f"{profile.row_count:,}")
        st.metric("Listings with grades", f"{profile.published_grade_rows:,}")
        subjects = ", ".join(profile.subjects_with_grades) or "None"
        st.caption(f"Subjects with published grades: {subjects}")
    except GradeBotError as exc:
        st.error(str(exc))
    st.divider()
    if st.button("Clear conversation", width="stretch"):
        st.session_state.messages = []
        st.rerun()

if "messages" not in st.session_state:
    st.session_state.messages = []

if not st.session_state.messages:
    st.info(
        "Try: “What was the weighted average grade in Fall 2020?” or "
        "“Who taught Business Enterprises?”"
    )

for index, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        if message["role"] == "assistant":
            render_assistant(message, str(index))
        else:
            st.markdown(message["content"])

if question := st.chat_input("Ask about a semester, course, instructor, or grade distribution"):
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Generating and checking a read-only query…"):
                result = bot.ask(question)
            message = {
                "role": "assistant",
                "content": result.answer,
                "sql": result.sql,
                "columns": list(result.columns),
                "rows": [list(row) for row in result.rows],
                "truncated": result.truncated,
                "attempts": result.attempts,
            }
        except GradeBotError as exc:
            message = {"role": "assistant", "content": str(exc), "error": True}
        st.session_state.messages.append(message)
        render_assistant(message, str(len(st.session_state.messages) - 1))
