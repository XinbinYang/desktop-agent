import type { RunEvent } from '../types';

export type CollaborationActor = 'personal' | 'coding' | 'system' | 'user';
export type CollaborationTimelineKind =
  | 'delegation'
  | 'task'
  | 'clarification'
  | 'answer'
  | 'tool'
  | 'edit'
  | 'verification'
  | 'review'
  | 'artifact'
  | 'completion';
export type CollaborationTimelineStatus = 'running' | 'waiting' | 'done' | 'failed' | 'info';

export interface CollaborationTimelineItem {
  id: string;
  actor: CollaborationActor;
  kind: CollaborationTimelineKind;
  title: string;
  detail?: string;
  status: CollaborationTimelineStatus;
  timestamp: number;
  rawEvent: RunEvent;
}

export function getCollaborationRunId(event: RunEvent): string {
  return String(
    event.data?.collaboration_run_id ||
      event.data?.run_id ||
      event.runId ||
      '',
  );
}

export function hasCollaborationRunId(event: RunEvent): boolean {
  return Boolean(event.data?.collaboration_run_id || event.type.startsWith('collaboration_'));
}

function compact(value: unknown, max = 180): string {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
}

function basename(path: unknown): string {
  const text = String(path || '');
  return text.split(/[\\/]/).filter(Boolean).pop() || text || 'file';
}

function statusFromTask(status: string): CollaborationTimelineStatus {
  if (status === 'completed' || status === 'done' || status === 'pass') return 'done';
  if (status === 'failed' || status === 'cancelled' || status === 'blocked' || status === 'fail') return 'failed';
  if (status === 'waiting_clarification' || status === 'paused') return 'waiting';
  if (status === 'running' || status === 'pending') return 'running';
  return 'info';
}

function actorFromAgentType(agentType: unknown): CollaborationActor {
  const value = String(agentType || '').toLowerCase();
  if (value.includes('personal')) return 'personal';
  if (value.includes('coding')) return 'coding';
  return 'system';
}

function titleForTaskStatus(status: string): string {
  if (status === 'running') return 'Coding started work';
  if (status === 'waiting_clarification') return 'Coding is waiting for input';
  if (status === 'completed') return 'Coding completed the task';
  if (status === 'failed') return 'Coding task failed';
  if (status === 'cancelled') return 'Collaboration was cancelled';
  if (status === 'blocked') return 'Coding task is blocked';
  return status ? `Coding task ${status.replace(/_/g, ' ')}` : 'Coding task updated';
}

export function collaborationEventsForRun(events: RunEvent[], runId: string): RunEvent[] {
  if (!runId) return [];
  return events.filter((event) => getCollaborationRunId(event) === runId);
}

