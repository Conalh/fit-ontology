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

export default function NewClientPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const rosterQ = useQuery({ queryKey: ["roster"], queryFn: api.roster });
  const [serverError, setServerError] = useState<string | null>(null);

  const accentHex = "#4F46E5";
  const accentVars = {
    "--accent": accentHex,
    "--accent-bg": withAlpha(accentHex, 0.10),
  } as CSSProperties;

  const toast = useToast();
  const create = useMutation({
    mutationFn: (payload: ClientFormPayload) => api.createClient(payload),
    onSuccess: (result, payload) => {
      qc.invalidateQueries({ queryKey: ["roster"] });
      toast.show(`Client added: ${payload.name}.`);
      router.push(`/clients/?id=${result.id}`);
    },
    onError: (e: Error) => {
      setServerError(e.message);
      toast.show(`Could not create client: ${e.message}`, "error");
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
      <Sidebar roster={rosterQ.data ?? []} activeNav="roster" accentHex={accentHex} />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <TopBar
          breadcrumb={
            <>
              <Link href="/" style={{ color: "var(--text-muted)", textDecoration: "none" }}>
                Roster
              </Link>
              <Chevron />
              <span style={{ color: "var(--text)", fontWeight: 500 }}>New client</span>
            </>
          }
        />

        <div style={{ padding: "28px 28px 36px", maxWidth: 720 }}>
          <header style={{ marginBottom: 18 }}>
            <h1 style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em", margin: 0, color: "var(--text)" }}>
              Add a client
            </h1>
            <p style={{ margin: "4px 0 0", fontSize: 12.5, color: "var(--text-muted)" }}>
              Intake fields. Wearable data and sessions come in separately through{" "}
              <strong>Upload</strong> or the sync scripts.
            </p>
          </header>

          <ClientForm
            submitLabel="Create client"
            submittingLabel="Creating…"
            serverError={serverError}
            isPending={create.isPending}
            onCancel={() => router.push("/")}
            onSubmit={(payload) => {
              setServerError(null);
              return create.mutateAsync(payload).then(() => undefined);
            }}
          />
        </div>
      </div>
    </div>
  );
}
