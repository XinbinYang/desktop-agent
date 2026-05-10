import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { KnowledgePanel } from '../../components/KnowledgePanel';

function mockFetchResponse(data: any) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(data),
  } as Response);
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
    fetchMock.mockResolvedValueOnce(mockFetchResponse({ docs: [] }));
    render(<KnowledgePanel />);
    expect(await screen.findByText('知识库为空，添加文件或文件夹开始索引')).toBeInTheDocument();
  });

  it('renders indexed documents', async () => {
    fetchMock.mockResolvedValueOnce(mockFetchResponse({
      docs: [
        { source_path: '/docs/readme.md', chunk_count: 5, last_indexed: 1700000000 },
        { source_path: '/docs/guide.md', chunk_count: 12, last_indexed: 1700000100 },
      ]
    }));
    render(<KnowledgePanel />);
    expect(await screen.findByText('/docs/readme.md')).toBeInTheDocument();
    expect(screen.getByText('5 chunks')).toBeInTheDocument();
    expect(screen.getByText('/docs/guide.md')).toBeInTheDocument();
  });

  it('indexes a file when add button clicked', async () => {
    fetchMock
      .mockResolvedValueOnce(mockFetchResponse({ docs: [] }))
      .mockResolvedValueOnce(mockFetchResponse({ indexed: 1, chunks: 3, skipped: 0 }))
      .mockResolvedValueOnce(mockFetchResponse({ docs: [{ source_path: '/test/file.md', chunk_count: 3, last_indexed: 1700000000 }] }));

    render(<KnowledgePanel />);
    await screen.findByText('知识库为空，添加文件或文件夹开始索引');

    const input = screen.getByPlaceholderText('输入文件或文件夹路径...');
    fireEvent.change(input, { target: { value: '/test/file.md' } });
    fireEvent.click(screen.getAllByRole('button')[1]); // Plus button

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/knowledge/index'),
        expect.objectContaining({ method: 'POST' })
      );
    });
  });

  it('deletes a document when trash clicked', async () => {
    fetchMock
      .mockResolvedValueOnce(mockFetchResponse({
        docs: [{ source_path: '/docs/readme.md', chunk_count: 5, last_indexed: 1700000000 }]
      }))
      .mockResolvedValueOnce(mockFetchResponse({ deleted: 5 }))
      .mockResolvedValueOnce(mockFetchResponse({ docs: [] }));

    render(<KnowledgePanel />);
    await screen.findByText('/docs/readme.md');

    const deleteBtn = screen.getAllByRole('button').find(b => b.querySelector('.lucide-trash2'));
    fireEvent.click(deleteBtn!);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/knowledge/docs'),
        expect.objectContaining({ method: 'DELETE' })
      );
    });
  });

  it('searches knowledge base', async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url.includes('/api/knowledge/docs')) return mockFetchResponse({ docs: [] });
      if (url.includes('/api/knowledge/search')) return mockFetchResponse({
        results: [{ chunk_id: 'c1', source_path: '/docs/readme.md', content: 'Hello world', score: 0.95 }]
      });
      return mockFetchResponse({});
    });

    render(<KnowledgePanel />);
    await screen.findByText('知识库为空，添加文件或文件夹开始索引');

    const searchInput = screen.getByPlaceholderText('搜索知识库...');
    fireEvent.change(searchInput, { target: { value: 'hello' } });
    fireEvent.click(screen.getAllByRole('button')[2]); // search button

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/knowledge/search'),
        expect.objectContaining({ method: 'POST' })
      );
    });
  });

  it('opens folder picker when folder button clicked', async () => {
    fetchMock.mockResolvedValueOnce(mockFetchResponse({ docs: [] }));
    render(<KnowledgePanel />);
    await screen.findByText('知识库为空，添加文件或文件夹开始索引');

    const folderBtn = screen.getAllByRole('button')[0]; // FolderOpen button
    fireEvent.click(folderBtn);

    await waitFor(() => {
      expect((window as any).electronAPI.selectFolder).toHaveBeenCalled();
    });
  });
});
