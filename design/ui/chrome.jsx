// Shared chrome: left sidebar w/ nav + roster strip, top bar
const { useState: useState_chrome, useEffect: useEffect_chrome, useRef: useRef_chrome } = React;

// ───────────────────────────────────────────────────────────────────────
// Per-client accent persistence + the curated swatch palette
// ───────────────────────────────────────────────────────────────────────

const ACCENT_SWATCHES = [
  '#E11D48', // rose
  '#EA580C', // orange
  '#D97706', // amber
  '#65A30D', // lime
  '#15803D', // green
  '#0D9488', // teal
  '#0891B2', // cyan
  '#0369A1', // sky
  '#4F46E5', // indigo
  '#7C3AED', // violet
  '#C026D3', // fuchsia
  '#475569', // slate
];

function getStoredAccent(clientId, fallback) {
  try {
    return localStorage.getItem(`fitont-accent-${clientId}`) || fallback;
  } catch (e) {
    return fallback;
  }
}

function setStoredAccent(clientId, hex) {
  try { localStorage.setItem(`fitont-accent-${clientId}`, hex); } catch (e) {}
}

// Apply alpha to a #rrggbb hex → returns 8-char hex
function withAlpha(hex, alpha) {
  const a = Math.round(alpha * 255).toString(16).padStart(2, '0');
  return hex + a;
}

// Resolve current accent for any client (from storage or roster default)
function clientAccent(clientId) {
  const c = window.ROSTER.find(r => r.id === clientId);
  return getStoredAccent(clientId, c ? c.accentHex : '#4F46E5');
}

// Hook for the *active* client — read/write with reactive updates
function useClientAccent(clientId, fallback) {
  const [hex, setHex] = useState_chrome(() => getStoredAccent(clientId, fallback));
  const update = (next) => {
    setHex(next);
    setStoredAccent(clientId, next);
  };
  return [hex, update];
}

// ───────────────────────────────────────────────────────────────────────
// Components
// ───────────────────────────────────────────────────────────────────────

