"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api, type RosterRow } from "@/lib/api";

/**
 * Roster — Monday-morning triage. Pulls /api/roster and tabulates every
 * client by recommendation label, flag kinds, confidence, and how fresh
 * the data is. Intentionally minimal styling — this is the scaffold
 * surface Claude Design will replace.
 */
export default function RosterPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["roster"],
    queryFn: api.roster,
  });

  return (
    <main className="mx-auto w-full max-w-5xl px-6 py-12">
      <header className="mb-8">
        <h1 className="text-3xl font-semibold tracking-tight">FitOntology</h1>
        <p className="mt-1 text-sm text-slate-600">
          Roster · ranked by recommendation urgency
        </p>
      </header>

      {isLoading && <p className="text-sm text-slate-500">Loading roster…</p>}
      {error && (
        <p className="text-sm text-red-600">
          Could not reach the API. Is{" "}
          <code className="rounded bg-red-50 px-1 py-0.5 text-xs">
            fit-ontology-serve
          </code>{" "}
          running on {process.env.NEXT_PUBLIC_API_URL || "the same origin"}?
        </p>
      )}

      {data && data.length === 0 && (
        <p className="text-sm text-slate-500">No clients in the database yet.</p>
      )}

      {data && data.length > 0 && <RosterTable rows={data} />}
    </main>
  );
}

const RANK: Record<RosterRow["label"], number> = {
  Deload: 0,
  Conservative: 1,
  Standard: 2,
  "No recent data": 3,
};

function RosterTable({ rows }: { rows: RosterRow[] }) {
  const sorted = [...rows].sort(
    (a, b) =>
      RANK[a.label] - RANK[b.label] ||
      (b.confidence ?? 0) - (a.confidence ?? 0),
  );
  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-4 py-3 font-medium">Client</th>
            <th className="px-4 py-3 font-medium">Recommendation</th>
            <th className="px-4 py-3 font-medium">Flags</th>
            <th className="px-4 py-3 font-medium">Confidence</th>
            <th className="px-4 py-3 font-medium">Last data</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {sorted.map((row) => (
            <tr key={row.client_id} className="hover:bg-slate-50">
              <td className="px-4 py-3">
                <Link
                  href={`/clients/${row.client_id}`}
                  className="font-medium text-slate-900 hover:underline"
                >
                  {row.name}
                </Link>
                <div className="text-xs text-slate-500">{row.goal}</div>
              </td>
              <td className="px-4 py-3">
                <Label label={row.label} />
              </td>
              <td className="px-4 py-3 text-xs text-slate-600">
                {row.flags.length === 0 ? "—" : row.flags.join(", ")}
              </td>
              <td className="px-4 py-3 text-slate-700">
                {row.confidence == null
                  ? "—"
                  : `${Math.round(row.confidence * 100)}%`}
              </td>
              <td className="px-4 py-3 text-slate-700">
                {row.last_data_days == null
                  ? "—"
                  : `${row.last_data_days}d ago`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Label({ label }: { label: RosterRow["label"] }) {
  const tone = {
    Deload: "bg-red-100 text-red-800",
    Conservative: "bg-amber-100 text-amber-800",
    Standard: "bg-emerald-100 text-emerald-800",
    "No recent data": "bg-slate-100 text-slate-600",
  }[label];
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}
    >
      {label}
    </span>
  );
}
