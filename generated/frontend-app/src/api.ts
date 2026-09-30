export type JobSummary = {
  id: string;
  risk_score: number | null;
  risk_level: "low" | "medium" | "high" | null;
  stage: string;
};

export type JobDetail = {
  id: string;
  stage: string;
  extracted_json: Record<string, unknown> | null;
  risk_score: number | null;
  risk_level: "low" | "medium" | "high" | null;
  ai_summary: string | null;
};

async function json<T>(res: Response): Promise<T> {
  if (!res.ok)
    throw new Error(`Request failed (${res.status}): ${await res.text()}`);
  return res.json();
}

export function uploadDocument(
  file: File,
): Promise<{ job_id: string; stage: string }> {
  const form = new FormData();
  form.append("file", file);
  return fetch("/api/v1/documents/upload", { method: "POST", body: form }).then(
    json,
  );
}

export function getJob(jobId: string): Promise<JobDetail> {
  return fetch(`/api/v1/jobs/${jobId}`).then(json);
}

export function getReviewQueue(): Promise<JobSummary[]> {
  return fetch("/api/v1/jobs/review-queue").then(json);
}
