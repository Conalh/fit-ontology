// Variant A — "Safe" / Notion-y
// Generous whitespace, single content column, small-multiples chart grid,
// citations collapsed behind "Why", override in a top-right drawer button.

const { useState: useStateA } = React;

function VariantSafe() {
  const [showCitations, setShowCitations] = useStateA(false);
  const [showOverride, setShowOverride] = useStateA(false);
  // Per-client accent — read from localStorage with roster default, persist on change
  const activeClientId = 'maya';
  const defaultAccent = window.ROSTER.find(c => c.id === activeClientId).accentHex;
  const [accentHex, setAccentHex] = window.useClientAccent(activeClientId, defaultAccent);

  // Apply the active client's accent as --accent on the root, plus a derived
  // alpha for accent-bg, so all `var(--accent)` references through the page
  // shift in lockstep when the trainer recolors the client.
  const accentVars = {
    '--accent': accentHex,
    '--accent-bg': window.withAlpha(accentHex, 0.10),
  };

  return (
    <div style={{
      ...accentVars,
      display: 'flex',
      width: '100%', minHeight: '100%',
      background: 'var(--surface)',
      color: 'var(--text)',
      fontFamily: 'var(--font-sans)',
      fontSize: 14,
      lineHeight: 1.5,
      position: 'relative',
    }}>
      <Sidebar density="comfortable" activeClientId={activeClientId} accentHex={accentHex} />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <TopBar density="comfortable">
          <button className="btn-ghost">Share</button>
          <button className="btn-ghost">···</button>
          <button className="btn-primary" onClick={() => setShowOverride(s => !s)}>
            Override
          </button>
        </TopBar>

        <ClientHeader
          density="comfortable"
          accentHex={accentHex}
          onAccentChange={setAccentHex}
        />

        <div style={{
          padding: '8px 28px 36px',
          display: 'flex',
          flexDirection: 'column',
          gap: 22,
        }}>
          <RecommendationCardSafe
            showCitations={showCitations}
            onToggle={() => setShowCitations(s => !s)}
          />

          <TrendsGridSafe />

          <SessionsAndHistoryRow />
        </div>
      </div>

      {showOverride && (
        <OverrideDrawer onClose={() => setShowOverride(false)} />
      )}
    </div>
  );
}

