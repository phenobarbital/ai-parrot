
import { marked } from 'marked';
import DOMPurify from 'isomorphic-dompurify';

export function markdownToHtml(markdown: string | null | undefined): string {
    if (!markdown) return '';
    try {
        const rawHtml = marked.parse(markdown) as string;
        return DOMPurify.sanitize(rawHtml);
    } catch (e) {
        console.error('Failed to parse markdown', e);
        return markdown || '';
    }
}
