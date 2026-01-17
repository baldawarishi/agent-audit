"""CLI for Claude Code archive."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import click

from .config import Config
from .database import Database
from .parser import discover_sessions, get_project_name_from_dir, parse_session, is_tmp_directory
from .toml_renderer import render_session_to_file as render_toml_file
from .toml_renderer import render_session_toml


@click.group()
@click.version_option()
@click.option(
    "--config",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to config file",
)
@click.pass_context
def main(ctx, config: Optional[Path]):
    """Archive Claude Code transcripts for analysis."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = Config.load(config)


@main.command()
@click.option(
    "--projects-dir",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to Claude projects directory (overrides config)",
)
@click.option(
    "--archive-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to archive output directory (overrides config)",
)
@click.option(
    "--project",
    type=str,
    default=None,
    help="Only sync sessions for a specific project",
)
@click.option(
    "--force",
    is_flag=True,
    help="Re-archive sessions even if they already exist",
)
@click.option(
    "--include-tmp-directories",
    is_flag=True,
    help="Include sessions from temp directories (excluded by default)",
)
@click.pass_context
def sync(ctx, projects_dir: Optional[Path], archive_dir: Optional[Path], project: str, force: bool, include_tmp_directories: bool):
    """Sync sessions from Claude projects to the archive (SQLite only)."""
    cfg: Config = ctx.obj["config"]

    if archive_dir:
        cfg.archive_dir = archive_dir
    if projects_dir:
        cfg.projects_dir = projects_dir

    cfg.ensure_dirs()
    db = Database(cfg.db_path)

    with db:
        existing_ids = set(db.get_session_ids()) if not force else set()

        synced = 0
        skipped = 0
        errors = 0

        tmp_skipped = 0
        for jsonl_file, proj_name in discover_sessions(cfg.projects_dir):
            # Get better project name from directory
            proj_name = get_project_name_from_dir(jsonl_file.parent.name)

            # Skip temp directories unless explicitly included
            if not include_tmp_directories and is_tmp_directory(jsonl_file.parent.name):
                tmp_skipped += 1
                continue

            # Filter by project if specified
            if project and proj_name != project:
                continue

            session_id = jsonl_file.stem
            if session_id.startswith("agent-"):
                session_id = session_id[6:]

            if session_id in existing_ids:
                skipped += 1
                continue

            try:
                click.echo(f"Parsing {jsonl_file.name}...", nl=False)
                session = parse_session(jsonl_file, proj_name)

                # Skip sessions with no messages
                if not session.messages:
                    click.echo(" (empty, skipping)")
                    skipped += 1
                    continue

                # Insert into database
                db.insert_session(session)
                click.echo(" done")

                synced += 1
            except Exception as e:
                click.echo(f" ERROR: {e}")
                errors += 1

        click.echo(f"\nDone: {synced} synced, {skipped} skipped, {errors} errors")
        if tmp_skipped > 0:
            click.echo(f"  (Also skipped {tmp_skipped} sessions from temp directories)")

        # Show stats
        stats = db.get_stats()
        click.echo("\nArchive stats:")
        click.echo(f"  Sessions: {stats['total_sessions']}")
        click.echo(f"  Messages: {stats['total_messages']}")
        click.echo(f"  Tool calls: {stats['total_tool_calls']}")
        click.echo(f"  Input tokens: {stats['total_input_tokens']:,}")
        click.echo(f"  Output tokens: {stats['total_output_tokens']:,}")


