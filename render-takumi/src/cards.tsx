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
  totalLabel: "Сумма баллов",
  total: 283,
  maxTotal: 300,
  subjects: [
    { name: "Математика", score: 98 },
    { name: "Русский язык", score: 94 },
    { name: "Информатика", score: 91 },
  ],
  name: "Иванова Анна",
};

// --- liquid-glass primitives ----------------------------------------------
//
// Takumi renders through a real compositor (resvg under the hood), so the glass
// here is genuine: `backdrop-filter` frosts the aurora behind each panel, an
// inline-SVG `feTurbulence` lays down film grain, and layered inset shadows
// paint the specular rim + chromatic edge dispersion that read as "liquid glass".

type Blend = "soft-light" | "overlay" | "screen" | "normal";

/** Procedural film grain. An inline <svg> with feTurbulence → resvg rasterises it,
 *  then mix-blend-mode fuses it with whatever is painted behind. viewBox matches the
 *  box in px so grain cells stay square at any panel size. */
function Grain({ w, h, opacity, blend = "soft-light", freq = 0.9, seed = 7 }: {
  w: number; h: number; opacity: number; blend?: Blend; freq?: number; seed?: number;
}) {
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      style={{ position: "absolute", top: 0, left: 0, width: "100%", height: "100%", opacity, mixBlendMode: blend }}
    >
      <filter id="grain" colorInterpolationFilters="sRGB">
        <feTurbulence type="fractalNoise" baseFrequency={freq} numOctaves={2} seed={seed} stitchTiles="stitch" result="n" />
        <feColorMatrix in="n" type="saturate" values="0" />
      </filter>
      <rect x="0" y="0" width="100%" height="100%" filter="url(#grain)" />
    </svg>
  );
}

/** Diagonal specular streak — the catch of light sliding across a glass surface. */
function Sheen({ w = "82%", h = "62%", top = -34, left = -28, rot = -11, op = 0.34 }: {
  w?: number | string; h?: number | string; top?: number; left?: number; rot?: number; op?: number;
}) {
  return (
    <div
      style={{
        position: "absolute",
        top,
        left,
        width: w,
        height: h,
        backgroundImage: "linear-gradient(118deg,rgba(255,255,255,.5) 0%,rgba(255,255,255,.08) 34%,rgba(255,255,255,0) 62%)",
        transform: `rotate(${rot}deg)`,
        filter: "blur(11px)",
        opacity: op,
      }}
    />
  );
}

/** The glass material: frosted backdrop + sheen gradient + specular rim with a
 *  cool/warm chromatic edge + layered depth shadows. */
function glass(radius: number, o: { tint?: string; blur?: number; lift?: number } = {}): CSSProperties {
  const tint = o.tint ?? "rgba(255,255,255,.035)";
  const blur = o.blur ?? 30;
  const lift = o.lift ?? 1;
  return {
    position: "relative",
    overflow: "hidden",
    borderRadius: radius,
    backgroundColor: tint,
    backgroundImage:
      "linear-gradient(146deg,rgba(255,255,255,.13) 0%,rgba(255,255,255,.04) 26%,rgba(255,255,255,0) 54%,rgba(255,255,255,.02) 100%)",
    // No brightening — keep the glass at or below the backdrop so it reads as
    // see-through, not a milky slab. A touch of saturate gives the frost life.
    backdropFilter: `blur(${blur}px) saturate(112%)`,
    border: "1px solid rgba(255,255,255,.12)",
    boxShadow: [
      "inset 0 1.2px 0 rgba(255,255,255,.4)", // crisp top specular (the lit edge)
      "inset 0 1px 6px rgba(255,255,255,.05)", // soft inner top glow
      "inset 1.5px 0 0 rgba(150,200,255,.11)", // cool left edge (refraction)
      "inset -1.5px 0 0 rgba(255,150,210,.09)", // warm right edge (refraction)
      "inset 0 -1px 0 rgba(255,255,255,.04)", // faint bottom rim
      `0 ${22 * lift}px ${48 * lift}px -${18 * lift}px rgba(4,4,16,.72)`, // ambient
      `0 ${6 * lift}px ${16 * lift}px -${8 * lift}px rgba(4,4,16,.55)`, // contact
    ].join(","),
  };
}

