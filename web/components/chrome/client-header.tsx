"use client";

import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { ACCENT_SWATCHES, initialsFor, withAlpha } from "@/lib/accent";

export function ClientHeader({
  name,
  goal,
  age,
  sport,
  program,
  device,
  accentHex,
  onAccentChange,
}: {
  name: string;
  goal?: string;
  age?: number;
  sport?: string;
  program?: string;
  device?: string;
  accentHex: string;
  onAccentChange: (hex: string) => void;
}) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const initials = initialsFor(name);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 14,
        padding: "24px 28px 18px",
      }}
    >
      <ClientAvatarButton
        initials={initials}
        accentHex={accentHex}
        size={52}
        onClick={() => setPickerOpen((o) => !o)}
        active={pickerOpen}
      />
      <div style={{ flex: 1, minWidth: 0, position: "relative" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
          <h1
            style={{
              fontSize: 22,
              fontWeight: 600,
              color: "var(--text)",
              letterSpacing: "-0.02em",
              margin: 0,
              lineHeight: 1.1,
            }}
          >
            {name}
          </h1>
          {(age || sport) && (
            <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
              {[age, sport].filter(Boolean).join(" · ")}
            </span>
          )}
          <button
            onClick={() => setPickerOpen((o) => !o)}
            aria-label="Change accent color"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "3px 8px 3px 6px",
              background: pickerOpen ? withAlpha(accentHex, 0.12) : "transparent",
              border: "1px solid var(--border)",
              borderRadius: 999,
              cursor: "pointer",
              color: "var(--text-muted)",
              fontSize: 11,
              fontFamily: "inherit",
              transition: "background 0.12s",
            }}
          >
            <span
              style={{
                display: "inline-block",
                width: 10,
                height: 10,
                borderRadius: "50%",
                background: accentHex,
                boxShadow: `0 0 0 1px ${withAlpha(accentHex, 0.3)}`,
              }}
            />
            color
          </button>
        </div>
        <div
          style={{
            marginTop: 6,
            fontSize: 12.5,
            color: "var(--text-muted)",
            display: "flex",
            gap: 18,
            flexWrap: "wrap",
          }}
        >
          {goal && (
            <span>
              <span style={{ color: "var(--text)" }}>Goal:</span> {goal}
            </span>
          )}
          {program && (
            <span>
              <span style={{ color: "var(--text)" }}>Program:</span> {program}
            </span>
          )}
          {device && (
            <span>
              <span style={{ color: "var(--text)" }}>Device:</span> {device}
            </span>
          )}
        </div>
        {pickerOpen && (
          <AccentPickerPopover value={accentHex} onChange={onAccentChange} onClose={() => setPickerOpen(false)} />
        )}
      </div>
    </div>
  );
}

function ClientAvatarButton({
  initials,
  accentHex,
  size = 52,
  onClick,
  active,
}: {
  initials: string;
  accentHex: string;
  size?: number;
  onClick: () => void;
  active?: boolean;
}) {
  const [hover, setHover] = useState(false);
  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      aria-label="Change accent color"
      style={{
        width: size,
        height: size,
        borderRadius: 10,
        background: accentHex,
        border: "none",
        padding: 0,
        cursor: "pointer",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: size > 48 ? 18 : 16,
        fontWeight: 600,
        color: "white",
        letterSpacing: "-0.02em",
        flexShrink: 0,
        position: "relative",
        outline: hover || active ? `2px solid ${withAlpha(accentHex, 0.35)}` : "2px solid transparent",
        outlineOffset: 2,
        transition: "outline-color 0.12s",
        fontFamily: "inherit",
      } as CSSProperties}
    >
      {initials}
    </button>
  );
}

function AccentPickerPopover({
  value,
  onChange,
  onClose,
}: {
  value: string;
  onChange: (hex: string) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  return (
    <div
      ref={ref}
      style={{
        position: "absolute",
        top: "calc(100% + 8px)",
        left: 0,
        zIndex: 50,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 10,
        boxShadow: "0 8px 32px var(--shadow-md), 0 2px 6px var(--shadow-sm)",
        padding: "12px 12px 10px",
        width: 224,
      }}
    >
      <div
        style={{
          fontSize: 10,
          color: "var(--text-muted)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          fontWeight: 500,
          marginBottom: 8,
          display: "flex",
          justifyContent: "space-between",
        }}
      >
        <span>Client accent</span>
        <span>per-client</span>
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(6, 1fr)",
          gap: 6,
        }}
      >
        {ACCENT_SWATCHES.map((hex) => {
          const isSel = hex.toLowerCase() === value.toLowerCase();
          return (
            <button
              key={hex}
              onClick={() => onChange(hex)}
              aria-label={hex}
              style={{
                width: 28,
                height: 28,
                borderRadius: 6,
                background: hex,
                border: isSel ? "2px solid var(--text)" : "2px solid transparent",
                boxShadow: isSel ? "none" : `inset 0 0 0 1px ${withAlpha("#000000", 0.08)}`,
                cursor: "pointer",
                padding: 0,
                outline: "none",
              }}
            />
          );
        })}
      </div>
      <div
        style={{
          marginTop: 10,
          paddingTop: 10,
          borderTop: "1px solid var(--border)",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <label style={{ fontSize: 11, color: "var(--text-muted)" }}>Custom</label>
        <input
          type="text"
          value={value.toUpperCase()}
          onChange={(e) => {
            const v = e.target.value.trim();
            if (/^#[0-9a-f]{6}$/i.test(v)) onChange(v);
          }}
          style={{
            flex: 1,
            padding: "4px 6px",
            background: "var(--surface-2)",
            border: "1px solid var(--border)",
            borderRadius: 4,
            fontSize: 11,
            fontFamily: "var(--font-mono)",
            color: "var(--text)",
            letterSpacing: "0.04em",
          }}
        />
        <input
          type="color"
          value={value}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
          style={{
            width: 24,
            height: 22,
            border: "1px solid var(--border)",
            borderRadius: 4,
            background: "var(--surface-2)",
            cursor: "pointer",
            padding: 0,
          } as CSSProperties}
        />
      </div>
    </div>
  );
}
