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

- Styling-only changes: use visual or manual checks; do not run an automated suite.
- Behaviour changes: run focused tests relevant to the changed behaviour.
- Authentication, permissions, models, and migrations: run appropriate automated checks, including relevant tests and Django's system check.
- Run the full relevant suite at completed milestones before merging or pushing.
- Do not repeat passed checks unless subsequent changes affect them, or a milestone requires the full relevant suite.
- Documentation-only changes do not need tests.
