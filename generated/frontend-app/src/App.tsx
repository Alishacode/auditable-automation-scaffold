import { useState } from "react";
import { UploadScreen } from "./screens/UploadScreen";
import { ReviewerScreen } from "./screens/ReviewerScreen";
import { QueueScreen } from "./screens/QueueScreen";

type View =
  | { name: "upload" }
  | { name: "queue" }
  | { name: "job"; jobId: string };

export default function App() {
  const [view, setView] = useState<View>({ name: "upload" });

  return (
    <div style={{ fontFamily: "sans-serif" }}>
      <nav
        style={{
          display: "flex",
          gap: "1rem",
          padding: "1rem",
          borderBottom: "1px solid #8884",
        }}
      >
        <button onClick={() => setView({ name: "upload" })}>Upload</button>
        <button onClick={() => setView({ name: "queue" })}>Review Queue</button>
      </nav>

      {view.name === "upload" && (
        <UploadScreen onUploaded={(jobId) => setView({ name: "job", jobId })} />
      )}
      {view.name === "queue" && (
        <QueueScreen onSelect={(jobId) => setView({ name: "job", jobId })} />
      )}
      {view.name === "job" && (
        <ReviewerScreen
          jobId={view.jobId}
          onBack={() => setView({ name: "upload" })}
        />
      )}
    </div>
  );
}
