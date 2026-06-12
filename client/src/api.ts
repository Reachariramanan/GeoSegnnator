export type Point = { x: number; y: number };

export type ParamSpec = {
  name: string;
  type: "int" | "float" | "bool" | "select" | "string";
  default: any;
  min?: number;
  max?: number;
  step?: number;
  options?: string[];
};

export type AlgorithmSpec = {
  key: string;
  name: string;
  family: string;
  incremental: boolean;
  params: ParamSpec[];
};

export type ProcessResult = {
  boundary: Point[][];
  mask_image: string;
  area: number;
  width: number;
  height: number;
  score?: number | null;
};

const base = "/api";

export async function getAlgorithms(): Promise<AlgorithmSpec[]> {
  const r = await fetch(`${base}/algorithms`);
  const d = await r.json();
  return d.algorithms;
}

export async function getFiles(): Promise<string[]> {
  const r = await fetch(`${base}/files`);
  const d = await r.json();
  return d.files;
}

export async function uploadImage(file: File | Blob, name = "paste.png"): Promise<string> {
  const fd = new FormData();
  fd.append("file", file, (file as File).name || name);
  const r = await fetch(`${base}/upload`, { method: "POST", body: fd });
  const d = await r.json();
  return d.path;
}

export type ProcessArgs = {
  image_path: string;
  algorithm: string;
  pos_points: Point[];
  neg_points: Point[];
  params: Record<string, any>;
  prev_mask?: string | null;
  mode: "replace" | "add" | "omit";
};

export async function processImage(args: ProcessArgs): Promise<ProcessResult> {
  const r = await fetch(`${base}/process`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(args),
  });
  if (!r.ok) {
    const e = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(e.detail || "process failed");
  }
  return r.json();
}

export type PreviewResult = {
  boundary: Point[][];
  area: number;
  score?: number | null;
};

export async function previewSegmentation(args: ProcessArgs): Promise<PreviewResult> {
  const r = await fetch(`${base}/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(args),
  });
  if (!r.ok) {
    const e = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(e.detail || "preview failed");
  }
  return r.json();
}

export async function saveAnnotation(args: {
  image_path: string;
  algorithm: string;
  boundary: Point[][];
  mask_image: string | null;
}): Promise<{ saved: string; mask: string | null }> {
  const r = await fetch(`${base}/save`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(args),
  });
  return r.json();
}

export function imageUrl(path: string): string {
  return `/images/${path}`;
}
