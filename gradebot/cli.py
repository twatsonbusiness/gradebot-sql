"""Terminal interface for GradeBot."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from .core import ConfigurationError, GradeBot, GradeBotError, Settings


def build_parser() -> argparse.ArgumentParser:
    defaults = Settings.from_env()
    parser = argparse.ArgumentParser(description="Ask natural-language questions about grades.")
    parser.add_argument("question", nargs="*", help="ask once instead of opening interactive mode")
    parser.add_argument("--model", default=defaults.model)
    parser.add_argument("--ollama-url", default=defaults.ollama_url)
    parser.add_argument("--database", type=Path, default=defaults.database)
    parser.add_argument("--show-sql", action="store_true")
    return parser


def main() -> None:
    try:
        args = build_parser().parse_args()
        settings = replace(
            Settings.from_env(),
            model=args.model,
            ollama_url=args.ollama_url,
            database=args.database,
        )
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    bot = GradeBot(settings)

    if args.question:
        if not _respond(bot, " ".join(args.question), args.show_sql):
            raise SystemExit(1)
        return

    print(f"GradeBot is ready (model: {settings.model}). Type 'exit' to quit.")
    while True:
        try:
            question = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            return
        if question.lower() in {"exit", "quit"}:
            print("Goodbye!")
            return
        if question:
            _respond(bot, question, args.show_sql)


def _respond(bot: GradeBot, question: str, show_sql: bool) -> bool:
    try:
        result = bot.ask(question)
    except GradeBotError as exc:
        print(f"Error: {exc}")
        return False
    print(f"\nBot: {result.answer}")
    if result.attempts > 1:
        print(f"Note: corrected the generated query after {result.attempts} attempts.")
    if show_sql:
        print(f"SQL: {result.sql}")
    return True
