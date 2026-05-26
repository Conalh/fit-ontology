"use client";

import Link from "next/link";
import type { CSSProperties } from "react";
import {
  DEMO_PERSONAS,
  clientDetailHref,
  markTourStarted,
  type DemoPersona,
  type TourVerdict,
} from "@/lib/tour/constants";

const VERDICT_CLASS: Record<TourVerdict, string> = {
  Deload: "fit-tour-verdict--deload",
  Conservative: "fit-tour-verdict--conservative",
  Standard: "fit-tour-verdict--standard",
};

export function PersonaGrid() {
  return (
    <div className="fit-tour-personas">
      {DEMO_PERSONAS.map((persona) => (
        <PersonaCard key={persona.clientId} persona={persona} />
      ))}
    </div>
  );
}

function PersonaCard({ persona }: { persona: DemoPersona }) {
  const style = {
    "--persona-accent": persona.accent,
  } as CSSProperties;

  return (
    <Link
      href={clientDetailHref(persona.clientId)}
      className="fit-tour-persona"
      style={style}
      onClick={() => markTourStarted()}
    >
      <div className="fit-tour-persona-top">
        <div>
          <div className="fit-tour-persona-name">{persona.name}</div>
          <div className="fit-tour-persona-goal">{persona.goal}</div>
        </div>
        <span className={`fit-tour-verdict ${VERDICT_CLASS[persona.verdict]}`}>{persona.verdict}</span>
      </div>
      <p className="fit-tour-persona-hook">{persona.hook}</p>
      <span className="fit-tour-persona-cta">Open client week →</span>
    </Link>
  );
}