function Sidebar({ density = 'comfortable', activeClientId = 'maya', accentHex }) {
  const tight = density === 'compact';
  const navItems = [
    { icon: 'grid', label: 'Roster', count: 8 },
    { icon: 'user', label: 'Client', active: true },
    { icon: 'check', label: 'Calibration', count: 24 },
    { icon: 'chat', label: 'Ask FitOntology' },
  ];
  const tools = [
    { icon: 'inbox', label: 'Inbox', count: 3 },
    { icon: 'cal', label: 'This week' },
  ];

  return (
    <aside style={{
      width: tight ? 220 : 240,
      flexShrink: 0,
      borderRight: '1px solid var(--border)',
      background: 'var(--surface-2)',
      display: 'flex',
      flexDirection: 'column',
      fontSize: 13.5,
    }}>
      {/* Logo */}
      <div style={{
        padding: tight ? '14px 16px' : '18px 18px 14px',
        display: 'flex', alignItems: 'center', gap: 10,
        borderBottom: '1px solid var(--border)',
      }}>
        <div style={{
          width: 22, height: 22, borderRadius: 6,
          background: 'var(--text)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: 'var(--surface)', fontSize: 11, fontWeight: 700,
          fontFamily: 'var(--font-mono)',
          letterSpacing: '-0.04em',
        }}>
          F
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.15 }}>
          <span style={{ fontWeight: 600, color: 'var(--text)', letterSpacing: '-0.01em' }}>FitOntology</span>
          <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>v0.4 · 8 clients</span>
        </div>
      </div>

      {/* Nav */}
      <nav style={{ padding: tight ? '8px 8px' : '12px 10px', display: 'flex', flexDirection: 'column', gap: 1 }}>
        {navItems.map(n => (
          <a key={n.label} href="#" style={{
            display: 'flex', alignItems: 'center', gap: 9,
            padding: tight ? '5px 8px' : '6px 9px',
            borderRadius: 6,
            color: n.active ? 'var(--text)' : 'var(--text-muted)',
            background: n.active ? 'var(--surface)' : 'transparent',
            border: n.active ? '1px solid var(--border)' : '1px solid transparent',
            boxShadow: n.active ? '0 1px 0 var(--shadow-sm)' : 'none',
            textDecoration: 'none', fontSize: 13,
            fontWeight: n.active ? 500 : 400,
          }}>
            <NavIcon name={n.icon} active={n.active} />
            <span style={{ flex: 1 }}>{n.label}</span>
            {n.count !== undefined && (
              <span style={{
                fontSize: 10.5, color: 'var(--text-muted)',
                fontVariantNumeric: 'tabular-nums',
              }}>{n.count}</span>
            )}
          </a>
        ))}
      </nav>

      {/* Roster strip */}
      <div style={{
        padding: tight ? '4px 8px 6px' : '8px 10px 8px',
        marginTop: 4,
        borderTop: '1px solid var(--border)',
      }}>
        <div style={{
          padding: '8px 8px 6px',
          fontSize: 10, color: 'var(--text-muted)',
          textTransform: 'uppercase', letterSpacing: '0.08em',
          fontWeight: 500,
          display: 'flex', justifyContent: 'space-between',
        }}>
          <span>Roster</span>
          <span>Needs attention</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          {window.ROSTER.map(c => {
            const isActive = c.id === activeClientId;
            // For active client, use the prop accent (reactive). For others,
            // read once from storage / default.
            const cAccent = isActive ? accentHex : clientAccent(c.id);
            return (
              <a key={c.id} href="#" style={{
                display: 'flex', alignItems: 'center', gap: 9,
                padding: tight ? '5px 8px' : '6px 8px',
                borderRadius: 6,
                color: isActive ? 'var(--text)' : 'var(--text-muted)',
                background: isActive ? 'var(--surface)' : 'transparent',
                border: isActive ? '1px solid var(--border)' : '1px solid transparent',
                textDecoration: 'none', fontSize: 12.5,
              }}>
                <div style={{
                  width: 22, height: 22, borderRadius: 5,
                  background: withAlpha(cAccent, isActive ? 0.22 : 0.13),
                  color: cAccent,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 10, fontWeight: 600,
                  fontVariantNumeric: 'tabular-nums',
                  letterSpacing: '-0.02em',
                  flexShrink: 0,
                }}>
                  {c.initials}
                </div>
                <span style={{
                  flex: 1, overflow: 'hidden',
                  textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  fontWeight: isActive ? 500 : 400,
                }}>{c.name}</span>
                <VerdictDot verdict={c.verdict} />
              </a>
            );
          })}
        </div>
      </div>

      {/* Bottom tools */}
      <div style={{ marginTop: 'auto', padding: tight ? '8px 10px 12px' : '10px 10px 14px', borderTop: '1px solid var(--border)' }}>
        {tools.map(t => (
          <a key={t.label} href="#" style={{
            display: 'flex', alignItems: 'center', gap: 9,
            padding: '6px 9px',
            borderRadius: 6,
            color: 'var(--text-muted)',
            textDecoration: 'none', fontSize: 12.5,
          }}>
            <NavIcon name={t.icon} />
            <span style={{ flex: 1 }}>{t.label}</span>
            {t.count !== undefined && (
              <span style={{
                fontSize: 10.5,
                color: 'var(--text-muted)',
                fontVariantNumeric: 'tabular-nums',
                background: 'var(--surface)',
                border: '1px solid var(--border)',
                borderRadius: 4,
                padding: '0 5px',
              }}>{t.count}</span>
            )}
          </a>
        ))}
      </div>
    </aside>
  );
}

function NavIcon({ name, active }) {
  const stroke = active ? 'var(--text)' : 'var(--text-muted)';
  const paths = {
    grid: <><rect x="3" y="3" width="6" height="6" rx="1" /><rect x="11" y="3" width="6" height="6" rx="1" /><rect x="3" y="11" width="6" height="6" rx="1" /><rect x="11" y="11" width="6" height="6" rx="1" /></>,
    user: <><circle cx="10" cy="7" r="3" /><path d="M4 17c0-3.3 2.7-6 6-6s6 2.7 6 6" /></>,
    check: <><polyline points="3,11 8,16 17,5" /></>,
    chat: <><path d="M3 5h14v9H8l-4 3v-3H3z" /></>,
    inbox: <><path d="M3 12V5h14v7" /><path d="M3 12h4l1 2h4l1-2h4v3H3z" /></>,
    cal: <><rect x="3" y="4" width="14" height="13" rx="1" /><line x1="3" y1="8" x2="17" y2="8" /><line x1="7" y1="2" x2="7" y2="5" /><line x1="13" y1="2" x2="13" y2="5" /></>,
  };
  return (
    <svg width="14" height="14" viewBox="0 0 20 20" fill="none"
      stroke={stroke} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      {paths[name]}
    </svg>
  );
}

