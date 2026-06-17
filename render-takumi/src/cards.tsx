import type { CSSProperties, ReactNode, ReactElement } from "react";
import { SANS, MONO } from "./fonts";

// --- data models ----------------------------------------------------------

export type RussianData = {
  exam: string; // pill, e.g. "ЕГЭ · 2026"
  subject: string; // "Русский язык"
  kind: string; // "обязательный"
  score: number; // 94
  max: number; // 100
  threshold: number; // порог, e.g. 24
  name: string; // "Орлова Дарья"
  school: string; // "Гимназия № 1, 11 «А»"
};

export type SummaryData = {
  exam: string; // "ЕГЭ · 2026 · ИТОГ"
  totalLabel: string; // "Сумма трёх"
  total: number; // 283
  maxTotal: number; // 300
  subjects: { name: string; score: number | string }[];
  name: string; // "Иванова Анна"
};

// --- mock values ----------------------------------------------------------

export const russianMock: RussianData = {
  exam: "ЕГЭ · 2026",
  subject: "Русский язык",
  kind: "обязательный",
  score: 94,
  max: 100,
  threshold: 24,
  name: "Орлова Дарья",
  school: "Гимназия № 1, 11 «А»",
};

export const summaryMock: SummaryData = {
  exam: "ЕГЭ · 2026 · ИТОГ",
  totalLabel: "Сумма трёх",
  total: 283,
  maxTotal: 300,
  subjects: [
    { name: "Математика", score: 98 },
    { name: "Русский язык", score: 94 },
    { name: "Информатика", score: 91 },
  ],
  name: "Иванова Анна",
};

// --- shared bits ----------------------------------------------------------

/** Gradient-clipped text (background-clip:text + transparent fill). */
const gradientText = (gradient: string): CSSProperties => ({
  backgroundImage: gradient,
  backgroundClip: "text",
  WebkitBackgroundClip: "text",
  WebkitTextFillColor: "transparent",
  color: "transparent",
});

function Badge({ children, start }: { children: ReactNode; start?: boolean }) {
  return (
    <span
      style={{
        display: "flex",
        alignItems: "center",
        ...(start ? { alignSelf: "flex-start" } : {}),
        whiteSpace: "nowrap",
        fontSize: 13,
        fontWeight: 600,
        letterSpacing: ".16em",
        padding: "9px 16px",
        borderRadius: 999,
        backgroundColor: "rgba(255,255,255,.08)",
        border: "1px solid rgba(255,255,255,.18)",
        color: "#f5f5fa",
      }}
    >
      {children}
    </span>
  );
}

function Graduate({ name, school }: { name: string; school?: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <span style={{ fontSize: 12, fontWeight: 600, letterSpacing: ".2em", textTransform: "uppercase", color: "#8b8ba8" }}>
        Выпускник
      </span>
      <span style={{ fontSize: 32, fontWeight: 600, marginTop: 6, letterSpacing: "-.01em", color: "#f5f5fa" }}>{name}</span>
      {school ? <span style={{ fontSize: 14, color: "#8b8ba8", marginTop: 4 }}>{school}</span> : null}
    </div>
  );
}

// NB: no border-radius on the root → the exported PNG is a full rectangle
// (square corners), per request. Inner panels keep their own radii.
const cardRoot = (backgroundImage: string, shadow: string): CSSProperties => ({
  position: "relative",
  width: 420,
  height: 820,
  overflow: "hidden",
  display: "flex",
  flexDirection: "column",
  color: "#f5f5fa",
  fontFamily: SANS,
  backgroundImage,
  boxShadow: shadow,
});

const column: CSSProperties = {
  position: "relative",
  width: "100%",
  height: "100%",
  display: "flex",
  flexDirection: "column",
  justifyContent: "space-between",
  padding: "42px 38px",
};

const blob = (s: CSSProperties): CSSProperties => ({ position: "absolute", borderRadius: "50%", ...s });

const pct = (value: number, max: number) => `${Math.max(0, Math.min(100, max > 0 ? (value / max) * 100 : 0))}%`;

// --- 1 · одна дисциплина --------------------------------------------------

