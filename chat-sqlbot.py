from langchain_community.utilities.sql_database import SQLDatabase
from langchain_community.agent_toolkits.sql.base import create_sql_agent
from langchain.agents.agent_types import AgentType
from langchain_ollama import OllamaLLM
from langchain_core.prompts import MessagesPlaceholder
from langchain_core.messages import SystemMessage


def main():
    # Load the SQLite database and limit scope to course_grades table
    db = SQLDatabase.from_uri("sqlite:///grades.db", include_tables=["course_grades"])

    # Define your model
    llm = OllamaLLM(model="mistral", temperature=0)

    # Inject the correct schema as a system message
    schema_message = SystemMessage(
        content=(
            "- term_code: Use this to filter by semester (e.g., FS20 = Fall 2020).\n"
            "- numeric_term_code: Numeric version of the term (e.g., 1204).\n"
            "- subject_code: The department offering the course (e.g., LAW).\n"
            "- course_code: The course number (e.g., 500M).\n"
            "- course_title: Use this to reference the course name.\n"
            "- instructors: This column contains the name(s) of the professor(s) who taught the course. Use this column to answer any question about who taught what.\n"
            "- total_grades: Sum of all grade values assigned in the course.\n"
            "- amount_of_grades: Number of grades issued in the course.\n"
            "- average_grade: Use this to analyze or compare grade averages.\n"

            "Use the average_grade column to sort or compare course difficulty.\n"
            "Use the course_title column to report the name of the course.\n"
            "Use instructors to find who taught a course.\n"
            "Important instructions:\n"
            "- Always write full valid SQL queries starting with 'SELECT' and ending with ';'.\n"
            "- Use the exact table name course_grades.\n"
            "- Use the exact column names provided.\n"
            "- Do NOT output incomplete SQL expressions like 'AVG(grade)'.\n"
            "- Return only SQL statements, no additional explanation.\n"
            "Example correct queries:"
            "SELECT course_title, average_grade FROM course_grades ORDER BY average_grade DESC LIMIT 1;"
            "SELECT AVG(average_grade) FROM course_grades WHERE term_code = 'FS20';"
        )
    )

    # Create agent
    agent_executor = create_sql_agent(
        llm=llm,
        db=db,
        agent_type=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
        verbose=True,
        handle_parsing_errors=True,
        system_message=schema_message  # 👈 injects schema into the agent's context
    )

    print("📚 GradeBot is ready!")
    print("Ask a question about grades or courses. Type 'exit' to quit.\n")

    while True:
        question = input("You: ")
        if question.strip().lower() == "exit":
            print("👋 Goodbye!")
            break

        try:
            response = agent_executor.invoke({"input": question})
            print(f"Bot: {response['output']}\n")
        except Exception as e:
            print(f"❌ Error: {e}\n")


if __name__ == "__main__":
    main()