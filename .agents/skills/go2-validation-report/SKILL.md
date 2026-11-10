---
name: go2-validation-report
description: Keep the single Go2 navigation validation HTML and Draft PR synchronized with GitHub code changes, commands, evidence and unresolved risks. Use after implementing or testing.
---

# Validation record and PR update

Canonical file: `docs/go2_navigation_validation.html`. Do not create duplicates.

## Required update
1. Read the latest PR #1 and all new commits; preserve prior changes and test history.
2. Update the revision date and revision identifier (R1, R2, ...).
3. List each implemented change with original → current value and specific technical reason.
4. Add each relevant commit link. Never label an unrun ROS/Go2 test as PASS.
5. Update T00–T10 test steps and PASS/FAIL/BLOCKED/NOT TESTED evidence.
6. Add failure observations, root-cause hypotheses and independent follow-up changes.
7. Keep readable semantic HTML, CSS print support, accessible links and a compact table. Use short, direct technical sentences inspired by ASD-STE100; never claim formal ASD-STE100 certification.
8. Keep every existing prior record traceable. Make a separate docs commit for updates.
9. Update the **existing** Draft PR #1 body with a link, changed scope and unresolved risks. Never merge without explicit user approval.

## Offline checks
- Verify valid HTML structure, navigation anchor targets and all required sections.
- Verify commands are non-destructive and reflect the current code.
- Compare the document's current values with the current YAML and launch source.
- Report what was inspected (source/static/runtime/robot) distinctly.

No GitHub Actions. Do not rewrite results to make them look successful.