const blob = (s: CSSProperties): CSSProperties => ({ position: "absolute", borderRadius: "50%", ...s });

/** Gradient-clipped text (background-clip:text + transparent fill). */
const gradientText = (gradient: string): CSSProperties => ({
  backgroundImage: gradient,
  backgroundClip: "text",
  WebkitBackgroundClip: "text",
  WebkitTextFillColor: "transparent",
  color: "transparent",
});

const pct = (value: number, max: number) => `${Math.max(0, Math.min(100, max > 0 ? (value / max) * 100 : 0))}%`;

function Badge({ children, start }: { children: ReactNode; start?: boolean }) {
  return (
    <span
      style={{
        ...glass(999, { blur: 16, lift: 0.45 }),
        display: "flex",
        alignItems: "center",
        ...(start ? { alignSelf: "flex-start" } : {}),
        whiteSpace: "nowrap",
        fontSize: 12.5,
        fontWeight: 600,
        letterSpacing: ".18em",
        padding: "9px 17px",
        color: "#f3f1ff",
      }}
    >
      {children}
    </span>
  );
}

function Graduate({ name, school }: { name: string; school?: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <span style={{ fontSize: 11.5, fontWeight: 600, letterSpacing: ".26em", textTransform: "uppercase", color: "#9b96c4" }}>
        Выпускник
      </span>
      <span style={{ fontSize: 31, fontWeight: 600, marginTop: 7, letterSpacing: "-.01em", color: "#f6f5ff" }}>{name}</span>
      {school ? <span style={{ fontSize: 13.5, color: "#8d88b4", marginTop: 5 }}>{school}</span> : null}
    </div>
  );
}

// NB: no border-radius on the root → the exported PNG is a full rectangle
// (square corners), per request. Inner panels keep their own radii.
const cardRoot = (backgroundImage: string): CSSProperties => ({
  position: "relative",
  width: 420,
  height: 820,
  overflow: "hidden",
  display: "flex",
  color: "#f6f5ff",
  fontFamily: SANS,
  backgroundImage,
  boxShadow: "0 40px 80px -28px rgba(6,6,18,.7)",
});

const column: CSSProperties = {
  position: "relative",
  width: "100%",
  height: "100%",
  display: "flex",
  flexDirection: "column",
  justifyContent: "space-between",
  padding: "40px 36px",
};

/** Aurora mesh — soft coloured blobs that the glass panels frost. */
function Aurora({ blobs }: { blobs: CSSProperties[] }) {
  return (
    <>
      {blobs.map((b, i) => (
        <div key={i} style={blob(b)} />
      ))}
      {/* depth vignette: darken top & bottom so glass and text seat cleanly */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage:
            "linear-gradient(180deg,rgba(5,5,14,.55) 0%,rgba(5,5,14,.12) 26%,rgba(5,5,14,.12) 66%,rgba(5,5,14,.72) 100%)",
        }}
      />
    </>
  );
}

// --- 1 · одна дисциплина --------------------------------------------------

