import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';

const mermaidMock = vi.hoisted(() => ({
  initialize: vi.fn(),
  parse: vi.fn().mockResolvedValue(true),
  render: vi.fn().mockResolvedValue({ svg: '<svg data-testid="mermaid-svg"></svg>' }),
}));
vi.mock('mermaid', () => ({ default: mermaidMock }));

import A2UIMermaidDiagram, { resolveMermaidTheme } from './A2UIMermaidDiagram.svelte';

describe('resolveMermaidTheme', () => {
  it('hint wins; dark host -> dark; default otherwise', () => {
    expect(resolveMermaidTheme('forest', true)).toBe('forest');
    expect(resolveMermaidTheme(undefined, true)).toBe('dark');
    expect(resolveMermaidTheme(undefined, false)).toBe('default');
    expect(resolveMermaidTheme('bogus', false)).toBe('default');
  });
});

describe('A2UIMermaidDiagram', () => {
  beforeEach(() => {
    mermaidMock.initialize.mockClear();
    mermaidMock.parse.mockClear();
    mermaidMock.parse.mockResolvedValue(true);
    mermaidMock.render.mockClear();
    mermaidMock.render.mockResolvedValue({ svg: '<svg data-testid="mermaid-svg"></svg>' });
  });

  it('renders the sanitized SVG and the <details> source', async () => {
    const { container } = render(A2UIMermaidDiagram, {
      properties: {
        source: 'graph TD\n  A-->B',
        diagramType: 'flowchart',
        title: 'Test Diagram',
        caption: 'A simple flowchart',
        accessibleDescription: 'A flowchart showing A pointing to B',
      },
    });

    await waitFor(() => {
      expect(screen.getByTestId('mermaid-svg')).toBeTruthy();
    });
    expect(screen.getByText('Test Diagram')).toBeTruthy();
    expect(screen.getByText('A simple flowchart')).toBeTruthy();
    expect(screen.getByText('Mermaid source')).toBeTruthy();
    expect(container.querySelector('details code')?.textContent).toBe('graph TD\n  A-->B');
    const figure = container.querySelector('figure');
    expect(figure?.getAttribute('role')).toBe('img');
    expect(figure?.getAttribute('aria-label')).toBe('A flowchart showing A pointing to B');
  });

  it('initializes mermaid strictly with HTML labels disabled and unique render ids', async () => {
    render(A2UIMermaidDiagram, { properties: { source: 'graph TD\n  A-->B' } });
    render(A2UIMermaidDiagram, { properties: { source: 'graph TD\n  C-->D' } });
    await waitFor(() => expect(mermaidMock.render).toHaveBeenCalledTimes(2));

    const config = mermaidMock.initialize.mock.calls[0][0];
    expect(config.startOnLoad).toBe(false);
    expect(config.securityLevel).toBe('strict');
    expect(config.htmlLabels).toBe(false);
    expect(config.flowchart.htmlLabels).toBe(false);
    expect(config.class.htmlLabels).toBe(false);

    const ids = mermaidMock.render.mock.calls.map((c) => c[0]);
    expect(new Set(ids).size).toBe(2);
    expect(ids.every((id: string) => id.startsWith('a2ui-mermaid-'))).toBe(true);
  });

  it('falls back to the source on parse error without throwing', async () => {
    mermaidMock.parse.mockRejectedValueOnce(new Error('Parse error'));
    const { container } = render(A2UIMermaidDiagram, {
      properties: { source: 'invalid mermaid syntax' },
    });

    await waitFor(() => {
      expect(screen.getByText('Diagram could not be rendered')).toBeTruthy();
    });
    expect(container.querySelector('pre code')?.textContent).toBe('invalid mermaid syntax');
    expect(mermaidMock.render).not.toHaveBeenCalled();
  });

  it('falls back when render rejects', async () => {
    mermaidMock.render.mockRejectedValueOnce(new Error('boom'));
    render(A2UIMermaidDiagram, { properties: { source: 'graph TD\n  A-->B' } });
    await waitFor(() => {
      expect(screen.getByText('Diagram could not be rendered')).toBeTruthy();
    });
  });

  it('preserves SVG labels through sanitization and strips unsafe parts', async () => {
    const svgWithLabels = `
      <svg xmlns="http://www.w3.org/2000/svg">
        <g class="node"><text x="10" y="20"><tspan>Node A</tspan></text></g>
        <g class="node"><text x="50" y="20"><tspan>Node B</tspan></text></g>
        <g class="edgeLabel"><text><tspan>edge label</tspan></text></g>
        <foreignObject><div>HTML content</div></foreignObject>
        <script>alert("xss")</script>
        <circle id="c1" onclick="alert('xss')" r="3" />
      </svg>`;
    mermaidMock.render.mockResolvedValueOnce({ svg: svgWithLabels });
    const { container } = render(A2UIMermaidDiagram, {
      properties: { source: 'graph TD\n  A-->B' },
    });

    await waitFor(() => {
      expect(screen.getByText('Node A')).toBeTruthy();
    });
    expect(screen.getByText('Node B')).toBeTruthy();
    expect(screen.getByText('edge label')).toBeTruthy();
    expect(screen.queryByText('HTML content')).toBeNull();
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('foreignObject')).toBeNull();
    expect(container.querySelector('[onclick]')).toBeNull();
  });
});
