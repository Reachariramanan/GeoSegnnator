type Props = {
  exportJson: boolean;
  exportMask: boolean;
  onJsonChange: (checked: boolean) => void;
  onMaskChange: (checked: boolean) => void;
  onExport: () => void;
  onCancel: () => void;
  hasMask: boolean;
};

export default function ExportDialog(p: Props) {
  const canExport = p.exportJson || p.exportMask;
  return (
    <div style={{
      position: "fixed",
      inset: 0,
      zIndex: 1000,
      display: "grid",
      placeItems: "center",
      background: "rgba(0,0,0,0.45)",
      backdropFilter: "blur(6px)",
    }}>
      <div style={{
        background: "var(--glass)",
        backdropFilter: "blur(var(--blur)) saturate(160%)",
        WebkitBackdropFilter: "blur(var(--blur)) saturate(160%)",
        border: "1px solid var(--glass-border)",
        borderRadius: "var(--radius)",
        padding: 24,
        maxWidth: 320,
        boxShadow: "var(--shadow), var(--inner-hl)",
      }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text)", marginBottom: 16 }}>
          Export Options
        </div>

        <label style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginBottom: 12,
          cursor: "pointer",
        }}>
          <input
            type="checkbox"
            checked={p.exportJson}
            onChange={(e) => p.onJsonChange(e.target.checked)}
            style={{ cursor: "pointer" }}
          />
          <span style={{ fontSize: 13, color: "var(--text)" }}>JSON metadata</span>
        </label>

        {p.hasMask && (
          <label style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            marginBottom: 16,
            cursor: "pointer",
          }}>
            <input
              type="checkbox"
              checked={p.exportMask}
              onChange={(e) => p.onMaskChange(e.target.checked)}
              style={{ cursor: "pointer" }}
            />
            <span style={{ fontSize: 13, color: "var(--text)" }}>Mask image (PNG)</span>
          </label>
        )}

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button
            onClick={p.onCancel}
            style={{
              padding: "8px 14px",
              fontSize: 12,
              fontWeight: 540,
              color: "var(--text-dim)",
              background: "transparent",
              border: "1px solid var(--glass-border-strong)",
              borderRadius: 8,
              cursor: "pointer",
              transition: "all 0.18s var(--ease)",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = "var(--text)";
              e.currentTarget.style.background = "var(--accent-soft)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = "var(--text-dim)";
              e.currentTarget.style.background = "transparent";
            }}
          >
            Cancel
          </button>
          <button
            onClick={p.onExport}
            disabled={!canExport}
            style={{
              padding: "8px 14px",
              fontSize: 12,
              fontWeight: 540,
              color: canExport ? "var(--bg-0)" : "var(--text-dim)",
              background: canExport ? "var(--accent)" : "transparent",
              border: "1px solid transparent",
              borderRadius: 8,
              cursor: canExport ? "pointer" : "not-allowed",
              opacity: canExport ? 1 : 0.4,
              transition: "all 0.18s var(--ease)",
            }}
            onMouseEnter={(e) => {
              if (canExport) {
                e.currentTarget.style.boxShadow = "0 4px 14px -4px rgba(0,0,0,.5)";
              }
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.boxShadow = "none";
            }}
          >
            ⇓ Export
          </button>
        </div>
      </div>
    </div>
  );
}
