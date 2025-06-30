import streamlit as st
import time
import sys
from io import StringIO
from threading import Thread
from concurrent.futures import ThreadPoolExecutor
from langchain_community.utilities.sql_database import SQLDatabase
from langchain_community.agent_toolkits.sql.base import create_sql_agent
from langchain.agents.agent_types import AgentType
from langchain_ollama import OllamaLLM
from langchain_core.messages import SystemMessage

# --- Dual writer for console + in-memory buffer ---
class TeeStdout:
    def __init__(self, *targets):
        self.targets = targets

    def write(self, data):
        for target in self.targets:
            target.write(data)
            target.flush()

    def flush(self):
        for target in self.targets:
            target.flush()

# --- Streamlit UI ---
st.set_page_config(page_title="📚 GradeBot", page_icon="🤖")
st.title("📚 GradeBot - Ask About Course Grades")

@st.cache_resource
def setup_agent():
    db = SQLDatabase.from_uri("sqlite:///grades.db", include_tables=["course_grades"])
    llm = OllamaLLM(model="mistral", temperature=0)
    schema_message = SystemMessage(content=(
        "- term_code: ... \n"
        "SELECT AVG(average_grade) FROM course_grades WHERE term_code = 'FS20';"
    ))
    return create_sql_agent(
        llm=llm,
        db=db,
        agent_type=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
        verbose=True,
        handle_parsing_errors=True,
        system_message=schema_message
    )

agent_executor = setup_agent()
user_input = st.text_input("Ask a question about grades or courses:")

if user_input:
    status_box = st.empty()
    log_box = st.empty()
    output_box = st.empty()

    status_messages = [
        "Thinking...",
        "Thinking...",
        "Thinking...",
        "Thinking...",
        "Accessing Database...",
        "Accessing Database...",
        "Accessing Database...",
        "Accessing Database...",
        "Reading Data...",
        "Reading Data...",
        "Reading Data...",
        "Reading Data...",
        "Making SQL Query...",
        "Making SQL Query...",
        "Making SQL Query...",
        "Making SQL Query...",
        "Gathering Data...",
        "Gathering Data...",
        "Gathering Data...",
        "Gathering Data...",
        "Finalizing Answer...",
        "Finalizing Answer...",
        "Finalizing Answer...",
        "Finalizing Answer..."
    ]

    log_buffer = StringIO()

    def run_agent():
        # Tee console + in-memory log
        original_stdout = sys.stdout
        sys.stdout = TeeStdout(original_stdout, log_buffer)
        try:
            result = agent_executor.invoke({"input": user_input})
        finally:
            sys.stdout = original_stdout  # always restore
        return result

    # Run the agent in a background thread
    with ThreadPoolExecutor() as executor:
        future = executor.submit(run_agent)

        i = 0
        while not future.done():
            # Status message

            status_box.info(status_messages[i % len(status_messages)])


            # Show current logs
            log_output = log_buffer.getvalue()
            log_box.markdown(
                f"""
                <div style="height: 200px; overflow-y: auto; background-color: #0e1117; color: #f8f8f2; padding: 10px; border-radius: 8px; font-family: monospace; font-size: 13px;">
                    <pre>{log_output}</pre>
                </div>
                """,
                unsafe_allow_html=True
            )
            time.sleep(5)
            i += 1

        # Final results
        # Final results
        try:
            result = future.result()
            status_box.empty()
            log_box.markdown(
                f"""
                <div style="height: 200px; overflow-y: auto; background-color: #0e1117; color: #f8f8f2; padding: 10px; border-radius: 8px; font-family: monospace; font-size: 13px;">
                    <pre>{log_buffer.getvalue()}</pre>
                </div>
                """,
                unsafe_allow_html=True
            )
            output_box.success("🤖 " + result["output"])
        except Exception as e:
            status_box.error(f"❌ Error: {e}")