export function RussianCard(d: RussianData) {
  return (
    <div style={cardRoot("radial-gradient(125% 100% at 50% -8%,#191336 0%,#0c0a1e 50%,#06050d 100%)")}>
      <Aurora
        blobs={[
          { width: 380, height: 380, top: 30, left: -130, backgroundImage: "radial-gradient(circle,rgba(125,90,210,.44) 0%,transparent 70%)", filter: "blur(74px)" },
          { width: 360, height: 360, top: 120, right: -120, backgroundImage: "radial-gradient(circle,rgba(60,150,205,.38) 0%,transparent 70%)", filter: "blur(82px)" },
          { width: 320, height: 320, bottom: 60, left: -100, backgroundImage: "radial-gradient(circle,rgba(170,70,120,.28) 0%,transparent 70%)", filter: "blur(86px)" },
        ]}
      />

      <div style={column}>
        <Badge>{d.exam}</Badge>

        <div style={{ ...glass(34, { blur: 34, lift: 1.25 }), display: "flex", flexDirection: "column", padding: "34px 32px 30px" }}>
          <Sheen />
          {/* glow behind the hero number */}
          <div style={blob({ width: 300, height: 220, top: 30, left: 8, backgroundImage: "radial-gradient(circle,rgba(160,135,235,.3) 0%,transparent 70%)", filter: "blur(36px)", borderRadius: 0 })} />

          <span style={{ position: "relative", fontSize: 14, fontWeight: 600, letterSpacing: ".14em", textTransform: "uppercase", color: "#cdc6ff" }}>
            {d.subject}
          </span>
          <span style={{ position: "relative", fontSize: 13.5, color: "#8d88b4", marginTop: 3 }}>{d.kind}</span>

          <div style={{ position: "relative", display: "flex", alignItems: "flex-end", gap: 10, margin: "12px 0 6px" }}>
            <span style={{ fontSize: 142, lineHeight: 0.82, fontWeight: 700, letterSpacing: "-.04em", ...gradientText("linear-gradient(180deg,#ffffff,#c7d2fe)") }}>
              {d.score}
            </span>
            <span style={{ fontSize: 26, fontWeight: 500, color: "#8d88b4", marginBottom: 22 }}>/{d.max}</span>
          </div>

          <div style={{ position: "relative", display: "flex", height: 9, borderRadius: 999, backgroundColor: "rgba(255,255,255,.1)", overflow: "hidden", marginTop: 8 }}>
            <div style={{ width: pct(d.score, d.max), height: "100%", borderRadius: 999, backgroundImage: "linear-gradient(90deg,#9b85e0,#3bbfd6)", boxShadow: "0 0 14px rgba(129,120,210,.55)" }} />
          </div>

          <div style={{ position: "relative", display: "flex", justifyContent: "space-between", fontFamily: MONO, fontSize: 12, color: "#8d88b4", marginTop: 11 }}>
            <span>порог {d.threshold}</span>
            <span>{d.max}</span>
          </div>

          <Grain w={356} h={300} opacity={0.42} blend="soft-light" freq={0.9} seed={11} />
        </div>

        <Graduate name={d.name} school={d.school} />
      </div>

      <Grain w={420} h={820} opacity={0.16} blend="overlay" freq={0.95} seed={3} />
    </div>
  );
}

// --- 2 · сводная по нескольким дисциплинам --------------------------------

function SummaryRow({ subject, score, first, fontSize, padY, scoreBump }: {
  subject: string; score: number | string; first: boolean; fontSize: number; padY: number; scoreBump: number;
}) {
  return (
    <div
      style={{
        position: "relative",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: `${first ? 0 : padY}px 0 ${padY}px`,
        ...(first ? {} : { borderTop: "1px solid rgba(255,255,255,.1)" }),
      }}
    >
      <span style={{ fontSize, fontWeight: 500, color: "#ece9ff" }}>{subject}</span>
      <span style={{ fontFamily: MONO, fontSize: fontSize + scoreBump, fontWeight: 700, ...gradientText("linear-gradient(180deg,#ffffff,#a9f3ff)") }}>{score}</span>
    </div>
  );
}