export function buildCollaborationTimeline(events: RunEvent[]): CollaborationTimelineItem[] {
  const clarificationRequests = new Set(
    events
      .filter((event) => event.type === 'collaboration_clarification_request')
      .map((event) => String(event.data?.request_id || '')),
  );

  const items = events.flatMap((event): CollaborationTimelineItem[] => {
    const data = event.data || {};
    const base = {
      id: event.id,
      timestamp: event.timestamp,
      rawEvent: event,
    };

    switch (event.type) {
      case 'collaboration_run_created':
        return [{
          ...base,
          actor: 'personal',
          kind: 'delegation',
          title: 'Personal delegated to Coding',
          detail: compact(data.goal || data.summary || data.project_path),
          status: 'running',
        }];

      case 'collaboration_task_update': {
        const taskStatus = String(data.status || '');
        return [{
          ...base,
          actor: 'coding',
          kind: 'task',
          title: titleForTaskStatus(taskStatus),
          detail: compact(data.packet?.goal || data.result?.summary || data.summary || ''),
          status: statusFromTask(taskStatus),
        }];
      }

      case 'collaboration_plan_auto_approved':
        return [{
          ...base,
          actor: 'personal',
          kind: 'answer',
          title: 'Personal approved Coding plan',
          detail: compact(data.summary || 'Coding can continue execution.'),
          status: 'done',
        }];

      case 'decision_required': {
        if (data.kind === 'clarification' && clarificationRequests.has(String(data.request_id || ''))) {
          return [];
        }
        return [{
          ...base,
          actor: 'coding',
          kind: 'clarification',
          title: 'Coding needs a decision',
          detail: compact(data.question || data.reason || ''),
          status: 'waiting',
        }];
      }

      case 'collaboration_clarification_request':
        return [{
          ...base,
          actor: 'coding',
          kind: 'clarification',
          title: 'Coding asked Personal',
          detail: compact(data.question || data.reason || ''),
          status: 'waiting',
        }];

      case 'collaboration_clarification_answer': {
        const answeredBy = String(data.answered_by || '');
        const auto = answeredBy === 'personal_auto';
        const confidence = typeof data.confidence === 'number' ? ` (${Math.round(data.confidence * 100)}%)` : '';
        return [{
          ...base,
          actor: auto ? 'personal' : 'user',
          kind: 'answer',
          title: auto ? `Personal auto-answered${confidence}` : 'You answered Coding',
          detail: compact(data.answer || data.reason || ''),
          status: 'done',
        }];
      }

      case 'agent_message':
        return [{
          ...base,
          actor: actorFromAgentType(data.agent_type),
          kind: 'task',
          title: `${String(data.agent_type || 'Agent').replace(/_/g, ' ')} update`,
          detail: compact(data.text || data.summary || ''),
          status: statusFromTask(String(data.status || 'info')),
        }];

      case 'tool_call':
        return [{
          ...base,
          actor: 'coding',
          kind: 'tool',
          title: `Coding ran ${data.name || 'tool'}`,
          detail: compact(data.result || ''),
          status: String(data.result || '').startsWith('[ERROR]') ? 'failed' : 'done',
        }];

      case 'worker_tool_call':
        return [{
          ...base,
          actor: 'coding',
          kind: 'tool',
          title: `Worker ran ${data.name || 'tool'}`,
          detail: compact(data.result || ''),
          status: String(data.result || '').startsWith('[ERROR]') ? 'failed' : 'done',
        }];

      case 'file_edit': {
        const file = basename(data.path || data.file);
        const stats = data.stats || {};
        const delta = stats.added || stats.removed ? `+${stats.added || 0}/-${stats.removed || 0}` : '';
        return [{
          ...base,
          actor: 'coding',
          kind: 'edit',
          title: `Coding edited ${file}`,
          detail: compact(delta || data.operation || ''),
          status: 'done',
        }];
      }

      case 'verification_result':
        return [{
          ...base,
          actor: 'coding',
          kind: 'verification',
          title: data.passed ? 'Verification passed' : 'Verification failed',
          detail: compact(data.command || data.summary || ''),
          status: data.passed ? 'done' : 'failed',
        }];

      case 'review_finding': {
        const severity = String(data.severity || 'info').toLowerCase();
        return [{
          ...base,
          actor: 'coding',
          kind: 'review',
          title: `${severity} review finding`,
          detail: compact(data.message || data.file || ''),
          status: ['blocker', 'blocking', 'critical', 'high', 'error'].includes(severity) ? 'failed' : 'info',
        }];
      }

      case 'artifact_ready':
        return [{
          ...base,
          actor: 'coding',
          kind: 'artifact',
          title: 'Artifact ready',
          detail: compact(data.artifact?.title || data.artifact?.path || ''),
          status: 'done',
        }];

      case 'collaboration_run_completed':
      case 'run_completed': {
        const status = String(data.status || 'completed');
        return [{
          ...base,
          actor: 'system',
          kind: 'completion',
          title: status === 'completed' ? 'Collaboration completed' : `Collaboration ${status.replace(/_/g, ' ')}`,
          detail: compact(data.summary || ''),
          status: statusFromTask(status),
        }];
      }

      default:
        return [];
    }
  });

  return items.sort((a, b) => a.timestamp - b.timestamp);
}
