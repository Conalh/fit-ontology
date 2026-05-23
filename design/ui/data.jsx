// FitOntology mock data — Maya Okafor, conservative case
// 28 days of daily wearable signals + session logs.
// Narrative: marathon prep wk 8/16. Hard 22mi long run d-10. HRV dipped,
// RHR elevated, sleep fragmented. Now trending back but not fully recovered.

// Seeded pseudo-random for stable noise across reloads
function seeded(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0xffffffff;
  };
}

// Build 28d series. Day 0 = today, day -27 = oldest.
// Each metric: baseline + drift around an event on day -10 (the hard long run).
function buildSeries() {
  const rand = seeded(42);
  const days = [];
  for (let i = -27; i <= 0; i++) {
    // distance from the "hard run" stress event
    const d = i - (-10); // d=0 at the event, positive after
    // stress envelope: rising 5d before, peak at event, decaying ~14d after
    const stress = d < -5
      ? 0
      : d < 0
        ? (d + 5) / 5 * 0.4
        : Math.exp(-d / 7);

    const n = () => (rand() - 0.5) * 2; // noise -1..1

    days.push({
      day: i,
      // HRV RMSSD (ms): baseline ~58, dips to low 40s mid-stress
      hrv: Math.round((58 - stress * 14 + n() * 3) * 10) / 10,
      // Resting HR (bpm): baseline ~52, elevated to 58 during stress
      rhr: Math.round((52 + stress * 5.5 + n() * 1.2) * 10) / 10,
      // Sleep hours: baseline 7.4, drops to ~6 during stress
      sleepHours: Math.round((7.4 - stress * 1.2 + n() * 0.4) * 10) / 10,
      // Sleep score (0-100): baseline 81, drops to low 70s
      sleepScore: Math.round(81 - stress * 9 + n() * 3),
      // Readiness (0-100): baseline 74, dips to high 50s
      readiness: Math.round(74 - stress * 13 + n() * 4),
    });
  }
  return days;
}

const SERIES = buildSeries();

// Sessions over last 28d
const SESSIONS = [
  { day: -27, type: 'Easy run',     duration: 45, rpe: 4, load: 180,  notes: 'Z2, conversational' },
  { day: -26, type: 'Strength',     duration: 50, rpe: 6, load: 300,  notes: 'Posterior chain, 3x' },
  { day: -25, type: 'Rest',         duration: 0,  rpe: 0, load: 0,    notes: '' },
  { day: -24, type: 'Tempo run',    duration: 55, rpe: 7, load: 385,  notes: '4x 1mi @ MP, 90s rest' },
  { day: -23, type: 'Easy run',     duration: 50, rpe: 4, load: 200,  notes: 'Z2 recovery' },
  { day: -22, type: 'Long run',     duration: 110, rpe: 6, load: 660, notes: '14mi steady, last 3 strong' },
  { day: -21, type: 'Rest',         duration: 0,  rpe: 0, load: 0,    notes: '' },
  { day: -20, type: 'Easy run',     duration: 45, rpe: 4, load: 180,  notes: '' },
  { day: -19, type: 'Strength',     duration: 50, rpe: 6, load: 300,  notes: 'Lower body, heavy' },
  { day: -18, type: 'Intervals',    duration: 65, rpe: 8, load: 520,  notes: '6x 800m @ 5k pace' },
  { day: -17, type: 'Easy run',     duration: 50, rpe: 4, load: 200,  notes: '' },
  { day: -16, type: 'Easy run',     duration: 40, rpe: 4, load: 160,  notes: 'Legs felt heavy' },
  { day: -15, type: 'Rest',         duration: 0,  rpe: 0, load: 0,    notes: '' },
  { day: -14, type: 'MP work',      duration: 75, rpe: 7, load: 525,  notes: '8mi w/ 5 @ MP' },
  { day: -13, type: 'Easy run',     duration: 45, rpe: 4, load: 180,  notes: '' },
  { day: -12, type: 'Strength',     duration: 45, rpe: 6, load: 270,  notes: 'Light, pre-long' },
  { day: -11, type: 'Easy run',     duration: 40, rpe: 4, load: 160,  notes: 'Shakeout' },
  { day: -10, type: 'Long run',     duration: 165, rpe: 8, load: 1320, notes: '22mi, hot. Bonked last 4mi.' },
  { day: -9,  type: 'Rest',         duration: 0,  rpe: 0, load: 0,    notes: 'Trainer-flagged' },
  { day: -8,  type: 'Easy run',     duration: 30, rpe: 5, load: 150,  notes: 'Legs trashed' },
  { day: -7,  type: 'Easy run',     duration: 40, rpe: 5, load: 200,  notes: 'Still heavy' },
  { day: -6,  type: 'Strength',     duration: 40, rpe: 5, load: 200,  notes: 'Reduced volume' },
  { day: -5,  type: 'Easy run',     duration: 45, rpe: 4, load: 180,  notes: 'Felt better' },
  { day: -4,  type: 'Rest',         duration: 0,  rpe: 0, load: 0,    notes: '' },
  { day: -3,  type: 'Tempo run',    duration: 50, rpe: 6, load: 300,  notes: '3x 1mi, cut short' },
  { day: -2,  type: 'Easy run',     duration: 45, rpe: 4, load: 180,  notes: 'Z2, easy effort' },
  { day: -1,  type: 'Strength',     duration: 45, rpe: 5, load: 225,  notes: 'Maintained intensity' },
  { day: 0,   type: 'Easy run',     duration: 35, rpe: 4, load: 140,  notes: 'Pre-decision shakeout' },
];

