"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { use } from "react";
import { api } from "@/lib/api";

/**
 * Per-client detail page — a stub.
 *
 * The roster's "open" link routes here. Right now it shows the
 * recommendation payload from /api/clients/:id/recommendation in raw-
 * ish form. Claude Design will redraw this; the loader pattern and
 * routing structure stay.
 */
export default function ClientDetailPage({
  params,
}: {
  params: Promise<{ clientId: string }>;
}) {
  const { clientId } = use(params);
  const { data, isLoading, error } = useQuery({
    queryKey: ["rec", clientId],
    queryFn: () => api.recommendation(clientId),
  });

  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-12">
      <Link
        href="/"
        className="text-sm text-slate-500 hover:text-slate-900"
      >
        ← Back to roster
      </Link>
      <h1 className="mt-4 text-2xl font-semibold tracking-tight">
        Client detail
      </h1>
      <p className="text-sm text-slate-600">{clientId}</p>

      {isLoading && (
        <p className="mt-6 text-sm text-slate-500">Computing recommendation…</p>
      )}
      {error && (
        <p className="mt-6 text-sm text-red-600">Could not load recommendation.</p>
      )}
      {data && (
        <div className="mt-8 rounded-lg border border-slate-200 bg-white p-6">
          <h2 className="text-lg font-medium">{data.recommendation}</h2>
          <p className="mt-2 text-sm text-slate-600">{data.rationale}</p>
          <p className="mt-4 text-xs text-slate-500">
            Confidence {Math.round(data.confidence * 100)}% ·{" "}
            {data.source_metric_ids.length} source rows traced · week of{" "}
            {data.week_of}
          </p>
        </div>
      )}
    </main>
  );
}
