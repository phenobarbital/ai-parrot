/**
 * Thin wrapper around `MediaRecorder` for capturing short voice notes in the
 * browser, used by the AgentTalk Voice integration (FEAT-231).
 *
 * The recorded `Blob` is uploaded as `multipart/form-data` to
 * `POST /api/v1/agents/voice/{agent_id}`. The server detects audio by MIME type
 * (anything `audio/*`, plus `video/webm`) or by the file extension as a
 * fallback, so we record `audio/webm` (Opus) when available and tag the file
 * name with a matching extension at upload time.
 */

export interface RecordedVoiceNote {
  blob: Blob;
  /** Effective MIME type of the recording, e.g. "audio/webm". */
  mimeType: string;
  /** Extension matching `mimeType` (no dot), e.g. "webm" — for the file name. */
  extension: string;
  /** Recording length in milliseconds. */
  durationMs: number;
}

/** Candidate containers in preference order (server SUPPORTED_FORMATS mirror). */
const PREFERRED_TYPES = ["audio/webm", "audio/ogg", "audio/mp4"];

const MIME_TO_EXT: Record<string, string> = {
  "audio/webm": "webm",
  "audio/ogg": "ogg",
  "audio/mp4": "m4a",
  "audio/mpeg": "mp3",
  "audio/wav": "wav",
  "audio/flac": "flac",
};

/** True when the browser exposes the APIs we need to record audio. */
export function isVoiceRecordingSupported(): boolean {
  return (
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== "undefined"
  );
}

function pickMimeType(): string {
  if (typeof MediaRecorder === "undefined" || !MediaRecorder.isTypeSupported) {
    return "audio/webm";
  }
  for (const type of PREFERRED_TYPES) {
    if (MediaRecorder.isTypeSupported(type)) return type;
  }
  return ""; // let the browser choose its default
}

function extensionFor(mimeType: string): string {
  // Strip any codec suffix: "audio/webm;codecs=opus" → "audio/webm"
  const base = mimeType.split(";")[0].trim().toLowerCase();
  return MIME_TO_EXT[base] ?? "webm";
}

/**
 * Records a single voice note. Usage:
 *   const rec = new VoiceRecorder();
 *   await rec.start();                  // prompts for mic permission
 *   const note = await rec.stop();      // resolves with the captured Blob
 *
 * An optional `maxDurationMs` auto-stops the recording (the server caps audio at
 * 60s by default; stopping client-side avoids a wasted round-trip + 400).
 */
export class VoiceRecorder {
  private recorder: MediaRecorder | null = null;
  private stream: MediaStream | null = null;
  private chunks: BlobPart[] = [];
  private startedAt = 0;
  private autoStopTimer: ReturnType<typeof setTimeout> | null = null;

  get isRecording(): boolean {
    return this.recorder?.state === "recording";
  }

  async start(maxDurationMs = 60_000): Promise<void> {
    if (!isVoiceRecordingSupported()) {
      throw new Error("Voice recording is not supported in this browser.");
    }
    if (this.isRecording) return;

    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeType = pickMimeType();
    this.recorder = mimeType
      ? new MediaRecorder(this.stream, { mimeType })
      : new MediaRecorder(this.stream);
    this.chunks = [];
    this.recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) this.chunks.push(e.data);
    };
    this.startedAt = performance.now();
    this.recorder.start();

    if (maxDurationMs > 0) {
      this.autoStopTimer = setTimeout(() => {
        if (this.isRecording) this.recorder?.stop();
      }, maxDurationMs);
    }
  }

  /** Stops recording and resolves with the captured note. */
  stop(): Promise<RecordedVoiceNote> {
    return new Promise((resolve, reject) => {
      const recorder = this.recorder;
      if (!recorder) {
        reject(new Error("Recorder was not started."));
        return;
      }
      if (this.autoStopTimer) {
        clearTimeout(this.autoStopTimer);
        this.autoStopTimer = null;
      }
      recorder.onstop = () => {
        const mimeType = recorder.mimeType || "audio/webm";
        const blob = new Blob(this.chunks, { type: mimeType });
        const durationMs = Math.round(performance.now() - this.startedAt);
        this.cleanup();
        resolve({
          blob,
          mimeType,
          extension: extensionFor(mimeType),
          durationMs,
        });
      };
      recorder.onerror = (e) => {
        this.cleanup();
        reject((e as ErrorEvent).error ?? new Error("Recording failed."));
      };
      recorder.stop();
    });
  }

  /** Aborts recording without resolving a note and releases the mic. */
  cancel(): void {
    if (this.autoStopTimer) {
      clearTimeout(this.autoStopTimer);
      this.autoStopTimer = null;
    }
    try {
      if (this.recorder && this.recorder.state !== "inactive") {
        this.recorder.onstop = null;
        this.recorder.stop();
      }
    } catch {
      /* ignore — we're tearing down anyway */
    }
    this.cleanup();
  }

  private cleanup(): void {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.recorder = null;
    this.chunks = [];
  }
}
