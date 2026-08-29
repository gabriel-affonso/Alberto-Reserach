from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from alberto.db.connection import connect
from alberto.db.migrations import apply_migrations
from alberto.db.repositories import AlbertoRepository
from alberto.enums import FeedbackType
from alberto.logging import configure_logging
from alberto.openclaw.render import required_openclaw_paths
from alberto.research.config import load_project_config
from alberto.research.feedback import store_feedback
from alberto.research.notion import NotionAdapter
from alberto.research.workflow import run_digest_workflow, run_research_workflow


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="alberto")
    sub = parser.add_subparsers(dest="command", required=True)

    db = sub.add_parser("db")
    db_sub = db.add_subparsers(dest="db_command", required=True)
    migrate = db_sub.add_parser("migrate")
    migrate.add_argument("--db")

    config = sub.add_parser("config")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    validate = config_sub.add_parser("validate")
    validate.add_argument("project")

    research = sub.add_parser("research")
    research_sub = research.add_subparsers(dest="research_command", required=True)
    run = research_sub.add_parser("run")
    run.add_argument("--project", required=True)
    run.add_argument("--db")
    run.add_argument("--dry-run", action="store_true")
    digest = research_sub.add_parser("digest")
    digest.add_argument("--project", required=True)
    digest.add_argument("--db")
    digest.add_argument("--output-dir")
    feedback = research_sub.add_parser("feedback")
    feedback.add_argument("--project", required=True)
    feedback.add_argument("--db")
    feedback.add_argument("--type", required=True, choices=[item.value for item in FeedbackType])
    feedback.add_argument("--digest-item-id")
    feedback.add_argument("--paper-id", type=int)
    feedback.add_argument("--note")

    notion = sub.add_parser("notion")
    notion_sub = notion.add_subparsers(dest="notion_command", required=True)
    notion_setup = notion_sub.add_parser("setup")
    notion_setup.add_argument("--parent-page-id", required=True)
    notion_setup.add_argument("--title", default="Alberto Research Library")

    oc = sub.add_parser("openclaw")
    oc_sub = oc.add_subparsers(dest="openclaw_command", required=True)
    oc_sub.add_parser("verify-templates")

    args = parser.parse_args(argv)

    if args.command == "db" and args.db_command == "migrate":
        conn = connect(args.db)
        applied = apply_migrations(conn)
        conn.close()
        print(json.dumps({"applied": applied}))
        return 0
    if args.command == "config" and args.config_command == "validate":
        config_data = load_project_config(args.project)
        print(json.dumps({"ok": True, "project_id": config_data["id"]}))
        return 0
    if args.command == "research" and args.research_command == "run":
        run_id = run_research_workflow(project_path=args.project, db_path=args.db, dry_run=args.dry_run)
        print(json.dumps({"run_id": run_id}))
        return 0
    if args.command == "research" and args.research_command == "digest":
        digest_id, path = run_digest_workflow(project_path=args.project, db_path=args.db, output_dir=args.output_dir)
        print(json.dumps({"digest_id": digest_id, "path": str(path)}))
        return 0
    if args.command == "research" and args.research_command == "feedback":
        config_data = load_project_config(args.project)
        conn = connect(args.db)
        apply_migrations(conn)
        repo = AlbertoRepository(conn)
        repo.upsert_project(config_data, args.project)
        feedback_id = store_feedback(
            repo,
            project_id=config_data["id"],
            feedback_type=args.type,
            digest_item_id=args.digest_item_id,
            paper_id=args.paper_id,
            note=args.note,
        )
        conn.close()
        print(json.dumps({"feedback_id": feedback_id}))
        return 0
    if args.command == "notion" and args.notion_command == "setup":
        database = NotionAdapter().create_article_database(parent_page_id=args.parent_page_id, title=args.title)
        print(json.dumps({"database_id": database.database_id, "data_source_id": database.data_source_id}))
        return 0
    if args.command == "openclaw" and args.openclaw_command == "verify-templates":
        missing = [str(path) for path in required_openclaw_paths() if not path.exists()]
        print(json.dumps({"ok": not missing, "missing": missing}))
        return 1 if missing else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
