# Multi-Agent Collaboration System Design

## Overview

Add Manager-Worker multi-agent architecture to Desktop Agent. Manager (strong model) can dispatch parallel workers (light/cheap model) for subtask execution.

## Architecture

```
User → Manager Agent (existing AgentSession, strong model, full tools)
         ├── dispatch_worker    → Worker (light model, restricted tools)
         └── dispatch_parallel  → Worker A + Worker B + ... (parallel)
```

## Data Models

### WorkerProfile
- name: "code" | "general"
- tools: list of tool names available to worker
- max_iterations: default 15
- system_prompt_extra: additional system prompt text

### WorkerSession
- worker_id: unique ID
- model_id: can differ from Manager
- profile: WorkerProfile
- messages: independent message history (no inheritance from Manager)
- status: idle | running | completed | failed
- Lightweight ReAct loop: reuse ModelRouter + tool execution
- No persistence, no screenshots
- Stale detection: auto-terminate after 3 iterations with no tool calls or content

## New Tools

### dispatch_worker
- Args: task, profile, context_files (optional)
- Spawns single worker, waits for completion
- Returns structured result

### dispatch_parallel
- Args: tasks: [{task, profile}], model_id (optional)
- Spawns N workers via asyncio.gather
- return_exceptions=True: partial failures don't block others
- Collects and formats all results

## WebSocket Events (new)

- worker_start: {worker_id, task, profile}
- worker_content: {worker_id, text}
- worker_tool_call: {worker_id, name, args, result, duration_ms}
- worker_done: {worker_id, result, iterations, duration_ms, status}

## Frontend

- ToolCallView extended with WorkerCard sub-component
- dispatch_worker shows single expandable worker card
- dispatch_parallel shows multiple parallel worker cards
- No new panels needed

## Error Handling

- Worker model failure → worker_done with error, doesn't block other workers
- Worker timeout (>3min) → asyncio.wait_for, return partial results
- User cancel → Manager.cancel() propagates to all active workers
- Worker max_iterations → returns partial results with status
- Nested dispatch prevented: workers don't have dispatch tools

## Tasks

1. backend/app/worker.py — WorkerSession + WorkerProfile
2. backend/app/tools/worker_tool.py — dispatch_worker + dispatch_parallel
3. backend/app/agent.py — cancel propagation
4. backend/app/main.py — WebSocket worker event bridging
5. Backend tests — test_worker.py + test_worker_tool.py
6. Frontend — types, hook updates, ToolCallView WorkerCard
7. Frontend tests