// Compute 28d baseline (mean + sd) per metric — what the engine compares against
function baseline(arr) {
  const mean = arr.reduce((a, b) => a + b, 0) / arr.length;
  const variance = arr.reduce((a, b) => a + (b - mean) ** 2, 0) / arr.length;
  return { mean, sd: Math.sqrt(variance) };
}

function last7Mean(arr) {
  const slice = arr.slice(-7);
  return slice.reduce((a, b) => a + b, 0) / slice.length;
}

const HRV_VALS = SERIES.map(d => d.hrv);
const RHR_VALS = SERIES.map(d => d.rhr);
const SLEEP_H_VALS = SERIES.map(d => d.sleepHours);
const SLEEP_S_VALS = SERIES.map(d => d.sleepScore);
const READ_VALS = SERIES.map(d => d.readiness);

const HRV_BASE = baseline(HRV_VALS);
const RHR_BASE = baseline(RHR_VALS);
const SLEEP_H_BASE = baseline(SLEEP_H_VALS);
const SLEEP_S_BASE = baseline(SLEEP_S_VALS);
const READ_BASE = baseline(READ_VALS);

// Compute Acute (7d) and Chronic (28d) workload — Gabbett ACWR
function buildACWR() {
  const out = [];
  for (let i = 0; i < SERIES.length; i++) {
    // Acute = mean daily load over last 7 days (inclusive)
    const start7 = Math.max(0, i - 6);
    const acute7 = SESSIONS
      .filter(s => s.day >= SERIES[start7].day && s.day <= SERIES[i].day)
      .reduce((a, b) => a + b.load, 0) / 7;
    // Chronic = mean daily load over last 28 days
    const start28 = Math.max(0, i - 27);
    const days28 = i - start28 + 1;
    const chronic28 = SESSIONS
      .filter(s => s.day >= SERIES[start28].day && s.day <= SERIES[i].day)
      .reduce((a, b) => a + b.load, 0) / days28;
    out.push({
      day: SERIES[i].day,
      acwr: chronic28 > 0 ? Math.round((acute7 / chronic28) * 100) / 100 : 1,
      acute: Math.round(acute7),
      chronic: Math.round(chronic28),
    });
  }
  return out;
}

const ACWR_SERIES = buildACWR();

// Daily training load (RPE × duration)
const LOAD_SERIES = SERIES.map(d => {
  const sess = SESSIONS.find(s => s.day === d.day);
  return { day: d.day, load: sess ? sess.load : 0 };
});

// Roster: 8 clients ranked by recommendation urgency
// Each client gets a default accent color (trainer-editable, persisted per-client)
const ROSTER = [
  { id: 'maya',    name: 'Maya Okafor',     sport: 'Marathon',      verdict: 'CONSERVATIVE', confidence: 0.68, change: 'flagged', initials: 'MO', accentHex: '#E11D48' },
  { id: 'jordan',  name: 'Jordan Reyes',    sport: 'Powerlifting',  verdict: 'DELOAD',       confidence: 0.84, change: 'flagged', initials: 'JR', accentHex: '#0F766E' },
  { id: 'priya',   name: 'Priya Shah',      sport: 'CrossFit',      verdict: 'CONSERVATIVE', confidence: 0.61, change: 'new',     initials: 'PS', accentHex: '#7C3AED' },
  { id: 'kenji',   name: 'Kenji Watanabe',  sport: 'Triathlon',     verdict: 'CONSERVATIVE', confidence: 0.55, change: 'new',     initials: 'KW', accentHex: '#0369A1' },
  { id: 'leo',     name: 'Leo Martens',     sport: 'Hyrox',         verdict: 'STANDARD',     confidence: 0.78, change: '',       initials: 'LM', accentHex: '#B45309' },
  { id: 'ana',     name: 'Ana Vidal',       sport: 'Climbing',      verdict: 'STANDARD',     confidence: 0.81, change: '',       initials: 'AV', accentHex: '#15803D' },
  { id: 'sam',     name: 'Sam Eriksen',     sport: 'Cycling',       verdict: 'STANDARD',     confidence: 0.74, change: '',       initials: 'SE', accentHex: '#475569' },
  { id: 'noor',    name: 'Noor Hadid',      sport: 'Rowing',        verdict: 'STANDARD',     confidence: 0.69, change: '',       initials: 'NH', accentHex: '#9333EA' },
];

