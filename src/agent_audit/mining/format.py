"""Plain-text rendering for mined query results (shared by CLI + callers).

Pure string-building, no ``click`` import, so it is unit-testable and the
byte-for-byte regression contract for the ``01_churn`` table now that the
Step-1 shim is gone.
"""

from __future__ import annotations


def format_churn_table(result: dict, top: int) -> str:
    """Render the ``01_churn`` envelope as the Step-1 table + footer.

    Empty ``rows`` (no scanned session had tool calls) collapses to the
    single scanned-line.
    """
    meta = result["meta"]
    rows = result["rows"]
    if not rows:
        return f"Scanned {meta['sessions_scanned']} sessions; none had tool calls."

    header = (
        f"{'session':8}  {'project':30}  {'total':>5}  {'seqs':>5}  "
        f"{'fails':>5}  {'fail%':>6}  {'churn':>8}"
    )
    rule = "-" * len(header)
    lines = [header, rule]
    for r in rows[:top]:
        lines.append(
            f"{r['session_id'][:8]:8}  {r['project'][:30]:30}  "
            f"{r['total']:>5}  {r['sequences']:>5}  {r['fail_count']:>5}  "
            f"{r['fail_ratio'] * 100:>5.1f}%  {r['churn']:>8.2f}"
        )
    lines.append(rule)
    lines.append(
        f"sessions scanned: {meta['sessions_scanned']}  |  "
        f"with tool calls: {meta['sessions_with_calls']}  |  "
        f"median churn: {meta['median_churn']:.2f}"
    )
    return "\n".join(lines)


def format_failures_table(result: dict) -> str:
    """Render the ``02_failure_classification`` envelope as a ranked table.

    All buckets are printed (there are at most ~7), so no top-N knob.
    Empty ``rows`` (no error results scanned) collapses to a single line.
    """
    meta = result["meta"]
    rows = result["rows"]
    if not rows:
        return (
            f"Scanned {meta['sessions_scanned']} sessions; "
            "no error results found."
        )

    header = (
        f"{'bucket':12}  {'count':>6}  {'fail%':>6}  "
        f"{'sessions':>8}  example"
    )
    rule = "-" * len(header)
    lines = [header, rule]
    for r in rows:
        example = r["examples"][0] if r["examples"] else ""
        lines.append(
            f"{r['bucket'][:12]:12}  {r['count']:>6}  "
            f"{r['pct_of_failures']:>5.1f}%  {r['sessions_affected']:>8}  "
            f"{example}"
        )
    lines.append(rule)
    lines.append(
        f"sessions scanned: {meta['sessions_scanned']}  |  "
        f"with errors: {meta['sessions_with_errors']}  |  "
        f"total failures: {meta['total_failures']}"
    )
    return "\n".join(lines)


def format_bash_table(result: dict, top: int) -> str:
    """Render the ``03_bash_subcommands`` envelope as a ranked table.

    Only the top-``top`` rows are printed; the full set is always in the
    JSON envelope. Empty ``rows`` (no bash tool calls) collapses to a
    single scanned-line.
    """
    meta = result["meta"]
    rows = result["rows"]
    if not rows:
        return (
            f"Scanned {meta['sessions_scanned']} sessions; "
            "no bash tool calls found."
        )

    header = (
        f"{'subcommand':20}  {'count':>6}  {'sessions':>8}  "
        f"{'calls/ses':>9}  {'fail%':>6}"
    )
    rule = "-" * len(header)
    lines = [header, rule]
    for r in rows[:top]:
        lines.append(
            f"{r['subcommand'][:20]:20}  {r['count']:>6}  "
            f"{r['sessions']:>8}  {r['calls_per_session']:>9.2f}  "
            f"{r['fail_rate'] * 100:>5.1f}%"
        )
    lines.append(rule)
    lines.append(
        f"bash calls: {meta['bash_calls']}  |  "
        f"distinct subcommands: {meta['distinct_subcommands']}  |  "
        f"sessions scanned: {meta['sessions_scanned']}"
    )
    return "\n".join(lines)


def format_sequences_table(result: dict, top: int) -> str:
    """Render the ``04_tool_sequences`` envelope as a ranked table.

    Only the top-``top`` rows are printed; the full set is always in the
    JSON envelope. ``trigrams:`` in the footer is the grand total of
    trigram *occurrences* (sum of row counts -- the analog of
    ``bash calls:``), distinct from ``distinct:`` (unique trigrams).
    Empty ``rows`` (no session had 3+ tool calls) collapses to a single
    scanned-line.
    """
    meta = result["meta"]
    rows = result["rows"]
    if not rows:
        return (
            f"Scanned {meta['sessions_scanned']} sessions; "
            "no 3+-call sequences found."
        )

    header = f"{'trigram':40}  {'count':>6}  {'sessions':>8}"
    rule = "-" * len(header)
    lines = [header, rule]
    for r in rows[:top]:
        lines.append(
            f"{r['trigram'][:40]:40}  {r['count']:>6}  {r['sessions']:>8}"
        )
    lines.append(rule)
    total = sum(r["count"] for r in rows)
    lines.append(
        f"trigrams: {total}  |  "
        f"distinct: {meta['distinct_trigrams']}  |  "
        f"sessions scanned: {meta['sessions_scanned']}"
    )
    return "\n".join(lines)
