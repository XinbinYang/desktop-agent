# Desktop Agent Local Evals

This folder defines small, repository-local coding tasks for measuring agent engineering changes.

The first implementation exposes `POST /api/agent/evals/run`, which loads `manifest.json` and returns the task set and baseline metric slots. The next step is to run each task through the coding run kernel in an isolated worktree, record verification output, and compare metrics across agent changes.

Tracked metrics:

- success rate
- verification pass rate
- average iterations
- tool calls
- duration
- changed file count
- guardrail blocks