export function SummaryCard(d: SummaryData) {
  const n = d.subjects.length;
  const heroSize = n <= 4 ? 116 : n <= 5 ? 106 : n <= 6 ? 98 : 90;
  const rowFont = n <= 5 ? 17 : n <= 6 ? 16 : 15;
  const scoreBump = n <= 5 ? 11 : 7;
  const rowPadY = n <= 4 ? 14 : n <= 5 ? 12 : n <= 6 ? 10 : 8;
  const listPadY = n <= 5 ? 20 : 14;

  return (
    <div style={cardRoot("radial-gradient(125% 100% at 50% -8%,#0f1626 0%,#080c18 52%,#05060d 100%)")}>
      <Aurora
        blobs={[
          { width: 400, height: 400, top: 10, right: -140, backgroundImage: "radial-gradient(circle,rgba(56,150,205,.42) 0%,transparent 70%)", filter: "blur(74px)" },
          { width: 380, height: 380, top: 140, left: -140, backgroundImage: "radial-gradient(circle,rgba(108,98,200,.42) 0%,transparent 70%)", filter: "blur(80px)" },
          { width: 360, height: 320, top: 400, left: 30, backgroundImage: "radial-gradient(circle,rgba(80,90,180,.3) 0%,transparent 70%)", filter: "blur(86px)" },
          { width: 320, height: 320, bottom: 40, right: -100, backgroundImage: "radial-gradient(circle,rgba(56,160,150,.26) 0%,transparent 70%)", filter: "blur(86px)" },
          { width: 300, height: 300, bottom: 130, left: -90, backgroundImage: "radial-gradient(circle,rgba(170,70,120,.24) 0%,transparent 70%)", filter: "blur(88px)" },
        ]}
      />

      <div style={column}>
        {/* header: pill + hero stat */}
        <div style={{ display: "flex", flexDirection: "column", flexShrink: 0 }}>
          <Badge start>{d.exam}</Badge>

          <div style={{ ...glass(32, { blur: 34, lift: 1.2 }), display: "flex", flexDirection: "column", marginTop: 18, padding: "26px 28px 24px" }}>
            <Sheen />
            <div style={blob({ width: 300, height: 200, top: 6, left: -10, backgroundImage: "radial-gradient(circle,rgba(125,200,240,.28) 0%,transparent 70%)", filter: "blur(38px)", borderRadius: 0 })} />

            <span style={{ position: "relative", fontSize: 12.5, color: "#9fb8d8", letterSpacing: ".18em", textTransform: "uppercase", fontWeight: 600 }}>
              {d.totalLabel}
            </span>
            <div style={{ position: "relative", display: "flex", alignItems: "flex-end", gap: 10, marginTop: 4 }}>
              <span style={{ fontSize: heroSize, lineHeight: 0.84, fontWeight: 700, letterSpacing: "-.04em", ...gradientText("linear-gradient(180deg,#ffffff,#a9e8ff)") }}>
                {d.total}
              </span>
              <span style={{ fontSize: 22, color: "#8aa0c0", marginBottom: heroSize * 0.13 }}>/{d.maxTotal}</span>
            </div>

            <div style={{ position: "relative", display: "flex", height: 9, borderRadius: 999, backgroundColor: "rgba(255,255,255,.1)", overflow: "hidden", marginTop: 16 }}>
              <div style={{ width: pct(d.total, d.maxTotal), height: "100%", borderRadius: 999, backgroundImage: "linear-gradient(90deg,#7c8af0,#3bbfd6)", boxShadow: "0 0 14px rgba(80,150,200,.55)" }} />
            </div>

            <Grain w={348} h={210} opacity={0.4} blend="soft-light" freq={0.9} seed={5} />
          </div>
        </div>

        {/* subjects list — one glass card, hairline-separated rows (scales to many) */}
        <div style={{ ...glass(28, { blur: 26, lift: 0.9 }), flexShrink: 0, display: "flex", flexDirection: "column", padding: `${listPadY}px 24px`, marginTop: 16, marginBottom: 16 }}>
          <Sheen op={0.28} h="50%" />
          {d.subjects.map((s, i) => (
            <SummaryRow key={i} subject={s.name} score={s.score} first={i === 0} fontSize={rowFont} padY={rowPadY} scoreBump={scoreBump} />
          ))}
          <Grain w={372} h={360} opacity={0.36} blend="soft-light" freq={0.92} seed={9} />
        </div>

        <div style={{ flexShrink: 0 }}>
          <Graduate name={d.name} />
        </div>
      </div>

      <Grain w={420} h={820} opacity={0.16} blend="overlay" freq={0.95} seed={3} />
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
  summary: { title: "Сумма баллов · сводная", width: 420, height: 820, mock: summaryMock, render: (d) => <SummaryCard {...d} /> },
};
