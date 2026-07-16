/** Demo tour marketing content — personas + deep links. Interactive steps live in steps.ts. */

export type TourVerdict = "Deload" | "Conservative" | "Standard";

export interface DemoPersona {
  clientId: string;
  name: string;
  goal: string;
  verdict: TourVerdict;
  hook: string;
  accent: string;
}

export const DEMO_PERSONAS: DemoPersona[] = [
  {
    clientId: "c_ben",
    name: "Marcus Hill",
    goal: "Half-marathon return",
    verdict: "Deload",
    hook: "HRV sliding · sleep thin · load elevated — the Monday call is pull back.",
    accent: "#f87171",
  },
  {
    clientId: "c_carla",
    name: "Priya Shah",
    goal: "First pull-up + strength",
    verdict: "Conservative",
    hook: "Recovery is steady, but sleep sits below the floor — progress conservatively and watch response.",
    accent: "#fbbf24",
  },
  {
    clientId: "c_alice",
    name: "Maya Chen",
    goal: "Pain-free trail 10K",
    verdict: "Standard",
    hook: "Recovery clean · load in the sweet spot — normal progression week.",
    accent: "#4ade80",
  },
];

export const TOUR_DESTINATIONS = [
  {
    label: "Monday roster",
    description: "All clients ranked by urgency — deload first.",
    href: "/",
  },
  {
    label: "Calibration",
    description: "System vs trainer agreement over four seeded weeks.",
    href: "/calibration/",
  },
  {
    label: "Ask FitOntology",
    description: "Natural language over the same ontology the charts use.",
    href: "/ask/",
  },
] as const;

export { clientDetailHref, markTourStarted } from "./steps";
