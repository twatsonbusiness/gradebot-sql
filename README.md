
# GradeBot

Ask natural language questions about course grades using a local SQLite database and an LLM-powered agent.

![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)
![Streamlit](https://img.shields.io/badge/streamlit-app-red?logo=streamlit)
![LangChain](https://img.shields.io/badge/langchain-powered-blueviolet)
![License](https://img.shields.io/badge/license-Apache%202.0-green)

---

## What is GradeBot?

**GradeBot** is an intelligent chatbot that lets you explore a course grade database using natural language. It combines the power of [LangChain](https://www.langchain.com/), [Ollama](https://ollama.com/), and a local **SQLite** database to deliver smart, SQL-driven responses.

Whether you prefer the **command line** or a **modern web UI**, GradeBot has you covered!

---

## Project Structure

```text
.
├── newgrades.csv            # Source CSV data
├── grades.db                # SQLite DB (generated)
├── sql-make.py              # Converts CSV to SQLite
├── chat-sqlbot.py           # Terminal chatbot interface
├── streamlit_sqlbot.py      # Streamlit chatbot interface
├── requirements.txt         # Python dependencies
└── README.md
```

## Setup Instructions

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Install and run Ollama

If you haven't already, install Ollama and pull the Mistral model:

```bash
ollama pull mistral
```

### 3. Create the SQLite database

Run the script to convert the provided CSV into a .db file:

```bash
python sql-make.py
```

This will create a `grades.db` file from `newgrades.csv`.

## Usage

### Terminal Mode

Use the command-line chatbot:

```bash
python chat-sqlbot.py
```

Ask questions like:

```text
What is the average grade in Fall 2020?
```

### Streamlit Web App

Launch the web interface:

```bash
streamlit run streamlit_sqlbot.py
```

Then open the provided localhost URL in your browser to chat with GradeBot in a clean, interactive UI.

## Example Queries

- What was the highest grade in Spring 2022?
- Show me average grades for each department.
- How many students got an A in MATH101?

## License

This project is licensed under the Apache 2.0 License.

## Credits

- Built with LangChain
- Powered by Ollama and the Mistral model
- UI by Streamlit

## Future Improvements

- Upload your own CSV file via the UI
- Add support for charts and visualizations
- Deployable via Docker or Hugging Face Spaces