function RecommendationCardSafe({ showCitations, onToggle }) {
  const r = window.RECOMMENDATION;
  return (
    <section style={{
      border: '1px solid var(--border)',
      borderRadius: 10,
      background: 'var(--surface)',
      overflow: 'hidden',
    }}>
      {/* Top row: verdict label + summary */}
      <div style={{ padding: '22px 24px 18px', display: 'flex', gap: 28, alignItems: 'flex-start' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: 10.5, color: 'var(--text-muted)',
            textTransform: 'uppercase', letterSpacing: '0.08em',
            fontWeight: 500,
            marginBottom: 8,
          }}>
            {r.weekOf} · Recommendation
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
            <VerdictBadge verdict={r.verdict} size="lg" />
            <span style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>
              Hold intensity, reduce volume
            </span>
          </div>
          <p style={{
            fontSize: 15, color: 'var(--text)', margin: '6px 0 0',
            maxWidth: 560, lineHeight: 1.5,
            letterSpacing: '-0.005em',
          }}>
            {r.rationale}
          </p>
          <div style={{
            marginTop: 14, padding: '10px 12px',
            background: 'var(--surface-2)',
            border: '1px solid var(--border)',
            borderRadius: 6,
            fontSize: 13, color: 'var(--text)',
            display: 'flex', gap: 8,
          }}>
            <svg width="14" height="14" viewBox="0 0 20 20" fill="none"
              stroke="var(--text-muted)" strokeWidth="1.5"
              style={{ flexShrink: 0, marginTop: 2 }}>
              <circle cx="10" cy="10" r="7" />
              <path d="M10 6v4l3 2" strokeLinecap="round" />
            </svg>
            <span style={{ flex: 1 }}>{r.summary}</span>
          </div>
        </div>

        {/* Confidence + agreement */}
        <div style={{
          display: 'flex', gap: 24, alignItems: 'center',
          paddingLeft: 24,
          borderLeft: '1px solid var(--border)',
        }}>
          <div style={{ textAlign: 'center' }}>
            <Donut
              value={r.confidence}
              size={84} stroke={7}
              color="var(--accent)"
              label={`${Math.round(r.confidence * 100)}%`}
              sublabel="conf"
            />
            <div style={{
              fontSize: 11, color: 'var(--text-muted)', marginTop: 8,
              textAlign: 'center', maxWidth: 84, lineHeight: 1.3,
            }}>
              Engine confidence
            </div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <Donut
              value={r.agreement}
              size={84} stroke={7}
              color="var(--text)"
              label={`${Math.round(r.agreement * 100)}%`}
              sublabel="agree"
            />
            <div style={{
              fontSize: 11, color: 'var(--text-muted)', marginTop: 8,
              textAlign: 'center', maxWidth: 90, lineHeight: 1.3,
            }}>
              You agree on Conservative<br/>
              <span style={{ fontVariantNumeric: 'tabular-nums' }}>{r.agreedCount} of {r.totalDecisions}</span> times
            </div>
          </div>
        </div>
      </div>

      {/* Citations toggle */}
      <button
        onClick={onToggle}
        style={{
          width: '100%',
          padding: '11px 24px',
          background: 'var(--surface-2)',
          border: 'none',
          borderTop: '1px solid var(--border)',
          color: 'var(--text-muted)',
          fontSize: 12.5,
          textAlign: 'left',
          display: 'flex', alignItems: 'center', gap: 8,
          cursor: 'pointer',
          fontFamily: 'inherit',
        }}
      >
        <svg width="11" height="11" viewBox="0 0 20 20" fill="none"
          stroke="currentColor" strokeWidth="2"
          style={{ transform: showCitations ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s' }}>
          <polyline points="7,4 13,10 7,16" />
        </svg>
        <span style={{ color: 'var(--text)', fontWeight: 500 }}>Why this recommendation?</span>
        <span>{window.CITATIONS.length} signals · literature-anchored</span>
      </button>

      {showCitations && (
        <div style={{ padding: '4px 24px 22px', borderTop: '1px solid var(--border)' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ fontSize: 10.5, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                <th style={{ textAlign: 'left', padding: '12px 0 8px', fontWeight: 500 }}>Signal</th>
                <th style={{ textAlign: 'left', padding: '12px 0 8px', fontWeight: 500 }}>Finding</th>
                <th style={{ textAlign: 'right', padding: '12px 0 8px', fontWeight: 500, width: 90 }}>Weight</th>
                <th style={{ textAlign: 'right', padding: '12px 0 8px', fontWeight: 500, width: 140 }}>Source</th>
              </tr>
            </thead>
            <tbody>
              {window.CITATIONS.map(c => (
                <tr key={c.id} style={{ borderTop: '1px solid var(--border)' }}>
                  <td style={{ padding: '12px 0', color: 'var(--text)', fontWeight: 500, verticalAlign: 'top', width: 160 }}>
                    {c.metric}
                  </td>
                  <td style={{ padding: '12px 16px 12px 0', color: 'var(--text)', verticalAlign: 'top' }}>
                    <div style={{ fontVariantNumeric: 'tabular-nums' }}>{c.finding}</div>
                    <div style={{ fontSize: 11.5, color: 'var(--text-muted)', marginTop: 3, lineHeight: 1.45 }}>
                      {c.detail}
                    </div>
                  </td>
                  <td style={{ padding: '12px 0', verticalAlign: 'top', textAlign: 'right' }}>
                    <div style={{
                      display: 'inline-flex', alignItems: 'center', gap: 6,
                      fontVariantNumeric: 'tabular-nums', fontSize: 12, color: 'var(--text)',
                    }}>
                      <div style={{
                        width: 38, height: 4, borderRadius: 2,
                        background: 'var(--grid)', overflow: 'hidden',
                      }}>
                        <div style={{
                          width: `${c.weight * 100 / 0.4}%`, height: '100%',
                          background: 'var(--accent)',
                        }} />
                      </div>
                      {Math.round(c.weight * 100)}%
                    </div>
                  </td>
                  <td style={{ padding: '12px 0', verticalAlign: 'top', textAlign: 'right',
                    fontSize: 11.5, color: 'var(--text-muted)' }}>
                    {c.source}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function TrendsGridSafe() {
  const items = [
    { title: 'HRV', sub: 'RMSSD · ms', data: window.SERIES.map(d => ({ day: d.day, value: d.hrv })), base: window.HRV_BASE, unit: 'ms', invert: false },
    { title: 'Resting HR', sub: 'bpm', data: window.SERIES.map(d => ({ day: d.day, value: d.rhr })), base: window.RHR_BASE, unit: ' bpm', invert: true },
    { title: 'Sleep', sub: 'hours', data: window.SERIES.map(d => ({ day: d.day, value: d.sleepHours })), base: window.SLEEP_H_BASE, unit: 'h', invert: false },
    { title: 'Sleep score', sub: '0–100', data: window.SERIES.map(d => ({ day: d.day, value: d.sleepScore })), base: window.SLEEP_S_BASE, unit: '', invert: false },
    { title: 'Readiness', sub: '0–100 composite', data: window.SERIES.map(d => ({ day: d.day, value: d.readiness })), base: window.READ_BASE, unit: '', invert: false },
    { title: 'ACWR', sub: 'acute:chronic', data: window.ACWR_SERIES.map(d => ({ day: d.day, value: d.acwr })), base: { mean: 1, sd: 0.2 }, unit: '', invert: true, threshold: { value: 1.5, label: 'risk' } },
  ];

  return (
    <section>
      <div style={{
        display: 'flex', alignItems: 'baseline',
        justifyContent: 'space-between',
        marginBottom: 12,
      }}>
        <div>
          <h2 style={{
            fontSize: 15, fontWeight: 600, color: 'var(--text)',
            margin: 0, letterSpacing: '-0.01em',
          }}>Trends</h2>
          <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '2px 0 0' }}>
            Daily wearable signals, last 28 days. Shaded band = 28d baseline mean ± 1 SD.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 4, fontSize: 12 }}>
          {['7d', '28d', '8w'].map(w => (
            <button key={w} className={w === '28d' ? 'btn-chip-on' : 'btn-chip'}>
              {w}
            </button>
          ))}
        </div>
      </div>

      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(3, 1fr)',
        gap: 1,
        background: 'var(--border)',
        border: '1px solid var(--border)',
        borderRadius: 10,
        overflow: 'hidden',
      }}>
        {items.map(it => (
          <TrendCellSafe key={it.title} item={it} />
        ))}
      </div>

      {/* Daily load bars under the grid */}
      <div style={{
        marginTop: 14,
        border: '1px solid var(--border)',
        borderRadius: 10,
        padding: '14px 16px 8px',
        background: 'var(--surface)',
      }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>Daily training load</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>RPE × duration. Red = high-stress session.</div>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            7d sum <span style={{ color: 'var(--text)', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>1,365</span> · 28d sum <span style={{ color: 'var(--text)', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>6,733</span>
          </div>
        </div>
        <div style={{ marginTop: 6 }}>
          <LoadBars data={window.LOAD_SERIES} height={80} accent="var(--accent)" />
        </div>
      </div>
    </section>
  );
}

function TrendCellSafe({ item }) {
  const last = item.data[item.data.length - 1].value;
  const last7 = item.data.slice(-7).reduce((a, b) => a + b.value, 0) / 7;
  const delta = last7 - item.base.mean;
  const deltaPct = (delta / item.base.mean) * 100;
  const isBad = item.invert ? delta > 0 : delta < 0;
  const isFlag = Math.abs(delta) > item.base.sd * 0.5;
  return (
    <div style={{
      background: 'var(--surface)',
      padding: '14px 14px 8px',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)', letterSpacing: '-0.005em' }}>
            {item.title}
          </div>
          <div style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>{item.sub}</div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{
            fontSize: 16, fontWeight: 600, color: 'var(--text)',
            fontVariantNumeric: 'tabular-nums',
            letterSpacing: '-0.02em',
            lineHeight: 1,
          }}>
            {last.toFixed(last < 10 ? 1 : 0)}<span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-muted)', marginLeft: 2 }}>{item.unit}</span>
          </div>
          <div style={{
            fontSize: 10.5, marginTop: 3,
            color: isFlag ? (isBad ? 'var(--danger)' : 'var(--ok)') : 'var(--text-muted)',
            fontVariantNumeric: 'tabular-nums',
            fontWeight: 500,
          }}>
            {delta > 0 ? '+' : ''}{deltaPct.toFixed(1)}% vs base
          </div>
        </div>
      </div>
      <div style={{ marginTop: 6, marginLeft: -4, marginRight: -4 }}>
        <TrendChart
          data={item.data}
          baseline={item.base}
          unit={item.unit}
          height={110}
          width={300}
          accent="var(--accent)"
          showAxis={false}
          showLastValue={false}
          threshold={item.threshold}
        />
      </div>
    </div>
  );
}

function SessionsAndHistoryRow() {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 22 }}>
      <SessionsTable />
      <DecisionHistory />
    </div>
  );
}

function SessionsTable() {
  const recent = window.SESSIONS.filter(s => s.day >= -10).reverse();
  return (
    <section style={{
      border: '1px solid var(--border)', borderRadius: 10,
      background: 'var(--surface)', overflow: 'hidden',
    }}>
      <div style={{
        padding: '14px 16px',
        display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
        borderBottom: '1px solid var(--border)',
      }}>
        <div>
          <h3 style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--text)', margin: 0, letterSpacing: '-0.005em' }}>Recent sessions</h3>
          <p style={{ fontSize: 11.5, color: 'var(--text-muted)', margin: '2px 0 0' }}>Last 11 days · {recent.length} entries</p>
        </div>
        <a href="#" style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}>View all 28d →</a>
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
        <thead>
          <tr style={{ fontSize: 10.5, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            <th style={{ textAlign: 'left', padding: '8px 16px', fontWeight: 500 }}>Day</th>
            <th style={{ textAlign: 'left', padding: '8px 0', fontWeight: 500 }}>Session</th>
            <th style={{ textAlign: 'right', padding: '8px 0', fontWeight: 500 }}>Dur</th>
            <th style={{ textAlign: 'right', padding: '8px 0', fontWeight: 500 }}>RPE</th>
            <th style={{ textAlign: 'right', padding: '8px 16px', fontWeight: 500 }}>Load</th>
          </tr>
        </thead>
        <tbody>
          {recent.map(s => (
            <tr key={s.day} style={{ borderTop: '1px solid var(--border)' }}>
              <td style={{ padding: '9px 16px', color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums', width: 60 }}>
                d{s.day}
              </td>
              <td style={{ padding: '9px 0', color: 'var(--text)' }}>
                <div style={{ fontWeight: 500 }}>{s.type}</div>
                {s.notes && (
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 1 }}>{s.notes}</div>
                )}
              </td>
              <td style={{ padding: '9px 0', textAlign: 'right', color: 'var(--text)', fontVariantNumeric: 'tabular-nums' }}>
                {s.duration ? `${s.duration}m` : '—'}
              </td>
              <td style={{ padding: '9px 0', textAlign: 'right', color: 'var(--text)', fontVariantNumeric: 'tabular-nums' }}>
                {s.rpe || '—'}
              </td>
              <td style={{ padding: '9px 16px', textAlign: 'right',
                color: s.load > 800 ? 'var(--danger)' : 'var(--text)',
                fontVariantNumeric: 'tabular-nums', fontWeight: s.load > 800 ? 600 : 400,
              }}>
                {s.load || '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function DecisionHistory() {
  return (
    <section style={{
      border: '1px solid var(--border)', borderRadius: 10,
      background: 'var(--surface)', overflow: 'hidden',
    }}>
      <div style={{
        padding: '14px 16px',
        borderBottom: '1px solid var(--border)',
      }}>
        <h3 style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--text)', margin: 0, letterSpacing: '-0.005em' }}>Decision history</h3>
        <p style={{ fontSize: 11.5, color: 'var(--text-muted)', margin: '2px 0 0' }}>Engine vs. trainer, 8 weeks</p>
      </div>
      <div style={{ padding: '6px 0 8px' }}>
        {window.DECISION_HISTORY.map((h, i) => {
          const isCurrent = i === 0;
          const overrode = h.trainer && h.trainer !== h.engine;
          return (
            <div key={h.weekOf} style={{
              padding: '8px 16px',
              display: 'grid',
              gridTemplateColumns: '70px 1fr auto',
              gap: 10, alignItems: 'center',
              fontSize: 12,
            }}>
              <span style={{
                color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums',
                fontSize: 11.5,
              }}>
                {h.weekOf.slice(5)}
              </span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                <VerdictBadge verdict={h.engine} />
                {h.trainer && (
                  <>
                    <svg width="10" height="10" viewBox="0 0 20 20" fill="none" stroke="var(--text-muted)" strokeWidth="1.5">
                      <line x1="3" y1="10" x2="17" y2="10" />
                      <polyline points="13,6 17,10 13,14" />
                    </svg>
                    <VerdictBadge verdict={h.trainer} />
                  </>
                )}
                {overrode && (
                  <span style={{
                    fontSize: 9.5, color: 'var(--text-muted)',
                    background: 'var(--surface-2)', border: '1px solid var(--border)',
                    padding: '1px 5px', borderRadius: 3,
                    textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 500,
                  }}>override</span>
                )}
                {isCurrent && (
                  <span style={{
                    fontSize: 9.5, color: 'var(--warn)',
                    background: 'var(--warn-bg)',
                    padding: '1px 5px', borderRadius: 3,
                    textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600,
                  }}>now</span>
                )}
              </div>
              <span style={{ color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums', fontSize: 11.5 }}>
                {Math.round(h.confidence * 100)}%
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function OverrideDrawer({ onClose }) {
  const [verdict, setVerdict] = useStateA('STANDARD');
  const [reasons, setReasons] = useStateA(new Set());
  const [conf, setConf] = useStateA(70);
  const [rationale, setRationale] = useStateA('');

  const toggleReason = (r) => {
    const next = new Set(reasons);
    next.has(r) ? next.delete(r) : next.add(r);
    setReasons(next);
  };

  const reasonOpts = ['Felt fresh in person', 'Life stress', 'Travel', 'Comp prep', 'Recent illness', 'Equipment limit', 'Trainer judgment'];

  return (
    <div style={{
      position: 'absolute', top: 0, right: 0, bottom: 0,
      width: 380,
      background: 'var(--surface)',
      borderLeft: '1px solid var(--border)',
      display: 'flex', flexDirection: 'column',
      boxShadow: '-6px 0 24px var(--shadow-md)',
      zIndex: 10,
    }}>
      <div style={{
        padding: '16px 20px',
        borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div>
          <div style={{ fontSize: 10.5, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 500 }}>
            This week's call
          </div>
          <h3 style={{ fontSize: 15, fontWeight: 600, color: 'var(--text)', margin: '4px 0 0' }}>Override</h3>
        </div>
        <button onClick={onClose} className="btn-icon">
          <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8">
            <line x1="5" y1="5" x2="15" y2="15" /><line x1="15" y1="5" x2="5" y2="15" />
          </svg>
        </button>
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: 20, display: 'flex', flexDirection: 'column', gap: 18 }}>
        <div>
          <div style={{ fontSize: 11.5, color: 'var(--text-muted)', marginBottom: 4 }}>Engine recommended</div>
          <VerdictBadge verdict="CONSERVATIVE" size="lg" />
        </div>

        <div>
          <label style={{ fontSize: 12, fontWeight: 500, color: 'var(--text)', display: 'block', marginBottom: 8 }}>
            Your call
          </label>
          <div style={{ display: 'flex', gap: 6 }}>
            {['DELOAD', 'CONSERVATIVE', 'STANDARD'].map(v => (
              <button key={v} onClick={() => setVerdict(v)}
                style={{
                  flex: 1, padding: '8px 0',
                  border: verdict === v ? '1px solid var(--accent)' : '1px solid var(--border)',
                  background: verdict === v ? 'var(--accent-bg)' : 'var(--surface)',
                  borderRadius: 6, cursor: 'pointer',
                  fontSize: 11, fontWeight: 600,
                  color: verdict === v ? 'var(--accent)' : 'var(--text-muted)',
                  letterSpacing: '0.04em', textTransform: 'uppercase',
                  fontFamily: 'inherit',
                }}>
                {v}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label style={{ fontSize: 12, fontWeight: 500, color: 'var(--text)', display: 'block', marginBottom: 8 }}>
            Reasons <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>(tagged)</span>
          </label>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
            {reasonOpts.map(r => (
              <button key={r} onClick={() => toggleReason(r)}
                style={{
                  padding: '5px 9px',
                  border: reasons.has(r) ? '1px solid var(--accent)' : '1px solid var(--border)',
                  background: reasons.has(r) ? 'var(--accent-bg)' : 'var(--surface)',
                  color: reasons.has(r) ? 'var(--accent)' : 'var(--text)',
                  borderRadius: 4, cursor: 'pointer',
                  fontSize: 11.5, fontFamily: 'inherit',
                }}>
                {r}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label style={{ fontSize: 12, fontWeight: 500, color: 'var(--text)', display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
            <span>Your confidence</span>
            <span style={{ color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>{conf}%</span>
          </label>
          <input type="range" min="0" max="100" value={conf} onChange={e => setConf(+e.target.value)}
            style={{ width: '100%', accentColor: 'var(--accent)' }} />
        </div>

        <div>
          <label style={{ fontSize: 12, fontWeight: 500, color: 'var(--text)', display: 'block', marginBottom: 8 }}>
            Rationale
          </label>
          <textarea
            value={rationale}
            onChange={e => setRationale(e.target.value)}
            placeholder="e.g. saw her at Tuesday session, gait was solid…"
            style={{
              width: '100%', minHeight: 90,
              padding: '8px 10px',
              background: 'var(--surface-2)',
              border: '1px solid var(--border)',
              borderRadius: 6,
              fontSize: 12.5, fontFamily: 'inherit',
              color: 'var(--text)',
              resize: 'vertical',
              boxSizing: 'border-box',
            }} />
        </div>
      </div>

      <div style={{
        padding: '12px 20px',
        borderTop: '1px solid var(--border)',
        display: 'flex', gap: 8,
      }}>
        <button className="btn-ghost" onClick={onClose} style={{ flex: 1 }}>Cancel</button>
        <button className="btn-primary" style={{ flex: 1 }}>Save call</button>
      </div>
    </div>
  );
}

Object.assign(window, { VariantSafe });
