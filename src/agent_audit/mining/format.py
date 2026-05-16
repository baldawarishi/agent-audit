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
