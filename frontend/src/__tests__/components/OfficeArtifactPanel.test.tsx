import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ArtifactPanel } from '../../components/ArtifactPanel/ArtifactPanel';
import { ArtifactList } from '../../components/ArtifactPanel/ArtifactList';
import type { ArtifactItem } from '../../types';

const officeArtifact: ArtifactItem = {
  id: 'office-1',
  type: 'office',
  title: 'report.xlsx',
  url: 'http://127.0.0.1:8765/preview/session/report.xlsx',
  path: 'C:\\runtime\\report.xlsx',
  mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  size: 4096,
  timestamp: 1,
  sourceTool: 'excel_create',
};

const officePackageArtifact: ArtifactItem = {
  id: 'package-1',
  type: 'office_package',
  title: 'excel-ppt-skill-self-test',
  timestamp: 1,
  sourceTool: 'office_package_publish',
  size: 8192,
  qaSummary: {
    excel: { qa_status: 'passed', sheet_count: 4 },
    ppt: { qa_status: 'passed', slide_count: 5 },
  },
  files: [
    {
      id: 'excel-file',
      type: 'office',
      kind: 'excel',
      title: 'excel-ppt-skill-self-test.xlsx',
      path: 'C:\\runtime\\excel-ppt-skill-self-test.xlsx',
      workbook: {
        sheets: [
          {
            name: 'Dashboard',
            rows: [
              [
                { address: 'A1', value: 'KPI', style: { bold: true, fill: '#0f172a', font_color: '#ffffff' } },
                { address: 'B1', value: 'Value', style: { bold: true, fill: '#0f172a', font_color: '#ffffff' } },
              ],
              [
                { address: 'A2', value: 'Revenue' },
                { address: 'B2', formula: '=SUM(Data!B2:B3)' },
              ],
            ],
          },
          { name: 'Data', sample: [['Product'], ['Core']] },
        ],
      },
    },
    {
      id: 'ppt-file',
      type: 'office',
      kind: 'ppt',
      title: 'excel-ppt-skill-self-test.pptx',
      path: 'C:\\runtime\\excel-ppt-skill-self-test.pptx',
      presentation: {
        slide_count: 1,
        slide_width: 13.333,
        slide_height: 7.5,
        slides: [{
          id: 'slide-1',
          slide: 1,
          title: 'Revenue growth is broad-based',
          texts: ['Revenue growth is broad-based'],
          notes: 'Speaker note',
          shapes: [
            { index: 1, text: 'Revenue growth is broad-based', bounds: { x: 0.8, y: 0.7, w: 7, h: 0.8 } },
          ],
        }],
      },
    },
  ],
  previews: [
    {
      id: 'preview-1',
      type: 'image',
      kind: 'ppt_contact_sheet',
      title: 'contact sheet',
      url: '/preview/session/contact.png',
    },
  ],
};

describe('Office artifacts', () => {
  beforeEach(() => {
    delete (window as any).electronAPI;
  });

  it('shows office artifacts in the artifact list', () => {
    render(
      <ArtifactList
        artifacts={[officeArtifact]}
        activeId="office-1"
        onSelect={vi.fn()}
        onDelete={vi.fn()}
        onClear={vi.fn()}
      />,
    );

    expect(screen.getByText('report.xlsx')).toBeInTheDocument();
    expect(screen.getByText('Office')).toBeInTheDocument();
  });

  it('opens and reveals office artifact local paths', async () => {
    const openPath = vi.fn(() => Promise.resolve(null));
    const revealPath = vi.fn(() => Promise.resolve(null));
    (window as any).electronAPI = { openPath, revealPath };

    render(
      <ArtifactPanel
        artifacts={[officeArtifact]}
        isRunning={false}
        latestToolCall={null}
        automationSnapshots={[]}
        automationActions={[]}
        automationTraces={[]}
        automationReplayStatus={null}
      />,
    );

    fireEvent.click(screen.getByText('输出'));
    fireEvent.click(screen.getByText('Open'));
    await waitFor(() => expect(openPath).toHaveBeenCalledWith('C:\\runtime\\report.xlsx'));

    fireEvent.click(screen.getByText('Show'));
    await waitFor(() => expect(revealPath).toHaveBeenCalledWith('C:\\runtime\\report.xlsx'));
  });

  it('renders grouped office packages with nested final files', () => {
    render(
      <ArtifactPanel
        artifacts={[officePackageArtifact]}
        isRunning={false}
        latestToolCall={null}
        automationSnapshots={[]}
        automationActions={[]}
        automationTraces={[]}
        automationReplayStatus={null}
      />,
    );

    expect(screen.getAllByText('excel-ppt-skill-self-test').length).toBeGreaterThan(0);
    expect(screen.getByText('excel-ppt-skill-self-test.xlsx')).toBeInTheDocument();
    expect(screen.getByText('excel-ppt-skill-self-test.pptx')).toBeInTheDocument();
    expect(screen.getAllByText('Dashboard').length).toBeGreaterThan(0);
    expect(screen.getAllByText('passed').length).toBeGreaterThan(0);
  });

  it('renders structured PPT fallback when slide images are unavailable', () => {
    render(
      <ArtifactPanel
        artifacts={[officePackageArtifact]}
        isRunning={false}
        latestToolCall={null}
        automationSnapshots={[]}
        automationActions={[]}
        automationTraces={[]}
        automationReplayStatus={null}
      />,
    );

    fireEvent.click(screen.getByText('excel-ppt-skill-self-test.pptx'));
    expect(screen.getAllByText('Revenue growth is broad-based').length).toBeGreaterThan(0);
    expect(screen.queryByText('No rendered slide preview is available.')).not.toBeInTheDocument();
  });
});
