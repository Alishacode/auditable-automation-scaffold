import { useState } from "react";

// Workspace Admin screen (slide 4 "Need: Low-code configuration", slide 6
// Template Agent flow): natural-language intent in, draft JSON Schema +
// Rules Builder out, PUBLISH locks the version (slide 7 Publish Lock).

export function TemplateBuilder() {
  const [intent, setIntent] = useState("");
  const [draftSchema, setDraftSchema] = useState<object | null>(null);

  async function generateDraft() {
    const res = await fetch("/api/v1/templates/draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ natural_language_intent: intent }),
    });
    setDraftSchema(await res.json());
  }

  async function publish(templateId: string, versionId: string) {
    // Publishing is irreversible for this version — see backend
    // TemplateVersion.publish(). Confirm with the user before calling.
    await fetch(
      `/api/v1/templates/${templateId}/versions/${versionId}/publish`,
      { method: "POST" },
    );
  }

  return (
    <div>
      <label>
        Natural Language Intent
        <input value={intent} onChange={(e) => setIntent(e.target.value)} />
      </label>
      <button onClick={generateDraft}>Generate Draft Schema</button>

      {draftSchema && (
        <>
          <h3>Draft Schema</h3>
          <pre>{JSON.stringify(draftSchema, null, 2)}</pre>
          {/* Rules Builder (field / condition / value / category) goes here,
              reading fields out of draftSchema.properties. */}
        </>
      )}
    </div>
  );
}
