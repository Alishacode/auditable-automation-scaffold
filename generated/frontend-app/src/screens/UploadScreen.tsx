import { useState } from "react";
import { uploadDocument } from "../api";

export function UploadScreen({
  onUploaded,
}: {
  onUploaded: (jobId: string) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<"idle" | "uploading" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  async function handleUpload() {
    if (!file) return;
    setStatus("uploading");
    setError(null);
    try {
      const { job_id } = await uploadDocument(file);
      onUploaded(job_id);
    } catch (e) {
      setStatus("error");
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div
      style={{
        padding: "1.5rem",
        maxWidth: 600,
        margin: "0 auto",
        textAlign: "left",
      }}
    >
      <h2>Upload a document</h2>
      <input
        type="file"
        accept="application/pdf,image/*"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
      />
      <div style={{ marginTop: "1rem" }}>
        <button
          onClick={handleUpload}
          disabled={!file || status === "uploading"}
        >
          {status === "uploading" ? "Uploading…" : "Upload & Process"}
        </button>
      </div>
      {error && <p style={{ color: "#c62828" }}>Error: {error}</p>}
    </div>
  );
}
