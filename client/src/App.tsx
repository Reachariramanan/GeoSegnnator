import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getAlgorithms, getFiles, uploadImage, processImage, previewSegmentation, imageUrl,
  type AlgorithmSpec, type Point, type ProcessResult,
} from "./api";
import { floodFillFromSeed, combineMasks, maskToPolygons } from "./lib/clientSegmentation";
import PixiCanvas, { type Marker } from "./components/PixiCanvas";
import Toolbar, { type Mode } from "./components/Toolbar";
import ParamsPanel from "./components/ParamsPanel";
import ExportDialog from "./components/ExportDialog";
import Gallery from "./components/Gallery";

type Theme = "dark" | "light";

const CLIENT_ALGO_KEY = "client_region_growing";
const CLIENT_ALGO_SPEC: AlgorithmSpec = {
  key: CLIENT_ALGO_KEY,
  name: "Auto Region Growing (Client)",
  family: "Classic interactive",
  incremental: true,
  params: [
    { name: "tolerance", type: "float", default: 25, min: 1, max: 100, step: 1 },
    { name: "simplify", type: "float", default: 1.0, min: 0, max: 5, step: 0.1 },
  ],
};

export default function App() {
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem("theme") as Theme) || "dark"
  );
  const [algorithms, setAlgorithms] = useState<AlgorithmSpec[]>([]);
  const [algorithm, setAlgorithm] = useState<string>("region_growing");
  const [params, setParams] = useState<Record<string, any>>({});
  const [files, setFiles] = useState<string[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("grow");

  const [posPoints, setPosPoints] = useState<Point[]>([]);
  const [negPoints, setNegPoints] = useState<Point[]>([]);
  // history of every click in order, so Undo/Reset can replay correctly
  const [history, setHistory] = useState<{ x: number; y: number; omit: boolean }[]>([]);

  const [boundary, setBoundary] = useState<Point[][]>([]);
  const [maskImage, setMaskImage] = useState<string | null>(null);
  const [area, setArea] = useState(0);
  const [score, setScore] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  const [smartHover, setSmartHover] = useState(false);
  const [previewBoundary, setPreviewBoundary] = useState<Point[][]>([]);
  const [previewArea, setPreviewArea] = useState<number | null>(null);

  const [showExportDialog, setShowExportDialog] = useState(false);
  const [exportJson, setExportJson] = useState(true);
  const [exportMask, setExportMask] = useState(true);

  // ---- client-side segmentation state ----
  const imageDataRef = useRef<ImageData | null>(null);
  const clientMask = useRef<Uint8Array | null>(null);

  const spec = useMemo(() => algorithms.find((a) => a.key === algorithm), [algorithms, algorithm]);

  // ---- theme ----
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);

  // ---- load registry + files ----
  const refreshFiles = useCallback(() => { getFiles().then(setFiles).catch(() => {}); }, []);
  useEffect(() => {
    getAlgorithms().then((a) => {
      const merged = [...a, CLIENT_ALGO_SPEC];
      setAlgorithms(merged);
      if (merged.length && !merged.find((x) => x.key === algorithm)) setAlgorithm(merged[0].key);
    }).catch(() => setToast("Backend not reachable on :8000"));
    refreshFiles();
  }, []); // eslint-disable-line

  // ---- default params when algorithm changes ----
  useEffect(() => {
    if (!spec) return;
    const def: Record<string, any> = {};
    spec.params.forEach((p) => (def[p.name] = p.default));
    setParams(def);
    if (!spec.incremental) setSmartHover(false);
  }, [spec]);

  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(null), 2200); };

  // ---- the core process call ----
  const lastMask = useRef<string | null>(null);
  const run = useCallback(
    async (pos: Point[], neg: Point[], mode: "replace" | "add" | "omit", prevMask: string | null) => {
      if (!active) return;
      setBusy(true);
      try {
        const res: ProcessResult = await processImage({
          image_path: active, algorithm, pos_points: pos, neg_points: neg,
          params, prev_mask: prevMask, mode,
        });
        setBoundary(res.boundary);
        setMaskImage(res.mask_image);
        lastMask.current = res.mask_image;
        setArea(res.area);
        setScore(res.score ?? null);
      } catch (e: any) {
        flash(e.message || "process failed");
      } finally {
        setBusy(false);
      }
    },
    [active, algorithm, params]
  );

  // ---- client-side (in-browser) region growing ----
  const runClient = useCallback(
    (x: number, y: number, omit: boolean) => {
      const img = imageDataRef.current;
      if (!img) return;
      const tolerance = Number(params.tolerance ?? 25);
      const simplify = Number(params.simplify ?? 1.0);
      const grown = floodFillFromSeed(img, { x, y }, tolerance);
      const next = combineMasks(clientMask.current, grown, omit ? "omit" : "add");
      clientMask.current = next;
      const polys = maskToPolygons(next, img.width, img.height, simplify);
      setBoundary(polys);
      setMaskImage(null);
      let area = 0;
      for (let i = 0; i < next.length; i++) area += next[i];
      setArea(area);
      setScore(null);
    },
    [params]
  );

  // Re-run from full history (used for non-incremental algos, undo, param changes).
  const rerunFromHistory = useCallback(
    (hist: { x: number; y: number; omit: boolean }[]) => {
      const pos = hist.filter((h) => !h.omit).map((h) => ({ x: h.x, y: h.y }));
      const neg = hist.filter((h) => h.omit).map((h) => ({ x: h.x, y: h.y }));
      setPosPoints(pos); setNegPoints(neg);
      if (!pos.length && !neg.length) {
        setBoundary([]); setMaskImage(null); lastMask.current = null; setArea(0); setScore(null);
        clientMask.current = null;
        return;
      }
      if (algorithm === CLIENT_ALGO_KEY) {
        // replay each click against a fresh mask (in-order grow/omit)
        clientMask.current = null;
        for (const h of hist) runClient(h.x, h.y, h.omit);
        return;
      }
      run(pos, neg, "replace", null);
    },
    [run, runClient, algorithm]
  );

  // ---- a click on the canvas ----
  const onPoint = useCallback(
    (x: number, y: number, altOmit: boolean) => {
      const omit = mode === "omit" || altOmit;
      const newHist = [...history, { x, y, omit }];
      setHistory(newHist);
      const pos = newHist.filter((h) => !h.omit).map((h) => ({ x: h.x, y: h.y }));
      const neg = newHist.filter((h) => h.omit).map((h) => ({ x: h.x, y: h.y }));
      setPosPoints(pos); setNegPoints(neg);

      // commit the hover preview, if any
      hoverSeq.current++;
      window.clearTimeout(hoverTimer.current);
      setPreviewBoundary([]); setPreviewArea(null);

      if (algorithm === CLIENT_ALGO_KEY) {
        runClient(x, y, omit);
        return;
      }

      const incremental = spec?.incremental;
      if (incremental) {
        // grow/shrink just this click on top of the existing mask
        if (omit) run([], [{ x, y }], "omit", lastMask.current);
        else run([{ x, y }], [], "add", lastMask.current);
      } else {
        // recompute from full marker set
        run(pos, neg, "replace", null);
      }
    },
    [history, mode, spec, run, algorithm, runClient]
  );

  const onUndo = () => {
    const h = history.slice(0, -1);
    setHistory(h);
    rerunFromHistory(h); // simplest correct path: replay
  };
  const onReset = () => {
    setHistory([]); setPosPoints([]); setNegPoints([]);
    setBoundary([]); setMaskImage(null); lastMask.current = null; setArea(0); setScore(null);
    clientMask.current = null;
    setPreviewBoundary([]); setPreviewArea(null);
  };

  // ---- smart hover: live segmentation preview as the cursor moves ----
  const hoverTimer = useRef<number | undefined>(undefined);
  const hoverSeq = useRef(0);
  const onHover = useCallback(
    (x: number, y: number) => {
      if (!active || !spec?.incremental) return;
      const seq = ++hoverSeq.current;
      window.clearTimeout(hoverTimer.current);

      if (algorithm === CLIENT_ALGO_KEY) {
        hoverTimer.current = window.setTimeout(() => {
          if (seq !== hoverSeq.current) return;
          const img = imageDataRef.current;
          if (!img) return;
          const omit = mode === "omit";
          const tolerance = Number(params.tolerance ?? 25);
          const simplify = Number(params.simplify ?? 1.0);
          const grown = floodFillFromSeed(img, { x, y }, tolerance);
          const next = combineMasks(clientMask.current, grown, omit ? "omit" : "add");
          const polys = maskToPolygons(next, img.width, img.height, simplify);
          let area = 0;
          for (let i = 0; i < next.length; i++) area += next[i];
          setPreviewBoundary(polys);
          setPreviewArea(area);
        }, 60);
        return;
      }

      hoverTimer.current = window.setTimeout(async () => {
        try {
          const omit = mode === "omit";
          const res = await previewSegmentation({
            image_path: active, algorithm,
            pos_points: omit ? [] : [{ x, y }],
            neg_points: omit ? [{ x, y }] : [],
            params, prev_mask: lastMask.current, mode: omit ? "omit" : "add",
          });
          if (seq !== hoverSeq.current) return; // stale response
          setPreviewBoundary(res.boundary);
          setPreviewArea(res.area);
        } catch {
          // ignore preview errors (e.g. cursor left a valid region momentarily)
        }
      }, 60);
    },
    [active, algorithm, params, mode, spec]
  );

  const onHoverEnd = useCallback(() => {
    hoverSeq.current++;
    window.clearTimeout(hoverTimer.current);
    setPreviewBoundary([]);
    setPreviewArea(null);
  }, []);

  // re-run when params change (debounced) if we have points
  const paramTimer = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (!active) return;
    const textPrompt = (params.text_prompt ?? "").trim();
    if (!history.length && !textPrompt) return;
    window.clearTimeout(paramTimer.current);
    paramTimer.current = window.setTimeout(() => {
      if (!history.length && textPrompt) {
        run([], [], "replace", null);
      } else {
        rerunFromHistory(history);
      }
    }, 220);
    return () => window.clearTimeout(paramTimer.current);
  }, [params]); // eslint-disable-line

  // ---- selecting an image resets the session ----
  const selectImage = (path: string) => {
    setActive(path);
    setHistory([]); setPosPoints([]); setNegPoints([]);
    setBoundary([]); setMaskImage(null); lastMask.current = null; setArea(0); setScore(null);
    clientMask.current = null;
    setPreviewBoundary([]); setPreviewArea(null);
  };

  // ---- upload helpers (drop / paste) ----
  const handleFiles = useCallback(async (fl: FileList | File[]) => {
    const imgs = Array.from(fl).filter((f) => f.type.startsWith("image/"));
    if (!imgs.length) return;
    let lastPath = "";
    for (const f of imgs) lastPath = await uploadImage(f);
    refreshFiles();
    if (lastPath) selectImage(lastPath);
    flash(`Loaded ${imgs.length} image${imgs.length > 1 ? "s" : ""}`);
  }, [refreshFiles]);

  // ---- drag & drop ----
  useEffect(() => {
    const over = (e: DragEvent) => { e.preventDefault(); setDragging(true); };
    const leave = (e: DragEvent) => { if (e.relatedTarget === null) setDragging(false); };
    const drop = (e: DragEvent) => {
      e.preventDefault(); setDragging(false);
      if (e.dataTransfer?.files?.length) handleFiles(e.dataTransfer.files);
    };
    window.addEventListener("dragover", over);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragover", over);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
    };
  }, [handleFiles]);

  // ---- paste (Ctrl+V) ----
  useEffect(() => {
    const paste = (e: ClipboardEvent) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      const blobs: File[] = [];
      for (const it of items) {
        if (it.type.startsWith("image/")) {
          const b = it.getAsFile();
          if (b) blobs.push(b);
        }
      }
      if (blobs.length) { e.preventDefault(); handleFiles(blobs); }
    };
    window.addEventListener("paste", paste);
    return () => window.removeEventListener("paste", paste);
  }, [handleFiles]);

  // ---- export with dialog ----
  const doExport = useCallback(() => {
    if (!active || !boundary.length) { flash("Nothing to export yet"); return; }
    setShowExportDialog(true);
  }, [active, boundary]);

  const performExport = useCallback(() => {
    if (!active || !boundary.length) return;
    const timestamp = Date.now();

    if (exportJson) {
      const data = {
        image: active,
        algorithm,
        timestamp: new Date().toISOString(),
        points: { pos: posPoints, neg: negPoints },
        boundary,
        area,
        score: score ?? null,
      };
      const json = JSON.stringify(data, null, 2);
      const blob = new Blob([json], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `annotation_${timestamp}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }

    if (exportMask && maskImage) {
      const a = document.createElement("a");
      a.href = maskImage;
      a.download = `mask_${timestamp}.png`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    }

    setShowExportDialog(false);
    flash("Exported successfully");
  }, [active, boundary, algorithm, posPoints, negPoints, area, score, exportJson, exportMask, maskImage]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); doExport(); }
      if (e.key.toLowerCase() === "z" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); onUndo(); }
      if (e.key === "g") setMode("grow");
      if (e.key === "o") setMode("omit");
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [doExport, history]); // eslint-disable-line

  const markers: Marker[] = [
    ...posPoints.map((p) => ({ ...p, kind: "pos" as const })),
    ...negPoints.map((p) => ({ ...p, kind: "neg" as const })),
  ];

  return (
    <div className="app">
      {/* Left: gallery */}
      <aside className="glass panel">
        <div className="brand">
          <div className="mark">S</div>
          <div>
            <div className="title">Segment</div>
            <div className="sub">RESEARCH ANNOTATOR</div>
          </div>
        </div>
        <div className="panel-head">Gallery</div>
        <div className="panel-body">
          <Gallery files={files} active={active} onSelect={selectImage} />
        </div>
      </aside>

      {/* Center: stage */}
      <main className="glass stage">
        <Toolbar
          algorithms={algorithms}
          algorithm={algorithm}
          onAlgorithm={setAlgorithm}
          mode={mode}
          onMode={setMode}
          onUndo={onUndo}
          onReset={onReset}
          onExport={doExport}
          canUndo={history.length > 0}
          canExport={boundary.length > 0}
          theme={theme}
          onToggleTheme={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
          smartHover={smartHover}
          onToggleSmartHover={() => {
            setSmartHover((s) => !s);
            onHoverEnd();
          }}
          smartHoverAvailable={!!spec?.incremental}
        />
        <PixiCanvas
          imageUrl={active ? imageUrl(active) : null}
          boundary={boundary}
          previewBoundary={smartHover ? previewBoundary : []}
          markers={markers}
          hoverActive={smartHover && !!spec?.incremental}
          onPoint={onPoint}
          onHover={onHover}
          onHoverEnd={onHoverEnd}
          onImageSize={() => {}}
          onImageData={(data) => { imageDataRef.current = data; }}
        />
        <div className="statbar glass">
          {active ? <span>{active}</span> : <span>no image</span>}
          <span>pts <b>{posPoints.length}</b>+ / <b>{negPoints.length}</b>−</span>
          <span>area <b>{area.toLocaleString()}</b> px</span>
          {score !== null && (
            <span>confidence <b>{(score * 100).toFixed(1)}%</b></span>
          )}
          {smartHover && previewArea !== null && (
            <span>preview <b>{previewArea.toLocaleString()}</b> px</span>
          )}
          {busy && <span className="busy"><span className="spin">◠</span> processing</span>}
        </div>
      </main>

      {/* Right: params */}
      <aside className="glass panel">
        <div className="panel-head">Parameters</div>
        <div className="panel-body">
          <ParamsPanel
            spec={spec}
            values={params}
            onChange={(n, v) => setParams((p) => ({ ...p, [n]: v }))}
          />
        </div>
      </aside>

      {dragging && (
        <div className="drop-overlay"><div className="inner">Drop image to load</div></div>
      )}
      {toast && <div className="toast glass">{toast}</div>}
      {showExportDialog && (
        <ExportDialog
          exportJson={exportJson}
          exportMask={exportMask}
          onJsonChange={setExportJson}
          onMaskChange={setExportMask}
          onExport={performExport}
          onCancel={() => setShowExportDialog(false)}
          hasMask={!!maskImage}
        />
      )}
    </div>
  );
}
