import { describe, expect, it } from 'vitest';
import {
  deserializePaneTree,
  findLeafById,
  findLeafByPaneId,
  normalizeSizes,
  removeLeaf,
  replaceNode,
  resetSplitSizes,
  updateSplitSizes,
  type LeafNode,
  type PaneNode,
} from '../../../components/session/PaneTypes';

function leaf(id: string, paneId = `pane_${id}`, sessionId = `session_${id}`): LeafNode {
  return {
    type: 'leaf',
    id,
    pane: { id: paneId, sessionId, model: 'gpt-test', agentType: 'personal', role: 'desktop-agent' },
  };
}

function sum(values: number[]): number {
  return values.reduce((total, value) => total + value, 0);
}

describe('PaneTypes', () => {
  it('replaces split nodes as well as leaf nodes', () => {
    const root: PaneNode = {
      type: 'split',
      id: 'root',
      direction: 'horizontal',
      children: [
        leaf('a'),
        { type: 'split', id: 'nested', direction: 'vertical', children: [leaf('b'), leaf('c')], sizes: [30, 70] },
      ],
      sizes: [40, 60],
    };

    const result = replaceNode(root, 'nested', leaf('x'));

    expect(result.type).toBe('split');
    if (result.type === 'split') {
      expect(result.children[1]).toMatchObject({ type: 'leaf', id: 'x' });
    }
  });

  it('removes a leaf inside a nested split and collapses the parent split', () => {
    const root: PaneNode = {
      type: 'split',
      id: 'root',
      direction: 'horizontal',
      children: [
        leaf('a'),
        { type: 'split', id: 'nested', direction: 'vertical', children: [leaf('b'), leaf('c')], sizes: [40, 60] },
        leaf('d'),
      ],
      sizes: [20, 50, 30],
    };

    const result = removeLeaf(root, 'b');

    expect(result?.removedPane?.id).toBe('pane_b');
    expect(result?.focusId).toBe('c');
    expect(findLeafById(result!.root, 'b')).toBeNull();
    expect(findLeafById(result!.root, 'c')).not.toBeNull();
    expect(result!.root).toMatchObject({
      type: 'split',
      children: [
        { type: 'leaf', id: 'a' },
        { type: 'leaf', id: 'c' },
        { type: 'leaf', id: 'd' },
      ],
    });
  });

  it('removes a direct child and redistributes its size', () => {
    const root: PaneNode = {
      type: 'split',
      id: 'root',
      direction: 'horizontal',
      children: [leaf('a'), leaf('b'), leaf('c')],
      sizes: [20, 30, 50],
    };

    const result = removeLeaf(root, 'b');

    expect(result?.removedPane?.id).toBe('pane_b');
    expect(result?.focusId).toBe('c');
    expect(result?.root.type).toBe('split');
    if (result?.root.type === 'split') {
      expect(result.root.children.map((child) => child.id)).toEqual(['a', 'c']);
      expect(sum(result.root.sizes)).toBeCloseTo(100);
      expect(result.root.sizes[0]).toBeCloseTo(28.571, 2);
      expect(result.root.sizes[1]).toBeCloseTo(71.429, 2);
    }
  });

  it('returns null when removing an unknown leaf', () => {
    const root: PaneNode = { type: 'split', id: 'root', direction: 'horizontal', children: [leaf('a'), leaf('b')], sizes: [50, 50] };

    expect(removeLeaf(root, 'missing')).toBeNull();
  });

  it('finds leaves by pane id', () => {
    const root: PaneNode = { type: 'split', id: 'root', direction: 'horizontal', children: [leaf('a', 'pane-a'), leaf('b', 'pane-b')], sizes: [50, 50] };

    expect(findLeafByPaneId(root, 'pane-b')?.id).toBe('b');
  });

  it('normalizes and resets split sizes', () => {
    expect(normalizeSizes(2, [1, 3])).toEqual([25, 75]);

    const root: PaneNode = { type: 'split', id: 'root', direction: 'horizontal', children: [leaf('a'), leaf('b')], sizes: [10, 90] };
    const updated = updateSplitSizes(root, 'root', [20, 80]);
    const reset = resetSplitSizes(updated);

    expect(updated.type === 'split' ? updated.sizes : []).toEqual([20, 80]);
    expect(reset.type === 'split' ? reset.sizes : []).toEqual([50, 50]);
  });

  it('migrates v1 persisted trees and fixes invalid focused leaf ids', () => {
    const raw = JSON.stringify({
      version: 1,
      focusedLeafId: 'missing',
      paneRoot: {
        type: 'split',
        id: 'root',
        direction: 'horizontal',
        children: [leaf('a'), leaf('b')],
        sizes: [10],
      },
    });

    const result = deserializePaneTree(raw);

    expect(result?.version).toBe(2);
    expect(result?.focusedLeafId).toBe('a');
    expect(result?.paneRoot.type).toBe('split');
    if (result?.paneRoot.type === 'split') {
      expect(result.paneRoot.sizes).toEqual([50, 50]);
    }
  });
});
