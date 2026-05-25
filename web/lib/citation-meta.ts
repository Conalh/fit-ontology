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
  "Plews & Laursen 2013": {
    short: "Plews & Laursen 2013",
    title: "Plews, Laursen, Stanley, Kilding, Buchheit — Training Adaptation and Heart Rate Variability in Elite Endurance Athletes (Sports Med, 2013)",
    description:
      "The HRV-guided training methodology this engine implements: rolling-mean baselines, vagal-derived indices as the recovery signal, multi-day windows over single-day reads. The mild / moderate / severe SD thresholds map directly to this paper's analysis.",
    href: "https://doi.org/10.1007/s40279-013-0071-8",
  },
  "Buchheit 2014": {
    short: "Buchheit 2014",
    title: "Buchheit — Monitoring training status with HR measures: do all roads lead to Rome? (Frontiers in Physiology, 2014)",
    description:
      "Comprehensive review of resting / submaximal / post-exercise HR measures as training-status proxies. Source for treating RHR elevation as an early signal of incomplete recovery, illness onset, or autonomic stress.",
    href: "https://doi.org/10.3389/fphys.2014.00073",
  },
  "ACSM 11e §7": {
    short: "ACSM 11e §7",
    title: "ACSM's Guidelines for Exercise Testing and Prescription, 11th ed. (2021)",
    description:
      "The ACSM's reference text — the standard progression model (5–10% weekly load increase for healthy adults) and recovery/sleep thresholds come from here. Section 7 covers general principles of exercise prescription.",
    href: "https://shop.lww.com/ACSM-s-Guidelines-for-Exercise-Testing-and-Prescription/p/9781975150181",
  },
  "Gabbett 2016": {
    short: "Gabbett 2016",
    title: "Gabbett — The training–injury prevention paradox: should athletes be training smarter and harder? (BJSM, 2016)",
    description:
      "Defined the Acute:Chronic Workload Ratio (ACWR) and identified the 0.8–1.3 'sweet spot' versus the >1.5 'danger zone' for injury risk. Source for both the high-ACWR and low-ACWR signals.",
    href: "https://doi.org/10.1136/bjsports-2015-095788",
  },
  "Foster 1998": {
    short: "Foster 1998",
    title: "Foster — Monitoring training in athletes with reference to overtraining syndrome (Med Sci Sports Exerc, 1998)",
    description:
      "The canonical session-RPE paper. Defined RPE × duration as a single-number internal-load proxy and showed its relationship to training monotony and overreaching. Source for the rising-RPE signal — RPE climbing for the same prescribed work is the textbook marker of accumulating fatigue.",
    href: "https://pubmed.ncbi.nlm.nih.gov/9662690/",
  },
};

/**
 * Legacy citation aliases — earlier engine versions emitted these
 * names (often with the wrong year or a non-canonical paper). Any
 * historical recommendation_overrides rows persisted under the old
 * names get routed to the right meta when the popover renders.
 * Fresh recommendations from the engine use the canonical names
 * above directly.
 */
const CITATION_ALIASES: Record<string, string> = {
  "Plews & Laursen 2017": "Plews & Laursen 2013",
  "Foster sRPE 1995": "Foster 1998",
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
  const canonical = CITATION_ALIASES[short] ?? short;
  return (
    CITATION_META[canonical] ?? {
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
