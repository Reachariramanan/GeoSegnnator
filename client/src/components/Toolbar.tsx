import type { AlgorithmSpec } from "../api";

export type Mode = "grow" | "omit";

type Props = {
  algorithms: AlgorithmSpec[];
  algorithm: string;
  onAlgorithm: (k: string) => void;
  mode: Mode;
  onMode: (m: Mode) => void;
  onUndo: () => void;
  onReset: () => void;
  onExport: () => void;
  canUndo: boolean;
  canExport: boolean;
  theme: "dark" | "light";
  onToggleTheme: () => void;
  smartHover: boolean;
  onToggleSmartHover: () => void;
  smartHoverAvailable: boolean;
};

export default function Toolbar(p: Props) {
  const families = Array.from(new Set(p.algorithms.map((a) => a.family)));
  return (
    <div className="toolbar glass">
      <select
        className="control"
        style={{ width: 210 }}
        value={p.algorithm}
        onChange={(e) => p.onAlgorithm(e.target.value)}
      >
        {families.map((fam) => (
          <optgroup key={fam} label={fam}>
            {p.algorithms.filter((a) => a.family === fam).map((a) => (
              <option key={a.key} value={a.key}>{a.name}</option>
            ))}
          </optgroup>
        ))}
      </select>

      <div className="divider" />

      <div className="seg">
        <button className={`btn ${p.mode === "grow" ? "active" : ""}`} onClick={() => p.onMode("grow")}>
          <span className="dot pos" /> Grow
        </button>
        <button className={`btn ${p.mode === "omit" ? "active" : ""}`} onClick={() => p.onMode("omit")}>
          <span className="dot neg" /> Omit
        </button>
      </div>

      <div className="divider" />

      <button
        className={`btn ${p.smartHover ? "active" : ""}`}
        onClick={p.onToggleSmartHover}
        disabled={!p.smartHoverAvailable}
        title={
          p.smartHoverAvailable
            ? "Smart Hover: live segmentation preview as you move (toggle)"
            : "Smart Hover is only available for incremental algorithms"
        }
      >
        ◎ Smart Hover
      </button>

      <div className="divider" />

      <button className="btn" onClick={p.onUndo} disabled={!p.canUndo} title="Undo last point">↶ Undo</button>
      <button className="btn" onClick={p.onReset} disabled={!p.canUndo} title="Clear all points">Reset</button>

      <div className="divider" />

      <button className="btn ghost" onClick={p.onExport} disabled={!p.canExport} title="Export as JSON">⇓ Export</button>
      <button className="btn" onClick={p.onToggleTheme} title="Toggle theme">
        {p.theme === "dark" ? "☾" : "☀"}
      </button>
    </div>
  );
}