@main.command()
@click.option(
    "--archive-dir",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to archive directory (overrides config)",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory for TOML files (default: archive/transcripts)",
)
@click.option(
    "--session",
    "session_id",
    type=str,
    default=None,
    help="Render a specific session by ID (prefix match)",
)
@click.option(
    "--project",
    type=str,
    default=None,
    help="Render all sessions for a specific project",
)
@click.option(
    "--stdout",
    is_flag=True,
    help="Output to stdout instead of files",
)
@click.pass_context
def render(ctx, archive_dir: Optional[Path], output_dir: Optional[Path], session_id: str, project: str, stdout: bool):
    """Render sessions as TOML transcripts."""
    cfg: Config = ctx.obj["config"]

    if archive_dir:
        cfg.archive_dir = archive_dir

    if not cfg.db_path.exists():
        click.echo("No archive database found. Run 'sync' first.")
        return

    output = output_dir or cfg.toml_dir

    db = Database(cfg.db_path)
    with db:
        # Get sessions to render
        if session_id:
            # Find session by prefix match
            all_sessions = db.get_all_sessions()
            sessions = [s for s in all_sessions if s["id"].startswith(session_id)]
            if not sessions:
                click.echo(f"No session found matching '{session_id}'")
                return
        elif project:
            sessions = db.get_sessions_by_project(project)
            if not sessions:
                click.echo(f"No sessions found for project '{project}'")
                return
        else:
            sessions = db.get_all_sessions()

        rendered = 0
        for session_dict in sessions:
            # Reconstruct session object from database
            from .models import Message, Session, ToolCall, ToolResult

            messages: list[Message] = []
            for msg in db.get_messages_for_session(session_dict["id"]):
                messages.append(Message(
                    id=msg["id"],
                    session_id=msg["session_id"],
                    type=msg["type"],
                    timestamp=msg["timestamp"],
                    content=msg["content"] or "",
                    parent_uuid=msg["parent_uuid"],
                    model=msg["model"],
                    input_tokens=msg["input_tokens"],
                    output_tokens=msg["output_tokens"],
                    thinking=msg.get("thinking"),
                    stop_reason=msg.get("stop_reason"),
                    is_sidechain=bool(msg.get("is_sidechain", False)),
                    tool_calls=[],
                ))

            tool_calls = []
            for tc in db.get_tool_calls_for_session(session_dict["id"]):
                tool_call = ToolCall(
                    id=tc["id"],
                    message_id=tc["message_id"],
                    session_id=tc["session_id"],
                    tool_name=tc["tool_name"],
                    input_json=tc["input_json"],
                    timestamp=tc["timestamp"],
                )
                tool_calls.append(tool_call)
                # Attach to message
                for message in messages:
                    if message.id == tc["message_id"]:
                        message.tool_calls.append(tool_call)
                        break

            tool_results = []
            for tr in db.get_tool_results_for_session(session_dict["id"]):
                tool_results.append(ToolResult(
                    id=tr["id"],
                    tool_call_id=tr["tool_call_id"],
                    session_id=tr["session_id"],
                    content=tr["content"] or "",
                    is_error=bool(tr["is_error"]),
                    timestamp=tr["timestamp"],
                ))

            session = Session(
                id=session_dict["id"],
                project=session_dict["project"],
                cwd=session_dict["cwd"],
                git_branch=session_dict["git_branch"],
                slug=session_dict.get("slug"),
                summary=session_dict.get("summary"),
                started_at=session_dict["started_at"],
                ended_at=session_dict["ended_at"],
                claude_version=session_dict["claude_version"],
                total_input_tokens=session_dict["total_input_tokens"] or 0,
                total_output_tokens=session_dict["total_output_tokens"] or 0,
                total_cache_read_tokens=session_dict["total_cache_read_tokens"] or 0,
                model=session_dict["model"],
                parent_session_id=session_dict.get("parent_session_id"),
                messages=messages,
                tool_calls=tool_calls,
                tool_results=tool_results,
            )

            if stdout:
                click.echo(render_session_toml(session))
                if len(sessions) > 1:
                    click.echo("\n---\n")
            else:
                output_path = render_toml_file(session, output)
                click.echo(f"Rendered: {output_path}")

            rendered += 1

        if not stdout:
            click.echo(f"\nRendered {rendered} sessions to {output}")


@main.command()
@click.option(
    "--archive-dir",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to archive directory (overrides config)",
)
@click.pass_context
def stats(ctx, archive_dir: Optional[Path]):
    """Show archive statistics."""
    cfg: Config = ctx.obj["config"]

    if archive_dir:
        cfg.archive_dir = archive_dir

    if not cfg.db_path.exists():
        click.echo("No archive database found. Run 'sync' first.")
        return

    db = Database(cfg.db_path)
    with db:
        s = db.get_stats()

        click.echo("Archive Statistics")
        click.echo("=" * 40)
        click.echo(f"Total sessions:    {s['total_sessions']:,}")
        click.echo(f"Total messages:    {s['total_messages']:,}")
        click.echo(f"Total tool calls:  {s['total_tool_calls']:,}")
        click.echo(f"Input tokens:      {s['total_input_tokens']:,}")
        click.echo(f"Output tokens:     {s['total_output_tokens']:,}")
        click.echo()
        click.echo("Projects:")
        for proj in s["projects"]:
            click.echo(f"  - {proj}")


@main.command()
@click.option(
    "--archive-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Set archive directory",
)
@click.option(
    "--projects-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Set Claude projects directory",
)
@click.option(
    "--show",
    is_flag=True,
    help="Show current configuration",
)
@click.pass_context
def config(ctx, archive_dir: Optional[Path], projects_dir: Optional[Path], show: bool):
    """Configure archive settings."""
    cfg: Config = ctx.obj["config"]

    if show or (not archive_dir and not projects_dir):
        click.echo("Current configuration:")
        click.echo(f"  Archive dir:  {cfg.archive_dir}")
        click.echo(f"  Projects dir: {cfg.projects_dir}")
        click.echo(f"  Database:     {cfg.db_path}")
        return

    if archive_dir:
        cfg.archive_dir = archive_dir
    if projects_dir:
        cfg.projects_dir = projects_dir

    cfg.save()
    click.echo("Configuration saved.")
    click.echo(f"  Archive dir:  {cfg.archive_dir}")
    click.echo(f"  Projects dir: {cfg.projects_dir}")


