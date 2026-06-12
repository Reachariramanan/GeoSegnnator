import type { AlgorithmSpec } from "../api";

type Props = {
  spec: AlgorithmSpec | undefined;
  values: Record<string, any>;
  onChange: (name: string, value: any) => void;
};

export default function ParamsPanel({ spec, values, onChange }: Props) {
  if (!spec) return null;
  return (
    <div>
      <div className="family-group">
        <div className="family-label">{spec.family}</div>
        <div style={{ fontSize: 13, color: "var(--text)", fontWeight: 600, padding: "0 2px 8px" }}>
          {spec.name}
        </div>
        <div style={{ fontSize: 11, color: "var(--text-faint)", padding: "0 2px 10px" }}>
          {spec.incremental
            ? "Incremental — each click adds/removes from the region."
            : "Recomputed from all accumulated points on every click."}
        </div>
      </div>

      {spec.params.length === 0 && (
        <div style={{ fontSize: 12, color: "var(--text-faint)", padding: "4px 2px" }}>
          No tunable parameters.
        </div>
      )}

      {spec.params.map((param) => {
        const v = values[param.name] ?? param.default;
        if (param.type === "bool") {
          return (
            <label className="field" key={param.name} style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <input
                type="checkbox"
                checked={!!v}
                onChange={(e) => onChange(param.name, e.target.checked)}
              />
              <span className="lbl" style={{ margin: 0 }}>{param.name}</span>
            </label>
          );
        }
        if (param.type === "string") {
          return (
            <label className="field" key={param.name}>
              <div className="lbl"><span>{param.name}</span></div>
              <input
                type="text"
                className="control"
                placeholder="e.g. the dog on the left"
                value={v ?? ""}
                onChange={(e) => onChange(param.name, e.target.value)}
              />
            </label>
          );
        }
        if (param.type === "select") {
          return (
            <label className="field" key={param.name}>
              <div className="lbl"><span>{param.name}</span></div>
              <select className="control" value={v} onChange={(e) => onChange(param.name, e.target.value)}>
                {param.options?.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            </label>
          );
        }
        // int / float -> slider + input
        const step = param.step ?? (param.type === "int" ? 1 : 0.01);
        const numVal = typeof v === "number" ? v : param.default;
        const displayVal = param.type === "int" ? numVal : Number(numVal).toFixed(3);
        const handleInputChange = (val: string) => {
          const num = param.type === "int" ? parseInt(val) : parseFloat(val);
          const minVal = param.min ?? -Infinity;
          const maxVal = param.max ?? Infinity;
          if (!isNaN(num) && num >= minVal && num <= maxVal) {
            onChange(param.name, num);
          }
        };
        return (
          <label className="field" key={param.name}>
            <div className="lbl">
              <span>{param.name}</span>
              <input
                type="number"
                min={param.min ?? undefined}
                max={param.max ?? undefined}
                step={step}
                value={displayVal}
                onChange={(e) => handleInputChange(e.target.value)}
                style={{
                  width: 60,
                  padding: "2px 6px",
                  fontSize: 11.5,
                  fontFamily: "var(--mono)",
                  color: "var(--text)",
                  background: "var(--accent-soft)",
                  border: "1px solid var(--glass-border)",
                  borderRadius: 6,
                  outline: "none",
                  cursor: "pointer",
                }}
              />
            </div>
            <input
              type="range"
              min={param.min ?? undefined}
              max={param.max ?? undefined}
              step={step}
              value={numVal}
              onChange={(e) =>
                onChange(param.name, param.type === "int" ? parseInt(e.target.value) : parseFloat(e.target.value))
              }
            />
          </label>
        );
      })}
    </div>
  );
}
