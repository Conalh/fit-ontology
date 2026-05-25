/**
 * Frontend-only metadata for the literature citations the reasoning
 * engine emits. The backend ships only the short citation string
 * (e.g. "Plews & Laursen 2017"); this map adds the popover content
 * — full title, one-line description of why it matters, link to
 * the paper — so the citation chip can become a clickable tooltip.
 *
 * Add new citations here when ``reasoning.CITATIONS`` grows. Unknown
 * keys fall back to a "no description available" popover so the UI
 * doesn't crash on a citation it doesn't know about yet.
 */

export interface CitationMeta {
  /** Short label shown on the chip (matches reasoning.CITATIONS values). */
  short: string;
  /** Full bibliographic-ish title for the popover heading. */
  title: string;
  /** One-sentence explanation of what the work contributes here. */
  description: string;
  /** Direct link to the paper or the closest authoritative source. */
  href?: string;
}

export const CITATION_META: Record<string, CitationMeta> = {
  "Plews & Laursen 2017": {
    short: "Plews & Laursen 2017",
    title: "Plews & Laursen — Heart-rate-variability monitoring (Sports Med, 2017)",
    description:
      "Established the 28-day rolling baseline + multi-day rolling-mean methodology this engine uses for HRV interpretation. The mild / moderate / severe SD thresholds come straight from this work.",
    href: "https://doi.org/10.1007/s40279-013-0114-1",
  },
  "Buchheit 2014": {
    short: "Buchheit 2014",
    title: "Buchheit — Monitoring training status with HR measures (Frontiers in Physiology, 2014)",
    description:
      "Resting-HR elevation as an early signal of incomplete recovery or illness onset. Underpins the RHR-above-baseline and RHR-trend-up rules.",
    href: "https://doi.org/10.3389/fphys.2014.00073",
  },
  "ACSM 11e §7": {
    short: "ACSM 11e §7",
    title: "ACSM's Guidelines for Exercise Testing and Prescription, 11th ed.",
    description:
      "Section 7 covers sleep & recovery thresholds for adult athletic populations. Source for the standard-progression 5–10% load-increase guidance and the sleep deficit floors.",
    href: "https://www.acsm.org/education-resources/books/acsms-guidelines-for-exercise-testing-and-prescription",
  },
  "Gabbett 2016": {
    short: "Gabbett 2016",
    title: "Gabbett — The training–injury prevention paradox (BJSM, 2016)",
    description:
      "Defined the Acute:Chronic Workload Ratio (ACWR) and identified the 0.8–1.3 'sweet spot' versus the >1.5 danger zone for injury risk. Source for both the high-ACWR and low-ACWR signals.",
    href: "https://doi.org/10.1136/bjsports-2015-095788",
  },
  "Foster sRPE 1995": {
    short: "Foster sRPE 1995",
    title: "Foster — Session RPE method (Med Sci Sports Exerc, 1995)",
    description:
      "Introduced session-RPE as a single-number internal-load proxy. Source for the rising-RPE signal — RPE climbing for the same prescribed work is the textbook marker of accumulating fatigue.",
    href: "https://pubmed.ncbi.nlm.nih.gov/9694422/",
  },
};

/**
 * Frontend-only metadata for each engine flag kind. Used by the
 * signal-chip tooltip to explain to the trainer what the signal
 * actually means + which citation supports the threshold.
 *
 * Keys mirror ``reasoning.FLAG_CITATIONS``. Falls back to a generic
 * "no description" popover for any unknown kind so a new engine
 * signal still renders sanely until this map catches up.
 */
export interface FlagMeta {
  description: string;
}

export const FLAG_META: Record<string, FlagMeta> = {
  hrv_below_baseline: {
    description:
      "Heart-rate variability has dropped below this client's 28-day baseline by enough to suggest incomplete recovery. The harder the drop (in standard deviations), the more conservative the verdict.",
  },
  hrv_trend_down: {
    description:
      "HRV has been trending downward over the recent rolling window — an early sign of accumulating stress before any single day looks bad.",
  },
  rhr_above_baseline: {
    description:
      "Resting heart rate is elevated versus this client's baseline. Often the first hardware signal of systemic stress, dehydration, or illness onset.",
  },
  rhr_trend_up: {
    description:
      "Resting heart rate has been climbing over the recent rolling window — same story as the absolute elevation, just earlier in its development.",
  },
  sleep_deficit: {
    description:
      "Sleep duration is consistently below the floor for this athletic population. The single biggest controllable recovery lever.",
  },
  sleep_trend_down: {
    description:
      "Sleep duration has been eroding over recent nights even if individual nights still look acceptable.",
  },
  rpe_rising: {
    description:
      "Subjective effort (sRPE) is rising for similar prescribed work — the textbook marker that the same training is costing more than it used to.",
  },
  acwr_high: {
    description:
      "Acute:Chronic Workload Ratio is in Gabbett's 'danger zone' — a sharp spike in recent training relative to the rolling chronic average.",
  },
  acwr_low: {
    description:
      "Acute:Chronic Workload Ratio shows the athlete is under-loaded: recent training has dropped well below the chronic average, increasing tissue-tolerance risk if you ramp back up too fast.",
  },
  training_readiness_low: {
    description:
      "Garmin's proprietary Training Readiness composite is low this morning. Black-box but tracks well with the HRV/sleep/RHR signals when they're present.",
  },
};

export function citationMeta(short: string): CitationMeta {
  return (
    CITATION_META[short] ?? {
      short,
      title: short,
      description: "No additional description available for this citation.",
    }
  );
}

export function flagMeta(kind: string): FlagMeta {
  return (
    FLAG_META[kind] ?? {
      description: "No description available for this signal yet.",
    }
  );
}
