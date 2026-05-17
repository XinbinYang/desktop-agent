import type { AgentType } from '../../types';
import { normalizeAgentType, roleForAgent } from '../../lib/agentProfiles';

export interface SessionPane {
  id: string;
  sessionId: string;
  model: string;
  agentType: AgentType;
  role?: string;
  teamId?: string;
}

export interface LeafNode {
  type: 'leaf';
  id: string;
  pane: SessionPane;
}

export interface SplitNode {
  type: 'split';
  id: string;
  direction: 'horizontal' | 'vertical';
  children: PaneNode[];
  sizes: number[];
}

export type PaneNode = LeafNode | SplitNode;

export interface LeafEntry {
  leafId: string;
  node: LeafNode;
  pane: SessionPane;
}

let _nodeCounter = 0;
export function nextNodeId(): string {
  return `node_${Date.now()}_${++_nodeCounter}`;
}

export function findLeafById(root: PaneNode, leafId: string): LeafNode | null {
  if (root.type === 'leaf') return root.id === leafId ? root : null;
  for (const child of root.children) {
    const found = findLeafById(child, leafId);
    if (found) return found;
  }
  return null;
}

export function findLeafByPaneId(root: PaneNode, paneId: string): LeafNode | null {
  if (root.type === 'leaf') return root.pane.id === paneId ? root : null;
  for (const child of root.children) {
    const found = findLeafByPaneId(child, paneId);
    if (found) return found;
  }
  return null;
}

/** Replace any node by id within the tree. Returns a new tree. */
export function replaceNode(root: PaneNode, targetId: string, replacement: PaneNode): PaneNode {
  if (root.id === targetId) return replacement;
  if (root.type === 'leaf') return root;
  return {
    ...root,
    children: root.children.map((child) => replaceNode(child, targetId, replacement)),
  };
}

export function collectLeaves(root: PaneNode): SessionPane[] {
  if (root.type === 'leaf') return [root.pane];
  return root.children.flatMap(collectLeaves);
}

export function collectLeafNodes(root: PaneNode): LeafEntry[] {
  if (root.type === 'leaf') return [{ leafId: root.id, node: root, pane: root.pane }];
  return root.children.flatMap(collectLeafNodes);
}

/** Find the parent of a node. Returns [parent, index] or null. */
export function findParent(root: PaneNode, childId: string): [SplitNode, number] | null {
  if (root.type === 'leaf') return null;
  for (let index = 0; index < root.children.length; index += 1) {
    if (root.children[index].id === childId) return [root, index];
    const found = findParent(root.children[index], childId);
    if (found) return found;
  }
  return null;
}

export function normalizeSizes(count: number, sizes?: number[]): number[] {
  if (count <= 0) return [];
  if (!Array.isArray(sizes) || sizes.length !== count) {
    return Array.from({ length: count }, () => 100 / count);
  }

  const numeric = sizes.map((size) => {
    const value = Number(size);
    return Number.isFinite(value) && value > 0 ? value : 0;
  });
  const total = numeric.reduce((sum, size) => sum + size, 0);
  if (total <= 0) {
    return Array.from({ length: count }, () => 100 / count);
  }

  return numeric.map((size) => (size / total) * 100);
}

function redistributeSizes(sizes: number[], removedIndexes: Set<number>): number[] {
  const keptSizes = sizes.filter((_, index) => !removedIndexes.has(index));
  if (keptSizes.length === 0) return [];

  const removedSize = sizes.reduce((sum, size, index) => (
    removedIndexes.has(index) ? sum + size : sum
  ), 0);
  const remainingTotal = keptSizes.reduce((sum, size) => sum + size, 0);
  if (remainingTotal <= 0) {
    return normalizeSizes(keptSizes.length);
  }

  return normalizeSizes(
    keptSizes.length,
    keptSizes.map((size) => size + (removedSize * size) / remainingTotal),
  );
}

export function removeLeaf(root: PaneNode, leafId: string): { root: PaneNode; focusId: string | null; removedPane: SessionPane | null } | null {
  if (root.type === 'leaf') {
    if (root.id === leafId) return { root, focusId: null, removedPane: root.pane };
    return null;
  }

  let removedPane: SessionPane | null = null;
  let focusId: string | null = null;

  function removeFrom(node: PaneNode): { node: PaneNode | null; removed: boolean } {
    if (node.type === 'leaf') {
      if (node.id !== leafId) return { node, removed: false };
      removedPane = node.pane;
      return { node: null, removed: true };
    }

    const baseSizes = normalizeSizes(node.children.length, node.sizes);
    const nextChildren: PaneNode[] = [];
    const nextSizes: number[] = [];
    const removedIndexes = new Set<number>();
    let removed = false;

    node.children.forEach((child, index) => {
      const result = removeFrom(child);
      if (result.removed) removed = true;
      if (result.node) {
        nextChildren.push(result.node);
        nextSizes.push(baseSizes[index]);
      } else {
        removedIndexes.add(index);
      }
    });

    if (!removed) return { node, removed: false };

    if (!focusId && removedIndexes.size > 0 && nextChildren.length > 0) {
      const firstRemoved = Math.min(...Array.from(removedIndexes));
      const focusChild = nextChildren[Math.min(firstRemoved, nextChildren.length - 1)];
      focusId = findFirstLeafId(focusChild);
    }

    if (nextChildren.length === 0) return { node: null, removed: true };
    if (nextChildren.length === 1) return { node: nextChildren[0], removed: true };

    const sizes = removedIndexes.size > 0
      ? redistributeSizes(baseSizes, removedIndexes)
      : normalizeSizes(nextChildren.length, nextSizes);

    return {
      node: {
        ...node,
        children: nextChildren,
        sizes,
      },
      removed: true,
    };
  }

  const result = removeFrom(root);
  if (!result.removed || !removedPane || !result.node) return null;

  return {
    root: result.node,
    focusId: focusId ?? findFirstLeafId(result.node),
    removedPane,
  };
}

