import { useEffect, useState } from "react";
import { getReviewQueue } from "../api";
import type { JobSummary } from "../api";

export function QueueScreen({
  onSelect,
}: {
  onSelect: (jobId: string) => void;
}) {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getReviewQueue()
      .then(setJobs)
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <div
      style={{
        padding: "1.5rem",
        maxWidth: 700,
        margin: "0 auto",
        textAlign: "left",
      }}
    >
      <h2>Review queue</h2>
      {error && <p style={{ color: "#c62828" }}>Error: {error}</p>}
      {jobs.length === 0 && !error && (
        <p>No documents currently awaiting review.</p>
      )}
      <ul style={{ listStyle: "none", padding: 0 }}>
        {jobs.map((j) => (
          <li key={j.id} style={{ marginBottom: "0.5rem" }}>
            <button onClick={() => onSelect(j.id)}>
              {j.id.slice(0, 8)} — risk {j.risk_score} ({j.risk_level})
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
