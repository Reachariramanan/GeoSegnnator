import { imageUrl } from "../api";

type Props = {
  files: string[];
  active: string | null;
  onSelect: (path: string) => void;
};

export default function Gallery({ files, active, onSelect }: Props) {
  return (
    <div>
      {files.length === 0 && (
        <div style={{ fontSize: 12, color: "var(--text-faint)", padding: "8px 2px" }}>
          No images yet. Drop or paste one.
        </div>
      )}
      {files.map((f) => (
        <div
          key={f}
          className={`thumb ${active === f ? "active" : ""}`}
          onClick={() => onSelect(f)}
        >
          <img src={imageUrl(f)} alt="" loading="lazy" />
          <span className="name">{f}</span>
        </div>
      ))}
    </div>
  );
}
