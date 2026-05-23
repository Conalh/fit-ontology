"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { CSSProperties, FormEvent } from "react";
import { Sidebar, TopBar } from "@/components/chrome";
import { withAlpha } from "@/lib/accent";
import { api, type AskTrace } from "@/lib/api";

interface Turn {
  question: string;
  answer: string;
  traces: AskTrace[];
}

/**
 * Ask FitOntology — conversational layer over the same reasoning + DB
 * the dashboard uses. The assistant has five tools (list_clients,
 * get_client_summary, get_recent_metrics, get_recent_sessions,
 * compute_recommendation, get_recent_overrides); we surface every tool
 * call inline so the trainer can see what data drove the answer.
 *
 * Multi-turn context flows by handing the prior turn's full Anthropic
 * message stream back as `history` on the next call — the same pattern
 * the Streamlit page used.
 */
export default function AskPage() {
  const rosterQ = useQuery({ queryKey: ["roster"], queryFn: api.roster });

  const accentHex = "#4F46E5";
  const accentVars = {
    "--accent": accentHex,
    "--accent-bg": withAlpha(accentHex, 0.10),
  } as CSSProperties;

  const [turns, setTurns] = useState<Turn[]>([]);
  const [history, setHistory] = useState<Record<string, unknown>[]>([]);
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const ask = useMutation({
    mutationFn: (question: string) => api.ask({ question, history }),
    onSuccess: (res, question) => {
      setTurns((prev) => [...prev, { question, answer: res.answer, traces: res.traces }]);
      setHistory(res.messages);
    },
  });

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns, ask.isPending]);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const q = draft.trim();
    if (!q || ask.isPending) return;
    setDraft("");
    ask.mutate(q);
  };

  const clearConversation = () => {
    setTurns([]);
    setHistory([]);
    ask.reset();
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
      <Sidebar roster={rosterQ.data ?? []} activeNav="ask" accentHex={accentHex} />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <TopBar breadcrumb={<span style={{ color: "var(--text)", fontWeight: 500 }}>Ask FitOntology</span>}>
          {turns.length > 0 && (
            <button className="btn-ghost" onClick={clearConversation}>
              Clear
            </button>
          )}
        </TopBar>

        <div style={{ padding: "28px 28px 0", maxWidth: 820 }}>
          <h1 style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em", margin: 0, color: "var(--text)" }}>
            Ask FitOntology
          </h1>
          <p style={{ margin: "4px 0 0", fontSize: 12.5, color: "var(--text-muted)" }}>
            Chat with the same reasoning engine the dashboard uses. Every answer cites the tools it ran.
          </p>
        </div>

        <div ref={scrollRef} style={{ flex: 1, overflow: "auto", padding: "20px 28px 12px", maxWidth: 820 }}>
          {turns.length === 0 && !ask.isPending && <EmptyState onPickPrompt={(p) => setDraft(p)} />}

          <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
            {turns.map((t, i) => (
              <TurnBlock key={i} turn={t} />
            ))}
            {ask.isPending && (
              <div style={{ fontSize: 12.5, color: "var(--text-muted)" }}>Thinking…</div>
            )}
            {ask.error && <AskError error={ask.error as Error} />}
          </div>
        </div>

        <form
          onSubmit={onSubmit}
          style={{
            padding: "12px 28px 22px",
            borderTop: "1px solid var(--border)",
            background: "var(--surface)",
            maxWidth: 820,
            width: "100%",
            boxSizing: "border-box",
          }}
        >
          <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  onSubmit(e);
                }
              }}
              placeholder="e.g. what should I do with Ben this week?"
              rows={1}
              style={{
                flex: 1,
                padding: "10px 12px",
                background: "var(--surface-2)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                fontSize: 13,
                fontFamily: "inherit",
                color: "var(--text)",
                resize: "vertical",
                minHeight: 40,
                maxHeight: 220,
                boxSizing: "border-box",
              }}
            />
            <button
              type="submit"
              className="btn-primary"
              disabled={ask.isPending || !draft.trim()}
              style={{ flexShrink: 0 }}
            >
              {ask.isPending ? "…" : "Send"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function AskError({ error }: { error: Error }) {
  const msg = error.message || "Unknown error.";
  const noKey = /ANTHROPIC_API_KEY/i.test(msg);

  if (noKey) {
    return (
      <div
        style={{
          padding: "12px 14px",
          border: "1px solid var(--warn-border)",
          background: "var(--warn-bg)",
          borderRadius: 8,
          fontSize: 12.5,
          color: "var(--text)",
          lineHeight: 1.5,
        }}
      >
        <div style={{ fontWeight: 600, marginBottom: 4 }}>Claude API key needed</div>
        Ask FitOntology calls Anthropic&apos;s API. Add an{" "}
        <code style={{ fontFamily: "var(--font-mono)", fontSize: 11.5 }}>ANTHROPIC_API_KEY</code> line to{" "}
        <code style={{ fontFamily: "var(--font-mono)", fontSize: 11.5 }}>.env</code> in the project root, then
        restart <code style={{ fontFamily: "var(--font-mono)", fontSize: 11.5 }}>fit-ontology-serve</code>.{" "}
        <a
          href="https://console.anthropic.com/settings/keys"
          target="_blank"
          rel="noopener noreferrer"
          style={{ color: "var(--accent)" }}
        >
          Get an API key →
        </a>
      </div>
    );
  }

  return (
    <div style={{ fontSize: 12.5, color: "var(--danger)" }}>{msg}</div>
  );
}

function EmptyState({ onPickPrompt }: { onPickPrompt: (p: string) => void }) {
  const examples = [
    "what should I do with Ben this week?",
    "who needs a deload?",
    "show me Carla's HRV trend",
    "did I agree with the system on Alice last week?",
  ];
  return (
    <div
      style={{
        border: "1px dashed var(--border)",
        borderRadius: 10,
        padding: "24px 24px",
        background: "var(--surface)",
      }}
    >
      <p style={{ margin: 0, fontSize: 13, fontWeight: 500, color: "var(--text)" }}>
        Ask anything about your clients.
      </p>
      <p style={{ margin: "4px 0 14px", fontSize: 12, color: "var(--text-muted)" }}>
        The assistant has read access to your ontology — clients, metrics, sessions, recommendations, and your
        override history.
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {examples.map((p) => (
          <button
            key={p}
            onClick={() => onPickPrompt(p)}
            style={{
              padding: "5px 10px",
              border: "1px solid var(--border)",
              background: "var(--surface-2)",
              color: "var(--text)",
              borderRadius: 999,
              cursor: "pointer",
              fontSize: 11.5,
              fontFamily: "inherit",
            }}
          >
            {p}
          </button>
        ))}
      </div>
    </div>
  );
}

function TurnBlock({ turn }: { turn: Turn }) {
  return (
    <article style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <div
          style={{
            background: "var(--surface-2)",
            border: "1px solid var(--border)",
            borderRadius: 12,
            padding: "8px 12px",
            fontSize: 13,
            color: "var(--text)",
            maxWidth: "75%",
            whiteSpace: "pre-wrap",
          }}
        >
          {turn.question}
        </div>
      </div>
      <div>
        <div
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 12,
            padding: "12px 14px",
            fontSize: 13.5,
            color: "var(--text)",
            lineHeight: 1.55,
            whiteSpace: "pre-wrap",
          }}
        >
          {turn.answer}
        </div>
        {turn.traces.length > 0 && (
          <details
            style={{
              marginTop: 6,
              padding: "6px 14px",
              fontSize: 11.5,
              color: "var(--text-muted)",
            }}
          >
            <summary style={{ cursor: "pointer" }}>Tools used ({turn.traces.length})</summary>
            <ul style={{ margin: "8px 0 0", padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 4 }}>
              {turn.traces.map((t, i) => (
                <li key={i} style={{ fontFamily: "var(--font-mono)" }}>
                  <span style={{ color: "var(--text)", fontWeight: 600 }}>{t.name}</span>
                  {Object.keys(t.arguments).length > 0 && (
                    <span style={{ color: "var(--text-muted)" }}>
                      ({Object.entries(t.arguments).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ")})
                    </span>
                  )}
                  <span style={{ color: "var(--text-muted)" }}> → {t.result_summary}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </article>
  );
}