@main.command()
@click.option(
    "--archive-dir",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to archive directory (overrides config)",
)
@click.option(
    "--project",
    type=str,
    default=None,
    help="Filter to specific project",
)
@click.option(
    "--since",
    type=str,
    default=None,
    help="Only analyze sessions since this ISO date (e.g., 2025-01-01)",
)
@click.option(
    "--patterns-only",
    is_flag=True,
    help="Output raw patterns as JSON (skip LLM classification)",
)
@click.option(
    "--min-occurrences",
    type=int,
    default=3,
    help="Minimum pattern occurrences (default: 3)",
)
@click.option(
    "--min-sessions",
    type=int,
    default=2,
    help="Minimum distinct sessions (default: 2)",
)
@click.option(
    "--global-threshold",
    type=float,
    default=0.3,
    help="Fraction of projects for global scope (default: 0.3 = 30%%)",
)
@click.option(
    "--max-patterns",
    type=int,
    default=50,
    help="Maximum patterns to classify with LLM (default: 50)",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=None,
    help="Output file path (default: {archive-dir}/analysis/...)",
)
@click.pass_context
def analyze(
    ctx,
    archive_dir: Optional[Path],
    project: Optional[str],
    since: Optional[str],
    patterns_only: bool,
    min_occurrences: int,
    min_sessions: int,
    global_threshold: float,
    max_patterns: int,
    output: Optional[Path],
):
    """Analyze archived sessions for workflow patterns."""
    import asyncio
    from .analyzer import (
        detect_patterns,
        classify_patterns,
        render_summary_stdout,
        write_recommendations,
    )

    cfg: Config = ctx.obj["config"]

    if archive_dir:
        cfg.archive_dir = archive_dir

    if not cfg.db_path.exists():
        click.echo("No archive database found. Run 'sync' first.")
        return

    db = Database(cfg.db_path)

    with db:
        click.echo("Detecting patterns...")
        result = detect_patterns(
            db=db,
            min_occurrences=min_occurrences,
            min_sessions=min_sessions,
            project_filter=project,
            since=since,
        )

        # Print summary
        summary = result["summary"]
        click.echo(f"\nAnalyzed {summary['total_sessions_analyzed']} sessions across {summary['total_projects']} projects")
        click.echo("\nPatterns found:")
        for pattern_type, count in summary["patterns_found"].items():
            click.echo(f"  {pattern_type}: {count}")

        # Check if there are any patterns to classify
        total_patterns = sum(summary["patterns_found"].values())

        if patterns_only:
            # Determine output path
            if output:
                output_path = output
            else:
                analysis_dir = cfg.archive_dir / "analysis"
                analysis_dir.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
                output_path = analysis_dir / f"patterns-{timestamp}.json"

            # Write JSON output
            with open(output_path, "w") as f:
                json.dump(result, f, indent=2)

            click.echo(f"\nPatterns written to: {output_path}")
        elif total_patterns == 0:
            click.echo("\nNo patterns found to classify.")
        else:
            # Run LLM classification
            click.echo("\nClassifying patterns with Claude...")

            try:
                classifications = asyncio.run(
                    classify_patterns(
                        patterns_result=result,
                        global_threshold=global_threshold,
                        max_patterns=max_patterns,
                    )
                )

                # Print summary to stdout
                click.echo("")
                click.echo(render_summary_stdout(
                    classifications=classifications,
                    total_sessions=summary["total_sessions_analyzed"],
                    total_projects=summary["total_projects"],
                ))

                # Determine output path
                if output:
                    output_path = output
                else:
                    analysis_dir = cfg.archive_dir / "analysis"
                    analysis_dir.mkdir(parents=True, exist_ok=True)
                    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
                    output_path = analysis_dir / f"recommendations-{timestamp}.md"

                # Write markdown output
                write_recommendations(
                    classifications=classifications,
                    output_path=output_path,
                    total_sessions=summary["total_sessions_analyzed"],
                    total_projects=summary["total_projects"],
                    archive_dir=cfg.archive_dir,
                )

                click.echo(f"\nRecommendations written to: {output_path}")

            except ValueError as e:
                if "ANTHROPIC_API_KEY" in str(e):
                    click.echo(f"\nError: {e}")
                    click.echo("Use --patterns-only to skip LLM classification.")
                else:
                    raise


if __name__ == "__main__":
    main()