// Decision history for Maya — past 8 weeks
const DECISION_HISTORY = [
  { weekOf: '2026-05-18', engine: 'CONSERVATIVE', trainer: null,           confidence: 0.68, note: 'Pending — current week' },
  { weekOf: '2026-05-11', engine: 'CONSERVATIVE', trainer: 'CONSERVATIVE', confidence: 0.72, note: 'Agreed. Reduced long-run volume.' },
  { weekOf: '2026-05-04', engine: 'STANDARD',     trainer: 'STANDARD',     confidence: 0.81, note: 'Agreed.' },
  { weekOf: '2026-04-27', engine: 'STANDARD',     trainer: 'STANDARD',     confidence: 0.79, note: 'Agreed.' },
  { weekOf: '2026-04-20', engine: 'CONSERVATIVE', trainer: 'STANDARD',     confidence: 0.58, note: 'Override: travel week, felt fresh on Mon.' },
  { weekOf: '2026-04-13', engine: 'STANDARD',     trainer: 'STANDARD',     confidence: 0.77, note: 'Agreed.' },
  { weekOf: '2026-04-06', engine: 'DELOAD',       trainer: 'CONSERVATIVE', confidence: 0.66, note: 'Override: HRV recovered Wed, kept tempo.' },
  { weekOf: '2026-03-30', engine: 'STANDARD',     trainer: 'STANDARD',     confidence: 0.83, note: 'Agreed.' },
];

// The reasoning citations driving THIS week's recommendation
const CITATIONS = [
  {
    id: 'hrv-7d',
    metric: 'HRV (RMSSD)',
    finding: '7d mean 49.2ms vs 28d baseline 53.8ms (−8.5%)',
    weight: 0.34,
    source: 'Plews & Laursen, 2017',
    detail: 'Rolling 7d HRV >1 SD below 28d baseline indicates incomplete parasympathetic recovery.',
  },
  {
    id: 'acwr',
    metric: 'ACWR (acute:chronic)',
    finding: 'Trailing 7:28 ratio 1.31, trending up',
    weight: 0.28,
    source: 'Gabbett, 2016',
    detail: 'Ratio >1.50 elevates injury risk 4–5×. Current trajectory crosses threshold within 5 days if load held.',
  },
  {
    id: 'rhr-7d',
    metric: 'Resting HR',
    finding: '7d mean 54.3 bpm vs 28d baseline 52.1 bpm (+2.2 bpm)',
    weight: 0.18,
    source: 'Buchheit, 2014',
    detail: '>2 bpm sustained elevation alongside HRV suppression is a confirmed-recovery-debt pattern.',
  },
  {
    id: 'sleep',
    metric: 'Sleep score',
    finding: '7d mean 76 vs 28d baseline 79, 2 nights <70',
    weight: 0.12,
    source: 'ACSM 11e, Ch. 7',
    detail: 'Sleep score variability with low-quality nights compounds autonomic recovery deficit.',
  },
  {
    id: 'rpe-trend',
    metric: 'Session RPE trend',
    finding: 'Last 3 sessions RPE ≥ planned despite reduced volume',
    weight: 0.08,
    source: 'Foster, 1998',
    detail: 'Effort drift at lower volumes signals fatigue accumulation.',
  },
];

const RECOMMENDATION = {
  verdict: 'CONSERVATIVE',
  confidence: 0.68,
  agreement: 0.71, // historical trainer agreement on CONSERVATIVE verdicts
  totalDecisions: 24,
  agreedCount: 17,
  weekOf: 'Week of May 18, 2026',
  summary: 'Hold intensity, reduce volume ~15%. Cap long run at 16mi. Skip tempo if Tue HRV <45ms.',
  rationale: 'Recovery debt is real but recoverable. HRV is climbing back toward baseline; another hard stimulus this week risks pushing ACWR over the injury-risk threshold.',
};

const CLIENT = {
  id: 'maya',
  name: 'Maya Okafor',
  initials: 'MO',
  age: 32,
  sport: 'Marathon',
  goal: 'Sub-3:15 — Chicago, Oct 11',
  program: 'Week 8 of 16 · Build phase',
  device: 'Garmin Forerunner 965',
  joined: 'Aug 2024',
  email: 'maya.okafor@example.com',
};

Object.assign(window, {
  CLIENT,
  ROSTER,
  SERIES,
  SESSIONS,
  ACWR_SERIES,
  LOAD_SERIES,
  HRV_BASE, RHR_BASE, SLEEP_H_BASE, SLEEP_S_BASE, READ_BASE,
  DECISION_HISTORY,
  CITATIONS,
  RECOMMENDATION,
});
