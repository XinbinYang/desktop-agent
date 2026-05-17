---
name: project-familiarization
description: Use when the user asks to "familiarize yourself with the project", "understand the codebase", "what is this project", or similar requests to explore and summarize a codebase
---

# Project Familiarization

## Overview

When the user asks you to familiarize yourself with a project, your job is to systematically explore the codebase and produce a high-quality, information-dense overview — not a shallow 4-line summary.

**Core principle:** "了解项目"是用户的明确请求，你需要真正读文件、理解架构，然后给出有具体文件名/路径/数字的输出。

## Workflow

### Phase 1: Get the Big Picture

Read these files first:
1. `README.md` — project purpose, setup, key features
2. Top-level config: `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `Makefile` — whichever exists
3. Entry points: `main.py`, `index.ts`, `App.tsx`, `main.go` — whichever exists

### Phase 2: Parallel Code Scanning

Use `dispatch_parallel` to launch 3-4 explorer agents concurrently. Each agent gets a focused task:

**Agent 1 — Backend / Core Logic**: "Scan the backend/core directory structure. List the top-level modules and read the key files. Report: module names, what each does, entry points, key classes/functions."

**Agent 2 — Frontend / UI (if exists)**: "Scan the frontend directory structure. List pages, components, routing. Report: tech stack, page list, key components, state management approach."

**Agent 3 — Config & Infrastructure**: "Read config files, CI configs, Dockerfiles, database schemas. Report: deployment approach, CI pipeline, data storage, environment configuration."

**Agent 4 — Recent Changes**: "Run git log for last 10 commits and git status. Report: recent work, current branch state, active areas of development."

### Phase 3: Synthesize

After sub-agents return, synthesize their findings into ONE structured response:

```
## Project: {name}
{1-2 sentence purpose}

### Tech Stack
- Backend: {framework, database, key libs}
- Frontend: {framework, UI lib, state management}
- Infrastructure: {CI, deployment, etc.}

### Architecture
{Directory tree with 1-line descriptions}

### Key Modules
- module_a/ — what it does
- module_b/ — what it does
...

### Recent Activity
{Branch, last commits, WIP areas}

### Notable Design Decisions
{Any non-obvious architecture choices}
```

## Anti-Patterns

- **DON'T** give a generic 4-line summary without reading any files
- **DON'T** just list directories without explaining what they do
- **DON'T** skip parallel scanning — one agent scanning everything is slow
- **DON'T** guess or make assumptions — read the actual files

## Output Quality

- Include specific file paths, class names, function names
- Include version numbers from config files
- Include real git branch names and commit messages
- Information density > brevity for this task type