function VerdictDot({ verdict }) {
  const color = verdict === 'DELOAD' ? 'var(--danger)'
    : verdict === 'CONSERVATIVE' ? 'var(--warn)'
    : 'var(--ok)';
  return (
    <div style={{
      width: 6, height: 6, borderRadius: '50%',
      background: color,
      flexShrink: 0,
    }} />
  );
}

function VerdictBadge({ verdict, size = 'sm' }) {
  const meta = {
    DELOAD: { fg: 'var(--danger)', bg: 'var(--danger-bg)', label: 'Deload' },
    CONSERVATIVE: { fg: 'var(--warn)', bg: 'var(--warn-bg)', label: 'Conservative' },
    STANDARD: { fg: 'var(--ok)', bg: 'var(--ok-bg)', label: 'Standard' },
  }[verdict];
  const padding = size === 'lg' ? '4px 10px' : '2px 7px';
  const fontSize = size === 'lg' ? 12 : 10.5;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      padding, borderRadius: 4,
      background: meta.bg,
      color: meta.fg,
      fontSize, fontWeight: 600,
      letterSpacing: '0.04em',
      textTransform: 'uppercase',
      fontFamily: 'var(--font-mono)',
      lineHeight: 1,
    }}>
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: meta.fg }} />
      {meta.label}
    </span>
  );
}

function TopBar({ density, children }) {
  const tight = density === 'compact';
  return (
    <div style={{
      height: tight ? 44 : 52,
      borderBottom: '1px solid var(--border)',
      display: 'flex', alignItems: 'center',
      padding: tight ? '0 16px' : '0 20px',
      gap: 12,
      background: 'var(--surface)',
      flexShrink: 0,
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6,
        fontSize: 12.5, color: 'var(--text-muted)',
      }}>
        <span>Roster</span>
        <Chevron />
        <span style={{ color: 'var(--text)', fontWeight: 500 }}>Maya Okafor</span>
        <Chevron />
        <span>This week</span>
      </div>
      <div style={{ flex: 1 }} />
      {children}
    </div>
  );
}

function Chevron() {
  return (
    <svg width="10" height="10" viewBox="0 0 20 20" fill="none" stroke="var(--text-muted)" strokeWidth="1.5">
      <polyline points="8,5 13,10 8,15" />
    </svg>
  );
}

function ClientHeader({ density, accentHex, onAccentChange }) {
  const c = window.CLIENT;
  const tight = density === 'compact';
  const [pickerOpen, setPickerOpen] = useState_chrome(false);
  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: 14,
      padding: tight ? '18px 24px 14px' : '24px 28px 18px',
    }}>
      <ClientAvatarButton
        initials={c.initials}
        accentHex={accentHex}
        size={tight ? 44 : 52}
        onClick={() => setPickerOpen(o => !o)}
        active={pickerOpen}
      />
      <div style={{ flex: 1, minWidth: 0, position: 'relative' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <h1 style={{
            fontSize: tight ? 19 : 22,
            fontWeight: 600,
            color: 'var(--text)',
            letterSpacing: '-0.02em',
            margin: 0,
            lineHeight: 1.1,
          }}>{c.name}</h1>
          <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>{c.age} · {c.sport}</span>
          <button
            onClick={() => setPickerOpen(o => !o)}
            aria-label="Change accent color"
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '3px 8px 3px 6px',
              background: pickerOpen ? withAlpha(accentHex, 0.12) : 'transparent',
              border: '1px solid var(--border)',
              borderRadius: 999,
              cursor: 'pointer',
              color: 'var(--text-muted)',
              fontSize: 11,
              fontFamily: 'inherit',
              transition: 'background 0.12s',
            }}
          >
            <span style={{
              display: 'inline-block',
              width: 10, height: 10, borderRadius: '50%',
              background: accentHex,
              boxShadow: `0 0 0 1px ${withAlpha(accentHex, 0.3)}`,
            }} />
            color
          </button>
        </div>
        <div style={{
          marginTop: 6, fontSize: 12.5, color: 'var(--text-muted)',
          display: 'flex', gap: 18, flexWrap: 'wrap',
        }}>
          <span><span style={{ color: 'var(--text)' }}>Goal:</span> {c.goal}</span>
          <span><span style={{ color: 'var(--text)' }}>Program:</span> {c.program}</span>
          <span><span style={{ color: 'var(--text)' }}>Device:</span> {c.device}</span>
        </div>
        {pickerOpen && (
          <AccentPickerPopover
            value={accentHex}
            onChange={(hex) => { onAccentChange(hex); }}
            onClose={() => setPickerOpen(false)}
          />
        )}
      </div>
    </div>
  );
}

