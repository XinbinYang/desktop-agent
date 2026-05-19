import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { KnowledgePanel } from '../../components/KnowledgePanel';

vi.mock('../../lib/db', () => ({
  loadKnowledgePaths: vi.fn(() => Promise.resolve([])),
  saveKnowledgePath: vi.fn(() => Promise.resolve()),
  deleteKnowledgePath: vi.fn(() => Promise.resolve()),
}));

function mockFetchResponse(data: any) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(data),
  } as Response);
}

function urlString(url: RequestInfo | URL): string {
  return typeof url === 'string' ? url : url.toString();
}

describe('KnowledgePanel', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
    global.confirm = vi.fn(() => true);
    (window as any).electronAPI = { selectFolder: vi.fn(() => Promise.resolve('/test/path')) };
  });

  it('renders empty state', async () => {
    fetchMock.mockImplementation((url) => {
      const u = urlString(url);
      if (u.includes('/api/knowledge/stats')) {
        return mockFetchResponse({ total_chunks: 0, source_count: 0, db_size_mb: 0 });
      }
      if (u.includes('/api/knowledge/docs') && !u.includes('?')) {
        return mockFetchResponse({ docs: [] });
      }
      return mockFetchResponse({});
    });
    render(<KnowledgePanel />);
    expect(await screen.findByText('The knowledge base is empty.')).toBeInTheDocument();
  });

  it('renders indexed documents', async () => {
    const docs = [
      { source_path: '/docs/readme.md', chunk_count: 5, last_indexed: 1700000000 },
      { source_path: '/docs/guide.md', chunk_count: 12, last_indexed: 1700000100 },
    ];
    fetchMock.mockImplementation((url) => {
      const u = urlString(url);
      if (u.includes('/api/knowledge/stats')) {
        return mockFetchResponse({ total_chunks: 17, source_count: 2, db_size_mb: 0.1 });
      }
      if (u.includes('/api/knowledge/docs') && !u.includes('?')) {
        return mockFetchResponse({ docs });
      }
      return mockFetchResponse({});
    });
    render(<KnowledgePanel />);
    expect(await screen.findByText('/docs/readme.md')).toBeInTheDocument();
    expect(screen.getByText(/5 chunks/)).toBeInTheDocument();
    expect(screen.getByText('/docs/guide.md')).toBeInTheDocument();
  });

  it('indexes a file when add button clicked', async () => {
    let docs: { source_path: string; chunk_count: number; last_indexed: number }[] = [];
    fetchMock.mockImplementation((url, init) => {
      const u = urlString(url);
      if (u.includes('/api/knowledge/stats')) {
        const total = docs.reduce((a, d) => a + d.chunk_count, 0);
        return mockFetchResponse({ total_chunks: total, source_count: docs.length, db_size_mb: 0 });
      }
      if (u.includes('/api/knowledge/index') && init && init.method === 'POST') {
        docs = [{ source_path: '/test/file.md', chunk_count: 3, last_indexed: 1700000000 }];
        return mockFetchResponse({ indexed: 1, chunks: 3, skipped: 0 });
      }
      if (u.includes('/api/knowledge/docs') && !u.includes('?')) {
        return mockFetchResponse({ docs });
      }
      return mockFetchResponse({});
    });
    render(<KnowledgePanel />);
    await screen.findByText('The knowledge base is empty.');

    const input = screen.getByPlaceholderText('File or folder path');
    fireEvent.change(input, { target: { value: '/test/file.md' } });
    fireEvent.click(screen.getByLabelText('Add to knowledge base'));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/knowledge/index'),
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });

  it('deletes a document when trash clicked', async () => {
    let docs = [{ source_path: '/docs/readme.md', chunk_count: 5, last_indexed: 1700000000 }];
    fetchMock.mockImplementation((url, init) => {
      const u = urlString(url);
      if (u.includes('/api/knowledge/stats')) {
        const total = docs.reduce((a, d) => a + d.chunk_count, 0);
        return mockFetchResponse({ total_chunks: total, source_count: docs.length, db_size_mb: 0 });
      }
      if (u.includes('/api/knowledge/docs?path=') && init?.method === 'DELETE') {
        docs = [];
        return mockFetchResponse({ deleted: 5 });
      }
      if (u.includes('/api/knowledge/docs')) {
        return mockFetchResponse({ docs });
      }
      return mockFetchResponse({});
    });

    render(<KnowledgePanel />);
    await screen.findByText('/docs/readme.md');

    fireEvent.click(screen.getByLabelText('Delete /docs/readme.md'));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringMatching(/\/api\/knowledge\/docs\?path=/),
        expect.objectContaining({ method: 'DELETE' }),
      );
    });
  });

  it('searches knowledge base', async () => {
    fetchMock.mockImplementation((url) => {
      const u = urlString(url);
      if (u.includes('/api/knowledge/stats')) {
        return mockFetchResponse({ total_chunks: 0, source_count: 0, db_size_mb: 0 });
      }
      if (u.includes('/api/knowledge/docs') && !u.includes('?')) {
        return mockFetchResponse({ docs: [] });
      }
      if (u.includes('/api/knowledge/search')) {
        return mockFetchResponse({
          results: [{ chunk_id: 'c1', source_path: '/docs/readme.md', content: 'Hello world', score: 0.95 }],
        });
      }
      return mockFetchResponse({});
    });

    render(<KnowledgePanel />);
    await screen.findByText('The knowledge base is empty.');

    const searchInput = screen.getByPlaceholderText('Search indexed content');
    fireEvent.change(searchInput, { target: { value: 'hello' } });
    fireEvent.click(screen.getByLabelText('Search knowledge base'));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/knowledge/search'),
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });

  it('opens folder picker when folder button clicked', async () => {
    fetchMock.mockImplementation((url) => {
      const u = urlString(url);
      if (u.includes('/api/knowledge/stats')) {
        return mockFetchResponse({ total_chunks: 0, source_count: 0, db_size_mb: 0 });
      }
      if (u.includes('/api/knowledge/docs') && !u.includes('?')) {
        return mockFetchResponse({ docs: [] });
      }
      return mockFetchResponse({});
    });
    render(<KnowledgePanel />);
    await screen.findByText('The knowledge base is empty.');

    fireEvent.click(screen.getByLabelText('Choose folder'));

    await waitFor(() => {
      expect((window as any).electronAPI.selectFolder).toHaveBeenCalled();
    });
  });
});
