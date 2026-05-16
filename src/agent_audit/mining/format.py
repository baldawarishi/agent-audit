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
