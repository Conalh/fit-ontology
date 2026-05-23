"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import type { CSSProperties } from "react";
import { ClientForm } from "@/components/client-form";
import { Chevron, Sidebar, TopBar } from "@/components/chrome";
import { withAlpha } from "@/lib/accent";
import { api, type ClientFormPayload } from "@/lib/api";

export default function EditClientPage() {
  return (
    <Suspense fallback={null}>
      <EditInner />
    </Suspense>
  );
}

function EditInner() {
  const router = useRouter();
  const qc = useQueryClient();
  const searchParams = useSearchParams();
  const clientId = searchParams.get("id") ?? "";

  const rosterQ = useQuery({ queryKey: ["roster"], queryFn: api.roster });
  const clientQ = useQuery({
    queryKey: ["client", clientId],
    queryFn: () => api.client(clientId),
    enabled: !!clientId,
  });

  const [serverError, setServerError] = useState<string | null>(null);

  const accentHex = "#4F46E5";
  const accentVars = {
    "--accent": accentHex,
    "--accent-bg": withAlpha(accentHex, 0.10),
  } as CSSProperties;

  const update = useMutation({
    mutationFn: (payload: ClientFormPayload) => api.updateClient(clientId, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["roster"] });
      qc.invalidateQueries({ queryKey: ["client", clientId] });
      router.push(`/clients/?id=${clientId}`);
    },
    onError: (e: Error) => {
      setServerError(e.message);
    },
  });

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
      <Sidebar
        roster={rosterQ.data ?? []}
        activeClientId={clientId || undefined}
        activeNav="client"
        accentHex={accentHex}
      />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <TopBar
          breadcrumb={
            <>
              <Link href="/" style={{ color: "var(--text-muted)", textDecoration: "none" }}>
                Roster
              </Link>
              <Chevron />
              {clientId ? (
                <Link
                  href={`/clients/?id=${clientId}`}
                  style={{ color: "var(--text-muted)", textDecoration: "none" }}
                >
                  {clientQ.data?.name ?? clientId}
                </Link>
              ) : (
                <span style={{ color: "var(--text-muted)" }}>—</span>
              )}
              <Chevron />
              <span style={{ color: "var(--text)", fontWeight: 500 }}>Edit</span>
            </>
          }
        />

        <div style={{ padding: "28px 28px 36px", maxWidth: 720 }}>
          {!clientId && (
            <p style={{ color: "var(--text-muted)", fontSize: 12.5 }}>
              Missing client id. Open one from the{" "}
              <Link href="/" style={{ color: "var(--accent)" }}>
                roster
              </Link>
              .
            </p>
          )}

          {clientId && clientQ.isLoading && (
            <p style={{ fontSize: 12.5, color: "var(--text-muted)" }}>Loading client…</p>
          )}
          {clientId && clientQ.error && (
            <p style={{ fontSize: 12.5, color: "var(--danger)" }}>
              Could not load client: {(clientQ.error as Error).message}
            </p>
          )}

          {clientId && clientQ.data && (
            <>
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
                  Edit {clientQ.data.name}
                </h1>
                <p style={{ margin: "4px 0 0", fontSize: 12.5, color: "var(--text-muted)" }}>
                  Update intake fields. Saved changes are reflected on the next dashboard render.
                </p>
              </header>

              <ClientForm
                initial={clientQ.data}
                submitLabel="Save changes"
                submittingLabel="Saving…"
                serverError={serverError}
                isPending={update.isPending}
                onCancel={() => router.push(`/clients/?id=${clientId}`)}
                onSubmit={(payload) => {
                  setServerError(null);
                  return update.mutateAsync(payload).then(() => undefined);
                }}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
