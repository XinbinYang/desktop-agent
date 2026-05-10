import { openDB, DBSchema, IDBPDatabase } from 'idb';

interface SessionData {
  sessionId: string;
  messages: any[];
  toolCalls: any[];
  fileEdits?: any[];
  timestamp: number;
}

interface CustomRoleData {
  id: string;
  name: string;
  description: string;
  prompt: string;
  createdAt: number;
}

interface KnowledgePathData {
  path: string;
  recursive: boolean;
  addedAt: number;
}

interface AgentDB extends DBSchema {
  sessions: {
    key: string;
    value: SessionData;
  };
  drafts: {
    key: string;
    value: { sessionId: string; text: string; timestamp: number };
  };
  roles: {
    key: string;
    value: CustomRoleData;
  };
  knowledge: {
    key: string;
    value: KnowledgePathData;
  };
}

const DB_NAME = 'desktop-agent-db';
const DB_VERSION = 3;

let dbPromise: Promise<IDBPDatabase<AgentDB>> | null = null;

function getDB(): Promise<IDBPDatabase<AgentDB>> {
  if (!dbPromise) {
    dbPromise = openDB<AgentDB>(DB_NAME, DB_VERSION, {
      upgrade(db, oldVersion) {
        if (!db.objectStoreNames.contains('sessions')) {
          db.createObjectStore('sessions', { keyPath: 'sessionId' });
        }
        if (!db.objectStoreNames.contains('drafts')) {
          db.createObjectStore('drafts', { keyPath: 'sessionId' });
        }
        if (oldVersion < 2 && !db.objectStoreNames.contains('roles')) {
          db.createObjectStore('roles', { keyPath: 'id' });
        }
        if (oldVersion < 3 && !db.objectStoreNames.contains('knowledge')) {
          db.createObjectStore('knowledge', { keyPath: 'path' });
        }
      },
    });
  }
  return dbPromise;
}

export async function saveSession(sessionId: string, messages: any[], toolCalls: any[], fileEdits: any[] = []): Promise<void> {
  const db = await getDB();
  await db.put('sessions', {
    sessionId,
    messages,
    toolCalls,
    fileEdits,
    timestamp: Date.now(),
  });
  // 清理旧会话，只保留最近 10 个
  const all = await db.getAll('sessions');
  if (all.length > 10) {
    const sorted = all.sort((a, b) => b.timestamp - a.timestamp);
    const toDelete = sorted.slice(10);
    for (const item of toDelete) {
      await db.delete('sessions', item.sessionId);
    }
  }
}

export async function loadSession(sessionId: string): Promise<SessionData | undefined> {
  const db = await getDB();
  return db.get('sessions', sessionId);
}

export async function deleteSessionData(sessionId: string): Promise<void> {
  const db = await getDB();
  await db.delete('sessions', sessionId);
}

export async function saveDraft(sessionId: string, text: string): Promise<void> {
  const db = await getDB();
  await db.put('drafts', { sessionId, text, timestamp: Date.now() });
}

export async function loadDraft(sessionId: string): Promise<string | undefined> {
  const db = await getDB();
  const data = await db.get('drafts', sessionId);
  return data?.text;
}

export async function deleteDraft(sessionId: string): Promise<void> {
  const db = await getDB();
  await db.delete('drafts', sessionId);
}

// ====== 自定义角色管理 ======

export async function saveRole(role: CustomRoleData): Promise<void> {
  const db = await getDB();
  await db.put('roles', { ...role, createdAt: role.createdAt || Date.now() });
}

export async function loadRoles(): Promise<CustomRoleData[]> {
  const db = await getDB();
  return db.getAll('roles');
}

export async function deleteRole(roleId: string): Promise<void> {
  const db = await getDB();
  await db.delete('roles', roleId);
}

// ====== 知识库路径管理 ======

export async function saveKnowledgePath(path: string, recursive: boolean): Promise<void> {
  const db = await getDB();
  await db.put('knowledge', { path, recursive, addedAt: Date.now() });
}

export async function loadKnowledgePaths(): Promise<KnowledgePathData[]> {
  const db = await getDB();
  return db.getAll('knowledge');
}

export async function deleteKnowledgePath(path: string): Promise<void> {
  const db = await getDB();
  await db.delete('knowledge', path);
}