export function findFirstLeafId(node: PaneNode): string | null {
  if (node.type === 'leaf') return node.id;
  for (const child of node.children) {
    const id = findFirstLeafId(child);
    if (id) return id;
  }
  return null;
}

export function updateSplitSizes(root: PaneNode, splitId: string, sizes: number[]): PaneNode {
  if (root.type === 'leaf') return root;
  if (root.id === splitId) {
    return {
      ...root,
      sizes: normalizeSizes(root.children.length, sizes),
    };
  }
  return {
    ...root,
    children: root.children.map((child) => updateSplitSizes(child, splitId, sizes)),
  };
}

export function resetSplitSizes(root: PaneNode): PaneNode {
  if (root.type === 'leaf') return root;
  const children = root.children.map(resetSplitSizes);
  return {
    ...root,
    children,
    sizes: normalizeSizes(children.length),
  };
}

export function normalizePaneTree(node: unknown): PaneNode | null {
  if (!node || typeof node !== 'object') return null;
  const data = node as Partial<PaneNode>;

  if (data.type === 'leaf') {
    const leaf = data as Partial<LeafNode>;
    const pane = leaf.pane as Partial<SessionPane> | undefined;
    if (!pane || typeof pane !== 'object') return null;

    const agentType = normalizeAgentType((pane as Partial<SessionPane>).agentType, pane.role);
    return {
      type: 'leaf',
      id: typeof leaf.id === 'string' && leaf.id ? leaf.id : nextNodeId(),
      pane: {
        id: typeof pane.id === 'string' && pane.id ? pane.id : `pane_${Date.now()}`,
        sessionId: typeof pane.sessionId === 'string' && pane.sessionId ? pane.sessionId : `session_${Date.now()}`,
        model: typeof pane.model === 'string' ? pane.model : '',
        agentType,
        role: typeof pane.role === 'string' ? pane.role : roleForAgent(agentType),
        ...(typeof pane.teamId === 'string' && pane.teamId ? { teamId: pane.teamId } : {}),
      },
    };
  }

  if (data.type === 'split') {
    const split = data as Partial<SplitNode>;
    const rawChildren = Array.isArray(split.children) ? split.children : [];
    const children = rawChildren
      .map((child) => normalizePaneTree(child))
      .filter((child): child is PaneNode => Boolean(child));

    if (children.length === 0) return null;
    if (children.length === 1) return children[0];

    return {
      type: 'split',
      id: typeof split.id === 'string' && split.id ? split.id : nextNodeId(),
      direction: split.direction === 'vertical' ? 'vertical' : 'horizontal',
      children,
      sizes: normalizeSizes(children.length, split.sizes),
    };
  }

  return null;
}

const PANE_TREE_VERSION = 2;

export interface PersistedPaneTree {
  version: number;
  paneRoot: PaneNode;
  focusedLeafId: string;
}

export function serializePaneTree(paneRoot: PaneNode, focusedLeafId: string): string {
  const data: PersistedPaneTree = {
    version: PANE_TREE_VERSION,
    paneRoot: normalizePaneTree(paneRoot) ?? paneRoot,
    focusedLeafId,
  };
  return JSON.stringify(data);
}

export function deserializePaneTree(raw: string): PersistedPaneTree | null {
  try {
    const data = JSON.parse(raw);
    if (!data || (data.version !== 1 && data.version !== PANE_TREE_VERSION) || !data.paneRoot) return null;

    const paneRoot = normalizePaneTree(data.paneRoot);
    if (!paneRoot) return null;

    const focusedLeafId = typeof data.focusedLeafId === 'string' && findLeafById(paneRoot, data.focusedLeafId)
      ? data.focusedLeafId
      : findFirstLeafId(paneRoot);
    if (!focusedLeafId) return null;

    _nodeCounter = Math.max(_nodeCounter, countNodes(paneRoot));
    return { version: PANE_TREE_VERSION, paneRoot, focusedLeafId };
  } catch {
    return null;
  }
}

function countNodes(node: PaneNode): number {
  if (node.type === 'leaf') return 1;
  return 1 + node.children.reduce((sum, child) => sum + countNodes(child), 0);
}