function ClientAvatarButton({ initials, accentHex, size = 52, onClick, active }) {
  const [hover, setHover] = useState_chrome(false);
  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      aria-label="Change accent color"
      style={{
        width: size, height: size,
        borderRadius: 10,
        background: accentHex,
        border: 'none',
        padding: 0,
        cursor: 'pointer',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: size > 48 ? 18 : 16, fontWeight: 600,
        color: 'white',
        letterSpacing: '-0.02em',
        flexShrink: 0, position: 'relative',
        outline: (hover || active) ? `2px solid ${withAlpha(accentHex, 0.35)}` : '2px solid transparent',
        outlineOffset: 2,
        transition: 'outline-color 0.12s',
        fontFamily: 'inherit',
      }}
    >
      {initials}
    </button>
  );
}

function AccentPickerPopover({ value, onChange, onClose }) {
  const ref = useRef_chrome(null);
  useEffect_chrome(() => {
    const onDown = (e) => {
      if (ref.current && !ref.current.contains(e.target)) onClose();
    };
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [onClose]);

  return (
    <div
      ref={ref}
      style={{
        position: 'absolute',
        top: 'calc(100% + 8px)',
        left: 0,
        zIndex: 50,
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 10,
        boxShadow: '0 8px 32px var(--shadow-md), 0 2px 6px var(--shadow-sm)',
        padding: '12px 12px 10px',
        width: 224,
      }}
    >
      <div style={{
        fontSize: 10, color: 'var(--text-muted)',
        textTransform: 'uppercase', letterSpacing: '0.08em',
        fontWeight: 500,
        marginBottom: 8,
        display: 'flex', justifyContent: 'space-between',
      }}>
        <span>Client accent</span>
        <span>per-client</span>
      </div>
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(6, 1fr)',
        gap: 6,
      }}>
        {ACCENT_SWATCHES.map(hex => {
          const isSel = hex.toLowerCase() === value.toLowerCase();
          return (
            <button
              key={hex}
              onClick={() => onChange(hex)}
              aria-label={hex}
              style={{
                width: 28, height: 28,
                borderRadius: 6,
                background: hex,
                border: isSel ? '2px solid var(--text)' : '2px solid transparent',
                boxShadow: isSel ? 'none' : `inset 0 0 0 1px ${withAlpha('#000000', 0.08)}`,
                cursor: 'pointer',
                padding: 0,
                outline: 'none',
              }}
            />
          );
        })}
      </div>
      <div style={{
        marginTop: 10, paddingTop: 10,
        borderTop: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        <label style={{ fontSize: 11, color: 'var(--text-muted)' }}>Custom</label>
        <input
          type="text"
          value={value.toUpperCase()}
          onChange={e => {
            const v = e.target.value.trim();
            if (/^#[0-9a-f]{6}$/i.test(v)) onChange(v);
          }}
          style={{
            flex: 1,
            padding: '4px 6px',
            background: 'var(--surface-2)',
            border: '1px solid var(--border)',
            borderRadius: 4,
            fontSize: 11, fontFamily: 'var(--font-mono)',
            color: 'var(--text)',
            letterSpacing: '0.04em',
          }}
        />
        <input
          type="color"
          value={value}
          onChange={e => onChange(e.target.value.toUpperCase())}
          style={{
            width: 24, height: 22,
            border: '1px solid var(--border)',
            borderRadius: 4,
            background: 'var(--surface-2)',
            cursor: 'pointer',
            padding: 0,
          }}
        />
      </div>
    </div>
  );
}

Object.assign(window, {
  Sidebar, TopBar, ClientHeader, VerdictBadge, VerdictDot, NavIcon, Chevron,
  ACCENT_SWATCHES, withAlpha, clientAccent, useClientAccent,
  ClientAvatarButton, AccentPickerPopover,
});
