import { useEffect, useState } from "react";

// Split-pane reviewer screen (slide 4 "Reviewer" persona, slide 13
// "Reviewer Queue"): document preview on the left, extracted JSON +
// traceable risk scorecard on the right.

type RuleEvaluationView = { ruleKey: string; passed: boolean; scoreDeltaApplied: number };

type JobDetail = {
  id: string;
  stage: string;
  extractedJson: Record<string, unknown> | null;
  riskScore: number | null;
  riskLevel: "low" | "medium" | "high" | null;
  aiSummary: string | null;
};

export function ReviewerScreen({ jobId }: { jobId: string }) {
  const [job, setJob] = useState<JobDetail | null>(null);

  useEffect(() => {
    fetch(`/api/v1/jobs/${jobId}`)
      .then((r) => r.json())
      .then(setJob);
  }, [jobId]);

  if (!job) return <div>Loading…</div>;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
      <section>
        <h2>Document Preview</h2>
        {/* Wire up your PDF/image viewer against job.id's source document. */}
      </section>

      <section>
        <h2>Structured Output &amp; Risk</h2>
        <pre>{JSON.stringify(job.extractedJson, null, 2)}</pre>

        {job.riskLevel && (
          <div className={`risk-badge risk-${job.riskLevel}`}>
            Risk Score: {job.riskScore} ({job.riskLevel.toUpperCase()})
          </div>
        )}

        {job.aiSummary && (
          <div>
            <h3>AI-Generated Summary</h3>
            <p>{job.aiSummary}</p>
          </div>
        )}
      </section>
    </div>
  );
}
