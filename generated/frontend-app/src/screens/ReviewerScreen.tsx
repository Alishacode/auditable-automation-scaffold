import { useEffect, useRef, useState } from "react";
import { getJob } from "../api";
import type { JobDetail } from "../api";

const badgeColor: Record<string, string> = {
  low: "#2e7d32",
  medium: "#ed6c02",
  high: "#c62828",
};
const TERMINAL_STAGES = [
  "COMPLETED",
  "REVIEW_REQUIRED",
  "REVIEWED",
  "TERMINAL_FAILURE",
];

export function ReviewerScreen({
  jobId,
  onBack,
}: {
  jobId: string;
  onBack: () => void;
}) {
  const [job, setJob] = useState<JobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<number | null>(null);

  useEffect(() => {
    setJob(null);
    setError(null);

    async function poll() {
      try {
        const data = await getJob(jobId);
        setJob(data);
        if (TERMINAL_STAGES.includes(data.stage) && intervalRef.current) {
          clearInterval(intervalRef.current);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        if (intervalRef.current) clearInterval(intervalRef.current);
      }
    }

    poll();
    intervalRef.current = window.setInterval(poll, 2000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [jobId]);

  return (
    <div
      style={{
        padding: "1.5rem",
        maxWidth: 900,
        margin: "0 auto",
        textAlign: "left",
      }}
    >
      <button onClick={onBack} style={{ marginBottom: "1rem" }}>
        &larr; Back
      </button>

      {error && <p style={{ color: "#c62828" }}>Error: {error}</p>}
      {!job && !error && <p>Loading…</p>}

      {job && (
        <>
          <h2>
            Job {job.id.slice(0, 8)} — {job.stage}
          </h2>
          {!TERMINAL_STAGES.includes(job.stage) && (
            <p>Processing… this updates automatically.</p>
          )}

          {job.risk_level && (
            <div
              style={{
                display: "inline-block",
                padding: "0.4rem 0.9rem",
                borderRadius: 6,
                color: "white",
                background: badgeColor[job.risk_level],
                marginBottom: "1rem",
              }}
            >
              Risk score: {job.risk_score} ({job.risk_level.toUpperCase()})
            </div>
          )}

          {job.extracted_json && (
            <>
              <h3>Extracted fields</h3>
              <ExtractedTable data={job.extracted_json} />
            </>
          )}
        </>
      )}
    </div>
  );
}

function ExtractedTable({ data }: { data: Record<string, unknown> }) {
  const fields = (data.fields ?? data) as Record<string, unknown>;
  const summary = typeof data.summary === "string" ? data.summary : null;

  return (
    <>
      {summary && (
        <p>
          <strong>Summary:</strong> {summary}
        </p>
      )}
      <table style={{ borderCollapse: "collapse", width: "100%" }}>
        <tbody>
          {Object.entries(fields).map(([key, value]) => (
            <tr key={key}>
              <td
                style={{
                  padding: "4px 8px",
                  borderBottom: "1px solid #8884",
                  fontWeight: 600,
                }}
              >
                {key}
              </td>
              <td
                style={{ padding: "4px 8px", borderBottom: "1px solid #8884" }}
              >
                {typeof value === "object"
                  ? JSON.stringify(value)
                  : String(value)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
