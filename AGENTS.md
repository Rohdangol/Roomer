# Roomer coding guidelines

Apply these guidelines to all future work in this project:

- Use simple, straightforward Django code and descriptive names.
- Prefer Django's built-in features and normal project structure.
- Avoid unnecessary abstractions, clever shortcuts, deeply nested logic, and extra dependencies.
- Keep separate files when they make responsibilities clearer; fewer files does not automatically mean simpler code.
- Add short comments explaining important logic and why it is needed, especially permissions, verification, file access, and transactions.
- Do not comment every obvious line.
- Preserve necessary security and validation.
- Implement requested tasks directly, keeping scope small and avoiding extra features.
- State the page or feature's purpose in 1–2 sentences before starting work.
- Keep final reports short: what changed, check results, and what to verify manually. Explain changed files, request flow, and important functions briefly when needed; do not give tutorials or repeat code in chat.
- Ask only when essential information is missing.
- Do not commit or push unless requested. After completing a task, wait for the next instruction.

## Checks and testing

- Use manual/browser checks by default for all Roomer tasks.
- Do not write or run automated tests unless absolutely necessary, including for behaviour, authentication, permissions, models, or migrations.
- If an automated check is essential, briefly explain why before running only the smallest relevant check.
- Do not automatically run suites after tasks or milestones, including before merging or pushing.
- Do not repeat passed checks.
- Keep reports short and accurately state what was checked; do not imply automated verification when only manual checks were performed.
- Documentation-only changes do not need tests.
