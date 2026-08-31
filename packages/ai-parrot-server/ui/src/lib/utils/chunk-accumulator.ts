/**
 * ChunkAccumulator — sentence-boundary buffering for streamed text.
 *
 * Accumulates raw text chunks from HTTP chunked responses and splits them at
 * sentence boundaries so the UI can render complete sentences smoothly.
 */
export class ChunkAccumulator {
  private buffer: string = "";

  /**
   * Sentence boundary markers. `. ` requires trailing space to avoid splitting
   * URLs (example.com), decimals (3.14), and abbreviations (Dr. Smith).
   */
  private static readonly BOUNDARIES = [". ", "? ", "! ", "\n\n"];

  /**
   * Append a raw text chunk to the internal buffer.
   * Empty chunks are silently ignored.
   */
  append(chunk: string): void {
    if (!chunk) return;
    this.buffer += chunk;
  }

  /**
   * Return all text up to and including the last sentence boundary.
   * If no boundary exists yet, returns an empty string.
   */
  getRenderable(): string {
    const lastIdx = this.findLastBoundaryEnd();
    if (lastIdx === -1) return "";
    return this.buffer.slice(0, lastIdx);
  }

  /**
   * Return the text fragment after the last sentence boundary (incomplete sentence).
   * If no boundary exists, returns the full buffer.
   */
  getPending(): string {
    const lastIdx = this.findLastBoundaryEnd();
    if (lastIdx === -1) return this.buffer;
    return this.buffer.slice(lastIdx);
  }

  /**
   * Return the complete buffer (renderable + pending).
   */
  getFullText(): string {
    return this.buffer;
  }

  /**
   * Clear all internal state for reuse.
   */
  reset(): void {
    this.buffer = "";
  }

  /**
   * Find the index in the buffer just after the last sentence boundary.
   * Returns -1 if no boundary is found.
   */
  private findLastBoundaryEnd(): number {
    let lastEnd = -1;
    for (const boundary of ChunkAccumulator.BOUNDARIES) {
      let searchFrom = 0;
      while (true) {
        const idx = this.buffer.indexOf(boundary, searchFrom);
        if (idx === -1) break;
        const end = idx + boundary.length;
        if (end > lastEnd) lastEnd = end;
        searchFrom = idx + 1;
      }
    }
    return lastEnd;
  }
}
