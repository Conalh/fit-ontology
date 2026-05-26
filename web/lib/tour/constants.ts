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
    name: "Captain Ahab",
    goal: "50m harpoon accuracy",
    verdict: "Deload",
    hook: "HRV sliding · sleep thin · ACWR elevated — the Monday call is pull back.",
    accent: "#f87171",
  },
  {
    clientId: "c_carla",
    name: "Lady Macbeth",
    goal: "Wrist + grip endurance",
    verdict: "Conservative",
    hook: "RPE drifting up at constant load — progress, but don't chase numbers.",
    accent: "#fbbf24",
  },
  {
    clientId: "c_alice",
    name: "Elizabeth Bennet",
    goal: "Sub-90 min to Netherfield",
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
