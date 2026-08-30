/**
 * Speech Report API — sends canvas data to an agent's speech_report endpoint
 * and returns paths to the generated script and podcast audio.
 */
import apiClient from "./http";

export interface SpeechReportResult {
  script_path: string;
  podcast_path: string;
}

interface SpeechReportRawResponse {
  message: string;
  response: string;
}

/**
 * Extract a file path from a Python PosixPath string representation.
 * e.g. "PosixPath('/home/.../static/agent/file.wav')" → "/static/agent/file.wav"
 * Also handles plain path strings that already contain "/static/".
 */
function resolveStaticUrl(raw: string): string {
  // Extract path from PosixPath('...') wrapper if present
  const posixMatch = raw.match(/PosixPath\(['"](.+?)['"]\)/);
  const fullPath = posixMatch ? posixMatch[1] : raw;

  // Extract everything from /static/ onwards
  const staticIdx = fullPath.indexOf("/static/");
  if (staticIdx === -1) return fullPath;
  const relativePath = fullPath.substring(staticIdx);

  return relativePath;
}

export async function generateSpeechReport(
  agentId: string,
  data: string,
): Promise<SpeechReportResult> {
  const { data: raw } = await apiClient.post<SpeechReportRawResponse>(
    `/api/v1/agents/chat/${agentId}/speech_report`,
    { report: data },
  );

  // The backend returns { message, response } where response is a Python dict string.
  // Parse the PosixPath values from the response string.
  const responseStr = raw.response ?? "";

  const scriptMatch = responseStr.match(
    /'script_path':\s*(PosixPath\(['"][^'"]+['"]\)|'[^']+'|"[^"]+")/,
  );
  const podcastMatch = responseStr.match(
    /'podcast_path':\s*(PosixPath\(['"][^'"]+['"]\)|'[^']+'|"[^"]+")/,
  );

  const scriptPath = scriptMatch ? resolveStaticUrl(scriptMatch[1]) : "";
  const podcastPath = podcastMatch ? resolveStaticUrl(podcastMatch[1]) : "";

  return { script_path: scriptPath, podcast_path: podcastPath };
}
