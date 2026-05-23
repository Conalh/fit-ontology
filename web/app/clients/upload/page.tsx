"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRef, useState } from "react";
import type { CSSProperties, DragEvent } from "react";
import { Chevron, Sidebar, TopBar } from "@/components/chrome";
import { withAlpha } from "@/lib/accent";
import { api } from "@/lib/api";
import { useClientAccent } from "@/lib/use-client-accent";
import { useQueryParam } from "@/lib/use-query-param";

/**
 * Upload — drop a wearable export (Apple Health zip/xml, Strava CSV,
 * Whoop JSON) and the server detects the format and inserts the rows.
 *
 * Reads ``?id=<client_id>`` via the useEffect-based hook (avoids the
 * Suspense + useSearchParams hydration stall on direct URL loads).
 */
export default function ClientUploadPage() {
  const clientIdParam = useQueryParam("id");
  if (clientIdParam === null) return null;
  return <UploadInner clientId={clientIdParam} />;
}

function UploadInner({ clientId }: { clientId: string }) {
  const missing = !clientId;
  const [accentHex] = useClientAccent(clientId || "_unknown");

  const rosterQ = useQuery({ queryKey: ["roster"], queryFn: api.roster });
  const clientQ = useQuery({
    queryKey: ["client", clientId],
    queryFn: () => api.client(clientId),
    enabled: !missing,
  });
  const client = clientQ.data as { name?: string } | undefined;
  const clientName = (client?.name as string | undefined) ?? clientId;

  const accentVars = {
    "--accent": accentHex,
    "--accent-bg": withAlpha(accentHex, 0.10),
  } as CSSProperties;

  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const qc = useQueryClient();

  const upload = useMutation({
    mutationFn: (file: File) => api.upload(clientId, file),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["metrics", clientId] });
      qc.invalidateQueries({ queryKey: ["sessions", clientId] });
      qc.invalidateQueries({ queryKey: ["roster"] });
    },
  });

  const handleFile = (file: File | undefined) => {
    if (!file) return;
    upload.mutate(file);
  };

  if (missing) {
    return (
      <main style={{ padding: "40px", color: "var(--text-muted)" }}>
        <p>
          Missing client id. Open a client from the{" "}
          <Link href="/" style={{ color: "var(--accent)" }}>
            roster
          </Link>
          .
        </p>
      </main>
    );
  }

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    handleFile(e.dataTransfer.files[0]);
  };

  return (
    <div
      style={{
        ...accentVars,
        display: "flex",
        width: "100%",
        minHeight: "100%",
        background: "var(--surface)",
        color: "var(--text)",
        fontFamily: "var(--font-sans)",
        fontSize: 14,
        lineHeight: 1.5,
      }}
    >
      <Sidebar roster={rosterQ.data ?? []} activeClientId={clientId} activeNav="client" accentHex={accentHex} />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <TopBar
          breadcrumb={
            <>
              <Link href="/" style={{ color: "var(--text-muted)", textDecoration: "none" }}>
                Roster
              </Link>
              <Chevron />
              <Link href={`/clients?id=${clientId}`} style={{ color: "var(--text-muted)", textDecoration: "none" }}>
                {clientName}
              </Link>
              <Chevron />
              <span style={{ color: "var(--text)", fontWeight: 500 }}>Upload</span>
            </>
          }
        >
          <Link href={`/clients?id=${clientId}`} className="btn-ghost">
            Back to detail
          </Link>
        </TopBar>

        <div style={{ padding: "28px 28px 36px", maxWidth: 720 }}>
          <header style={{ marginBottom: 18 }}>
            <h1
              style={{
                fontSize: 22,
                fontWeight: 600,
                letterSpacing: "-0.02em",
                margin: 0,
                color: "var(--text)",
              }}
            >
              Upload wearable data
            </h1>
            <p style={{ margin: "4px 0 0", fontSize: 12.5, color: "var(--text-muted)" }}>
              For <span style={{ color: "var(--text)" }}>{clientName}</span>. Accepts Apple Health export
              (<code style={{ fontFamily: "var(--font-mono)" }}>.zip</code> /{" "}
              <code style={{ fontFamily: "var(--font-mono)" }}>.xml</code>), Strava bulk export
              (<code style={{ fontFamily: "var(--font-mono)" }}>.csv</code>), or Whoop daily-record JSON
              (<code style={{ fontFamily: "var(--font-mono)" }}>.json</code>). Format detected automatically.
            </p>
          </header>

          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            onClick={() => inputRef.current?.click()}
            style={{
              border: `1px dashed ${dragOver ? accentHex : "var(--border)"}`,
              background: dragOver ? withAlpha(accentHex, 0.06) : "var(--surface)",
              borderRadius: 10,
              padding: "44px 24px",
              textAlign: "center",
              cursor: "pointer",
              transition: "background 0.12s, border-color 0.12s",
            }}
          >
            <div
              style={{
                fontSize: 13.5,
                fontWeight: 500,
                color: "var(--text)",
                marginBottom: 4,
              }}
            >
              Drop a file here, or click to choose
            </div>
            <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
              <code style={{ fontFamily: "var(--font-mono)" }}>.zip</code>,{" "}
              <code style={{ fontFamily: "var(--font-mono)" }}>.xml</code>,{" "}
              <code style={{ fontFamily: "var(--font-mono)" }}>.csv</code>, or{" "}
              <code style={{ fontFamily: "var(--font-mono)" }}>.json</code>
            </div>
            <input
              ref={inputRef}
              type="file"
              accept=".zip,.xml,.csv,.json"
              onChange={(e) => handleFile(e.target.files?.[0] ?? undefined)}
              style={{ display: "none" }}
            />
          </div>

          {upload.isPending && (
            <p style={{ marginTop: 14, fontSize: 12.5, color: "var(--text-muted)" }}>Uploading and parsing…</p>
          )}
          {upload.error && (
            <p style={{ marginTop: 14, fontSize: 12.5, color: "var(--danger)" }}>
              {(upload.error as Error).message}
            </p>
          )}
          {upload.isSuccess && upload.data && (
            <section
              style={{
                marginTop: 18,
                padding: "14px 16px",
                border: "1px solid var(--border)",
                borderRadius: 10,
                background: "var(--surface)",
              }}
            >
              <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text)" }}>
                Imported <span style={{ fontVariantNumeric: "tabular-nums" }}>{upload.data.inserted}</span> rows
                {upload.data.kinds.length > 0 && (
                  <>
                    {" "}
                    ·{" "}
                    <span style={{ color: "var(--text-muted)" }}>
                      {upload.data.kinds.join(", ")}
                    </span>
                  </>
                )}
                .
              </div>
              <div style={{ marginTop: 6, fontSize: 12, color: "var(--text-muted)" }}>
                Trend charts refresh automatically.{" "}
                <Link
                  href={`/clients?id=${clientId}`}
                  style={{ color: "var(--accent)", textDecoration: "none" }}
                >
                  Back to detail →
                </Link>
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