export function RussianCard(d: RussianData) {
  return (
    <div style={cardRoot("radial-gradient(120% 90% at 50% 0%,#1a1f3a 0%,#0a0c1a 60%)", "0 40px 80px -28px rgba(10,12,30,.7)")}>
      <div style={blob({ width: 360, height: 360, top: 60, left: -120, backgroundImage: "radial-gradient(circle,rgba(122,92,255,.85) 0%,transparent 70%)", filter: "blur(20px)" })} />
      <div style={blob({ width: 340, height: 340, bottom: 120, right: -110, backgroundImage: "radial-gradient(circle,rgba(0,200,255,.7) 0%,transparent 70%)", filter: "blur(20px)" })} />

      <div style={column}>
        <div style={{ display: "flex", alignItems: "center" }}>
          <Badge>{d.exam}</Badge>
        </div>

        <div
          style={{
            display: "flex",
            flexDirection: "column",
            backdropFilter: "blur(30px) saturate(160%)",
            backgroundColor: "rgba(255,255,255,.06)",
            border: "1px solid rgba(255,255,255,.18)",
            borderRadius: 34,
            boxShadow: "inset 0 1.5px 0 rgba(255,255,255,.22),0 24px 50px -24px rgba(0,0,0,.6)",
            padding: "36px 32px 32px",
          }}
        >
          <span style={{ fontSize: 15, fontWeight: 600, letterSpacing: ".12em", textTransform: "uppercase", color: "#c9c4ff" }}>
            {d.subject}
          </span>
          <span style={{ fontSize: 14, color: "#8b8ba8", marginTop: 2 }}>{d.kind}</span>

          <div style={{ display: "flex", alignItems: "flex-end", gap: 10, margin: "14px 0 6px" }}>
            <span style={{ fontSize: 140, lineHeight: 0.82, fontWeight: 700, letterSpacing: "-.04em", ...gradientText("linear-gradient(180deg,#fff,#bcb6ff)") }}>
              {d.score}
            </span>
            <span style={{ fontSize: 26, fontWeight: 500, color: "#8b8ba8", marginBottom: 22 }}>/{d.max}</span>
          </div>

          <div style={{ display: "flex", height: 8, borderRadius: 999, backgroundColor: "rgba(255,255,255,.1)", overflow: "hidden", marginTop: 8 }}>
            <div style={{ width: pct(d.score, d.max), height: "100%", borderRadius: 999, backgroundImage: "linear-gradient(90deg,#7a5cff,#00c8ff)", boxShadow: "0 0 16px rgba(122,92,255,.8)" }} />
          </div>

          <div style={{ display: "flex", justifyContent: "space-between", fontFamily: MONO, fontSize: 12, color: "#8b8ba8", marginTop: 10 }}>
            <span>порог {d.threshold}</span>
            <span>{d.max}</span>
          </div>
        </div>

        <Graduate name={d.name} school={d.school} />
      </div>
    </div>
  );
}

// --- 2 · сводная по нескольким дисциплинам --------------------------------

function SummaryRow({ subject, score }: { subject: string; score: number | string }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        backdropFilter: "blur(24px)",
        backgroundColor: "rgba(255,255,255,.06)",
        border: "1px solid rgba(255,255,255,.16)",
        borderRadius: 22,
        padding: "18px 22px",
      }}
    >
      <span style={{ fontSize: 17, fontWeight: 500, color: "#f5f5fa" }}>{subject}</span>
      <span style={{ fontFamily: MONO, fontSize: 30, fontWeight: 700, color: "#f5f5fa" }}>{score}</span>
    </div>
  );
}

export function SummaryCard(d: SummaryData) {
  return (
    <div style={cardRoot("radial-gradient(120% 90% at 50% 0%,#10233a 0%,#070c14 60%)", "0 40px 80px -28px rgba(7,12,20,.7)")}>
      <div style={blob({ width: 360, height: 360, top: 40, right: -120, backgroundImage: "radial-gradient(circle,rgba(0,180,216,.8) 0%,transparent 70%)", filter: "blur(22px)" })} />
      <div style={blob({ width: 320, height: 320, bottom: 80, left: -110, backgroundImage: "radial-gradient(circle,rgba(79,124,255,.7) 0%,transparent 70%)", filter: "blur(22px)" })} />

      <div style={column}>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <Badge start>{d.exam}</Badge>
          <span style={{ fontSize: 13, color: "#8b8ba8", marginTop: 18, letterSpacing: ".12em", textTransform: "uppercase" }}>
            {d.totalLabel}
          </span>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 10, marginTop: 4 }}>
            <span style={{ fontSize: 104, lineHeight: 0.85, fontWeight: 700, letterSpacing: "-.04em", ...gradientText("linear-gradient(180deg,#fff,#9fe9ff)") }}>
              {d.total}
            </span>
            <span style={{ fontSize: 22, color: "#8b8ba8", marginBottom: 18 }}>/{d.maxTotal}</span>
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {d.subjects.map((s, i) => (
            <SummaryRow key={i} subject={s.name} score={s.score} />
          ))}
        </div>

        <Graduate name={d.name} />
      </div>
    </div>
  );
}

// --- registry -------------------------------------------------------------

export type CardDef<T> = {
  title: string;
  width: number;
  height: number;
  mock: T;
  render: (data: T) => ReactElement;
};

export const CARDS: Record<string, CardDef<any>> = {
  russian: { title: "Русский язык · одна дисциплина", width: 420, height: 820, mock: russianMock, render: (d) => <RussianCard {...d} /> },
  summary: { title: "Сумма трёх · сводная", width: 420, height: 820, mock: summaryMock, render: (d) => <SummaryCard {...d} /> },
};
