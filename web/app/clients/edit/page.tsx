"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { CSSProperties } from "react";
import { ClientForm } from "@/components/client-form";
import { Chevron, Sidebar, TopBar } from "@/components/chrome";
import { useToast } from "@/components/toast";
import { withAlpha } from "@/lib/accent";
import { api, type ClientFormPayload } from "@/lib/api";
import { useQueryParam } from "@/lib/use-query-param";

export default function EditClientPage() {
  const clientIdParam = useQueryParam("id");
  if (clientIdParam === null) return null;
  return <EditInner clientId={clientIdParam} />;
}

function EditInner({ clientId }: { clientId: string }) {
  const router = useRouter();
  const qc = useQueryClient();

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

  const toast = useToast();
  const update = useMutation({
    mutationFn: (payload: ClientFormPayload) => api.updateClient(clientId, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["roster"] });
      qc.invalidateQueries({ queryKey: ["client", clientId] });
      toast.show("Changes saved.");
      router.push(`/clients/?id=${clientId}`);
    },
    onError: (e: Error) => {
      setServerError(e.message);
      toast.show(`Could not save: ${e.message}`, "error");
    },
  });

  // Delete is irreversible — cascades across sessions, metrics,
  // recommendations, overrides, planned sessions, thresholds, share
  // tokens. UX guard is the type-the-name confirm modal below.
  const [confirmOpen, setConfirmOpen] = useState(false);
  const remove = useMutation({
    mutationFn: () => api.deleteClient(clientId),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["roster"] });
      toast.show(`Deleted ${data.name}.`);
      router.push("/");
    },
    onError: (e: Error) => {
      toast.show(`Could not delete: ${e.message}`, "error");
      setConfirmOpen(false);
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

              <DangerZone
                clientName={clientQ.data.name}
                onClickDelete={() => setConfirmOpen(true)}
              />

              {confirmOpen && (
                <ConfirmDeleteModal
                  clientName={clientQ.data.name}
                  isPending={remove.isPending}
                  onCancel={() => setConfirmOpen(false)}
                  onConfirm={() => remove.mutate()}
                />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}


/** Bottom-of-page panel with the "Delete client" button. Visually
 *  separated from the form by a thin danger-coloured border so a
 *  trainer can't mistakenly hit it while scrolling through fields. */
function DangerZone({
  clientName,
  onClickDelete,
}: {
  clientName: string;
  onClickDelete: () => void;
}) {
  return (
    <section
      style={{
        marginTop: 32,
        padding: "16px 20px",
        border: "1px solid var(--danger)",
        borderRadius: 10,
        background: "color-mix(in oklab, var(--danger) 6%, var(--surface))",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        gap: 16,
        flexWrap: "wrap",
      }}
    >
      <div style={{ flex: "1 1 320px", minWidth: 220 }}>
        <h3
          style={{
            margin: 0,
            fontSize: 13.5,
            fontWeight: 600,
            color: "var(--danger)",
            letterSpacing: "-0.005em",
          }}
        >
          Delete client
        </h3>
        <p style={{ margin: "4px 0 0", fontSize: 11.5, color: "var(--text-muted)", lineHeight: 1.5 }}>
          Removes {clientName} and every row that references them — sessions,
          metrics, recommendations, overrides, planned sessions, thresholds, and
          any active share or intake links. This cannot be undone.
        </p>
      </div>
      <button
        type="button"
        onClick={onClickDelete}
        style={{
          padding: "8px 14px",
          background: "var(--danger)",
          color: "white",
          border: "none",
          borderRadius: 6,
          fontSize: 12.5,
          fontWeight: 600,
          cursor: "pointer",
          fontFamily: "inherit",
        }}
      >
        Delete client
      </button>
    </section>
  );
}


/** Type-the-name confirmation modal. Standard "are you sure" guard —
 *  irrelevant clicks (backdrop, Cancel, Esc) dismiss; the only path
 *  forward is to type the exact client name + click Delete. */
function ConfirmDeleteModal({
  clientName,
  isPending,
  onCancel,
  onConfirm,
}: {
  clientName: string;
  isPending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const [typed, setTyped] = useState("");
  const matches = typed.trim() === clientName.trim();
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Delete ${clientName}`}
      onClick={(e) => {
        if (e.target === e.currentTarget && !isPending) onCancel();
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape" && !isPending) onCancel();
      }}
      tabIndex={-1}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.45)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
        padding: 16,
      }}
    >
      <div
        style={{
          width: "100%",
          maxWidth: 460,
          background: "var(--surface-2)",
          border: "1px solid var(--border)",
          borderRadius: 10,
          padding: "20px 22px 18px",
          boxShadow: "0 10px 40px rgba(0,0,0,0.35)",
        }}
      >
        <div
          style={{
            fontSize: 11,
            fontWeight: 500,
            color: "var(--danger)",
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            marginBottom: 6,
          }}
        >
          Delete client
        </div>
        <p
          style={{
            margin: "0 0 14px",
            fontSize: 13,
            color: "var(--text)",
            lineHeight: 1.5,
          }}
        >
          You&apos;re about to permanently delete <strong>{clientName}</strong> and
          every row that references them. Type the name below to confirm.
        </p>
        <label style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 12 }}>
          <span style={{ fontSize: 11.5, fontWeight: 500, color: "var(--text)" }}>
            Client name
          </span>
          <input
            type="text"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            autoFocus
            disabled={isPending}
            placeholder={clientName}
            style={{
              width: "100%",
              padding: "8px 10px",
              background: "var(--surface)",
              border: `1px solid ${matches ? "var(--danger)" : "var(--border)"}`,
              borderRadius: 6,
              fontSize: 13,
              fontFamily: "inherit",
              color: "var(--text)",
              boxSizing: "border-box",
            }}
          />
        </label>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button
            type="button"
            className="btn-ghost"
            onClick={onCancel}
            disabled={isPending}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => matches && onConfirm()}
            disabled={!matches || isPending}
            style={{
              padding: "8px 14px",
              background: matches ? "var(--danger)" : "var(--surface)",
              color: matches ? "white" : "var(--text-muted)",
              border: matches ? "none" : "1px solid var(--border)",
              borderRadius: 6,
              fontSize: 12.5,
              fontWeight: 600,
              cursor: matches && !isPending ? "pointer" : "not-allowed",
              fontFamily: "inherit",
            }}
          >
            {isPending ? "Deleting…" : "Delete forever"}
          </button>
        </div>
      </div>
    </div>
  );
}
