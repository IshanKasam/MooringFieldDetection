import { useEffect, useState } from "react";
import {
  useEnrich,
  useField,
  useProspect,
  useUpdateProspect,
} from "../hooks/useFields";

type Props = {
  prospectId: number | null;
  fieldId: number | null;
  onClose: () => void;
};

export function FieldDetailDrawer({ prospectId, fieldId, onClose }: Props) {
  const { data, isLoading, error } = useProspect(prospectId);
  const { data: fieldRow } = useField(prospectId == null ? fieldId : null);
  const update = useUpdateProspect();
  const enrich = useEnrich();
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [website, setWebsite] = useState("");
  const [name, setName] = useState("");

  useEffect(() => {
    if (!data) return;
    setPhone(data.phone ?? "");
    setEmail(data.email ?? "");
    setWebsite(data.website ?? "");
    setName(data.canonical_business_name ?? "");
  }, [data]);

  if (prospectId == null && fieldId == null) return null;

  const sources = Array.isArray(data?.sources)
    ? data!.sources
    : typeof data?.sources === "string"
      ? (() => {
          try {
            const parsed = JSON.parse(data.sources);
            return Array.isArray(parsed) ? parsed : [data.sources];
          } catch {
            return [data.sources];
          }
        })()
      : [];

  return (
    <aside className="drawer" aria-label="Field / prospect detail">
      <header className="drawer-header">
        <h2>{prospectId != null ? "Prospect detail" : "Field detail"}</h2>
        <button type="button" className="ghost" onClick={onClose}>
          Close
        </button>
      </header>

      {prospectId == null && fieldRow && (
        <div className="drawer-body">
          <section>
            <h3>Location</h3>
            <p>
              {fieldRow.harbor_name || fieldRow.location_name || `Field ${fieldId}`}
            </p>
            <p className="muted">
              {fieldRow.boat_count} boats ·{" "}
              <span className={`status-badge status-${fieldRow.enrichment_status || "pending"}`}>
                {fieldRow.enrichment_status || "pending"}
              </span>
            </p>
            {fieldRow.enrichment_status === "skipped" && (
              <p className="dock-rejected-note">
                ⚠ Filtered out — likely a dock, marina, or pier (not a mooring field).
              </p>
            )}
          </section>
          <p className="muted">
            No prospect linked yet. Run Places enrichment to attach contacts.
          </p>
          <button
            type="button"
            className="primary"
            disabled={enrich.isPending}
            onClick={() => enrich.mutate({ step: "places", limit: 5 })}
          >
            {enrich.isPending ? "Queuing…" : "Enrich places"}
          </button>
          {enrich.isSuccess && (
            <p className="ok">Enrichment queued — map will refresh when done.</p>
          )}
        </div>
      )}

      {prospectId != null && isLoading && <p className="muted">Loading…</p>}
      {prospectId != null && error && (
        <p className="error">{(error as Error).message}</p>
      )}
      {prospectId != null && data && (
        <div className="drawer-body">
          <label>
            Business name
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            Phone
            <input value={phone} onChange={(e) => setPhone(e.target.value)} />
          </label>
          <label>
            Email
            <input value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label>
            Website
            <input
              value={website}
              onChange={(e) => setWebsite(e.target.value)}
            />
          </label>
          <div className="drawer-approve">
            <span>Approved</span>
            <label className="approve-toggle">
              <input
                type="checkbox"
                checked={!!data.approved}
                onChange={(e) =>
                  update.mutate({
                    id: prospectId,
                    body: { approved: e.target.checked },
                  })
                }
              />
              <span>{data.approved ? "Yes" : "No"}</span>
            </label>
          </div>
          <button
            type="button"
            className="primary"
            disabled={update.isPending}
            onClick={() =>
              update.mutate({
                id: prospectId,
                body: {
                  canonical_business_name: name || null,
                  phone: phone || null,
                  email: email || null,
                  website: website || null,
                },
              })
            }
          >
            {update.isPending ? "Saving…" : "Save contacts"}
          </button>
          {update.isSuccess && <p className="ok">Saved.</p>}
          {update.isError && (
            <p className="error">
              {(update.error as Error).message || "Save failed"}
            </p>
          )}

          <section>
            <h3>Harbor</h3>
            <p>{data.harbor_name || "—"}</p>
          </section>
          <section>
            <h3>Research summary</h3>
            <pre className="summary">{data.research_summary || "—"}</pre>
          </section>
          <section>
            <h3>Supply chain</h3>
            <pre className="summary">{data.supply_chain_summary || "—"}</pre>
          </section>
          <section>
            <h3>Linked fields</h3>
            <p>{data.field_ids.join(", ") || "—"}</p>
          </section>
          <section>
            <h3>Sources</h3>
            <ul className="sources">
              {sources.length === 0 && <li className="muted">None</li>}
              {sources.map((s) => (
                <li key={String(s)}>
                  {String(s).startsWith("http") ? (
                    <a href={String(s)} target="_blank" rel="noreferrer">
                      {String(s)}
                    </a>
                  ) : (
                    String(s)
                  )}
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </aside>
  );
}
