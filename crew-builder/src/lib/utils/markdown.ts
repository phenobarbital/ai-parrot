const HEADING_REGEX = /^(#{1,6})\s+(.*)$/;
const LIST_ITEM_REGEX = /^\s*[-*+]\s+(.*)$/;
const CODE_BLOCK_REGEX = /^```/;

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function renderInlineMarkdown(value: string): string {
  let result = escapeHtml(value);

  // Links [text](url)
  result = result.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, text, url) => {
    const safeUrl = url.trim();
    const safeText = text.trim().length ? text.trim() : safeUrl;
    return `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${safeText}</a>`;
  });

  // Bold **text** or __text__
  result = result.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  result = result.replace(/__([^_]+)__/g, '<strong>$1</strong>');

  // Italic *text* or _text_
  result = result.replace(/(^|[^*])\*([^*]+)\*(?!\*)/g, '$1<em>$2</em>');
  result = result.replace(/(^|[^_])_([^_]+)_(?!_)/g, '$1<em>$2</em>');

  // Inline code `code`
  result = result.replace(/`([^`]+)`/g, '<code>$1</code>');

  return result;
}

function renderCodeBlock(lines: string[]): string {
  const escaped = lines.map(escapeHtml).join('\n');
  return `<pre><code>${escaped}\n</code></pre>`;
}

export function markdownToHtml(markdown: string): string {
  if (!markdown?.trim()) {
    return '';
  }

  const lines = markdown.replace(/\r\n/g, '\n').split('\n');
  const html: string[] = [];
  let listItems: string[] = [];
  let codeBlock: string[] | null = null;

  const flushList = () => {
    if (!listItems.length) return;
    html.push('<ul>');
    for (const item of listItems) {
      html.push(`<li>${renderInlineMarkdown(item)}</li>`);
    }
    html.push('</ul>');
    listItems = [];
  };

  const flushParagraph = (content: string) => {
    if (!content.trim()) {
      html.push('<br />');
      return;
    }
    html.push(`<p>${renderInlineMarkdown(content)}</p>`);
  };

  for (const line of lines) {
    if (CODE_BLOCK_REGEX.test(line.trim())) {
      if (codeBlock) {
        html.push(renderCodeBlock(codeBlock));
        codeBlock = null;
      } else {
        flushList();
        codeBlock = [];
      }
      continue;
    }

    if (codeBlock) {
      codeBlock.push(line);
      continue;
    }

    const headingMatch = line.match(HEADING_REGEX);
    if (headingMatch) {
      flushList();
      const level = Math.min(headingMatch[1].length, 6);
      const content = renderInlineMarkdown(headingMatch[2]);
      html.push(`<h${level}>${content}</h${level}>`);
      continue;
    }

    const listMatch = line.match(LIST_ITEM_REGEX);
    if (listMatch) {
      listItems.push(listMatch[1]);
      continue;
    }

    flushList();

    if (!line.trim()) {
      html.push('<br />');
      continue;
    }

    flushParagraph(line);
  }

  if (codeBlock) {
    html.push(renderCodeBlock(codeBlock));
  }

  flushList();

  return html.join('\n');
}

export default markdownToHtml;
