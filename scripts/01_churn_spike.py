"""Step-1 churn spike — now a thin shim over ``agent_audit.mining.churn``.

The pure logic moved into the package (Step 2); this script is kept
only as a regression guard so the Step-1 demo command still runs and
prints identically:

    uv run python scripts/01_churn_spike.py [--db PATH] [--gap 120] [--top 20]

The real ``mine`` CLI command (Step 3) supersedes this script.
"""

from __future__ import annotations

from pathlib import Path

import click

from agent_audit.database import Database
from agent_audit.mining.churn import churn_query

DEFAULT_DB = Path(__file__).resolve().parent.parent / "archive" / "sessions.db"


@click.command()
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=DEFAULT_DB,
              show_default=True, help="Path to sessions.db.")
@click.option("--gap", default=120.0, show_default=True,
              help="Max seconds between calls to stay in the same sequence.")
@click.option("--top", default=20, show_default=True,
              help="How many of the churniest sessions to print.")
def main(db_path: Path, gap: float, top: int) -> None:
    if not db_path.exists():
        raise click.ClickException(f"Database not found: {db_path}")

    with Database(db_path) as db:
        result = churn_query(db, gap=gap)

    meta = result["meta"]
    rows = result["rows"]
    if not rows:
        click.echo(
            f"Scanned {meta['sessions_scanned']} sessions; none had tool calls."
        )
        return

    header = (
        f"{'session':8}  {'project':30}  {'total':>5}  {'seqs':>5}  "
        f"{'fails':>5}  {'fail%':>6}  {'churn':>8}"
    )
    click.echo(header)
    click.echo("-" * len(header))
    for r in rows[:top]:
        click.echo(
            f"{r['session_id'][:8]:8}  {r['project'][:30]:30}  "
            f"{r['total']:>5}  {r['sequences']:>5}  {r['fail_count']:>5}  "
            f"{r['fail_ratio'] * 100:>5.1f}%  {r['churn']:>8.2f}"
        )

    click.echo("-" * len(header))
    click.echo(
        f"sessions scanned: {meta['sessions_scanned']}  |  "
        f"with tool calls: {meta['sessions_with_calls']}  |  "
        f"median churn: {meta['median_churn']:.2f}"
    )


if __name__ == "__main__":
    main()
