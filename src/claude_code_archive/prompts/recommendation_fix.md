# Recommendation Fix

You are fixing recommendations that failed quality validation. Your job is to revise ONLY the flagged recommendations while preserving passing ones exactly.

## Original Synthesis TOML

{original_toml}

---

## Validation Issues

The following recommendations need revision:

{validation_issues}

---

## Task

Output a complete, corrected TOML block with ALL recommendations:
1. **PASS recommendations**: Copy exactly as-is, no changes
2. **NEEDS_REVISION recommendations**: Fix based on the issues and suggested fixes provided
3. **REJECT recommendations**: Remove entirely (do not include in output)

### Fix Guidelines

When fixing a recommendation:

- **Vague content**: Add specific, actionable details (commands, checklists, examples)
- **Wrong category**: Change to appropriate category (skill for detailed workflows, claude_md for brief rules, workflow for process guidelines)
- **Missing evidence**: If evidence is weak, note it honestly - don't fabricate
- **Conflated concerns**: Split into separate recommendations if needed
- **Incomplete implementation**: Either complete it or change to a simpler deliverable type

### Output Format

Output ONLY the corrected TOML block. Include all recommendations (passed unchanged + fixed):

```toml
[[recommendations]]
category = "..."
title = "Unchanged Passing Recommendation"
# ... exact copy of passing recommendation ...

[[recommendations]]
category = "..."  # possibly changed
title = "Fixed Recommendation"
description = "..."  # revised
evidence = [...]
priority_score = ...
content = """
... revised, more actionable content ...
"""
```

**IMPORTANT**:
- Output valid TOML only
- In multi-line strings, escape backslashes as `\\`
- Include ALL passing recommendations unchanged
- Do not add new recommendations - only fix existing ones
