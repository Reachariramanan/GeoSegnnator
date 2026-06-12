import { useEffect, useRef, useCallback } from "react";
import type { Point } from "../api";

export type Marker = { x: number; y: number; kind: "pos" | "neg" };

type Props = {
  imageUrl: string | null;
  boundary: Point[][];
  markers: Marker[];
  onPoint: (x: number, y: number, omit: boolean) => void;
  onImageSize: (w: number, h: number) => void;
};

/**
 * Layered interactive canvas: base image + translucent boundary fill/stroke +
 * seed markers, with zoom (wheel) and pan (space/middle-drag). Image-space
 * coordinates are reported back to the parent so the backend always works in
 * native pixels regardless of viewport zoom.
 */
export default function Canvas({ imageUrl, boundary, markers, onPoint, onImageSize }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const view = useRef({ scale: 1, ox: 0, oy: 0 });
  const drag = useRef<{ on: boolean; sx: number; sy: number; ox: number; oy: number }>({
    on: false, sx: 0, sy: 0, ox: 0, oy: 0,
  });
  const dpr = window.devicePixelRatio || 1;

  // ---- drawing ----
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    const img = imgRef.current;
    if (!canvas || !wrap) return;
    const cw = wrap.clientWidth, ch = wrap.clientHeight;
    canvas.width = cw * dpr; canvas.height = ch * dpr;
    canvas.style.width = cw + "px"; canvas.style.height = ch + "px";
    const ctx = canvas.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cw, ch);
    if (!img) return;

    const { scale, ox, oy } = view.current;
    ctx.save();
    ctx.translate(ox, oy);
    ctx.scale(scale, scale);

    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(img, 0, 0);

    // boundary fill + stroke
    if (boundary.length) {
      const accent = getComputedStyle(document.documentElement).getPropertyValue("--boundary").trim() || "#fff";
      ctx.beginPath();
      for (const poly of boundary) {
        if (poly.length < 2) continue;
        ctx.moveTo(poly[0].x, poly[0].y);
        for (let i = 1; i < poly.length; i++) ctx.lineTo(poly[i].x, poly[i].y);
        ctx.closePath();
      }
      ctx.fillStyle = "rgba(120,170,255,0.20)";
      ctx.fill("evenodd");
      ctx.lineWidth = 1.6 / scale;
      ctx.strokeStyle = accent;
      ctx.shadowColor = "rgba(0,0,0,0.6)";
      ctx.shadowBlur = 3 / scale;
      ctx.stroke();
      ctx.shadowBlur = 0;
    }

    // markers
    const css = getComputedStyle(document.documentElement);
    const posC = css.getPropertyValue("--pos").trim() || "#4ade80";
    const negC = css.getPropertyValue("--neg").trim() || "#fb7185";
    for (const m of markers) {
      const r = 5 / scale;
      ctx.beginPath();
      ctx.arc(m.x, m.y, r, 0, Math.PI * 2);
      ctx.fillStyle = m.kind === "pos" ? posC : negC;
      ctx.fill();
      ctx.lineWidth = 2 / scale;
      ctx.strokeStyle = "rgba(255,255,255,0.85)";
      ctx.stroke();
    }
    ctx.restore();
  }, [boundary, markers, dpr]);

  // ---- fit image to viewport on load ----
  const fit = useCallback(() => {
    const wrap = wrapRef.current, img = imgRef.current;
    if (!wrap || !img) return;
    const cw = wrap.clientWidth, ch = wrap.clientHeight;
    const s = Math.min(cw / img.width, ch / img.height) * 0.92;
    view.current = { scale: s, ox: (cw - img.width * s) / 2, oy: (ch - img.height * s) / 2 };
    draw();
  }, [draw]);

  useEffect(() => {
    if (!imageUrl) { imgRef.current = null; draw(); return; }
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => { imgRef.current = img; onImageSize(img.width, img.height); fit(); };
    img.src = imageUrl;
  }, [imageUrl, fit, onImageSize, draw]);

  useEffect(() => { draw(); }, [draw]);

  useEffect(() => {
    const ro = new ResizeObserver(() => draw());
    if (wrapRef.current) ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, [draw]);

  // ---- coordinate transform: screen -> image px ----
  const toImage = (clientX: number, clientY: number) => {
    const rect = canvasRef.current!.getBoundingClientRect();
    const { scale, ox, oy } = view.current;
    return {
      x: Math.round((clientX - rect.left - ox) / scale),
      y: Math.round((clientY - rect.top - oy) / scale),
    };
  };

  // ---- interactions ----
  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const rect = canvasRef.current!.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const v = view.current;
    const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
    const ns = Math.min(40, Math.max(0.05, v.scale * factor));
    v.ox = mx - (mx - v.ox) * (ns / v.scale);
    v.oy = my - (my - v.oy) * (ns / v.scale);
    v.scale = ns;
    draw();
  };

  const onDown = (e: React.MouseEvent) => {
    // Shift+left-drag also pans (in addition to middle-drag handled separately).
    if (e.button === 0 && e.shiftKey) {
      drag.current = { on: true, sx: e.clientX, sy: e.clientY, ox: view.current.ox, oy: view.current.oy };
      return;
    }
    // left = positive, right (or alt+left) = omission
    if (e.button === 0 && !e.metaKey && !e.ctrlKey) {
      const p = toImage(e.clientX, e.clientY);
      const img = imgRef.current;
      if (img && p.x >= 0 && p.y >= 0 && p.x < img.width && p.y < img.height) {
        onPoint(p.x, p.y, e.altKey);
      }
    }
  };

  const onContext = (e: React.MouseEvent) => {
    e.preventDefault();
    const p = toImage(e.clientX, e.clientY);
    const img = imgRef.current;
    if (img && p.x >= 0 && p.y >= 0 && p.x < img.width && p.y < img.height) {
      onPoint(p.x, p.y, true); // right click = omit
    }
  };

  const onMiddleDown = (e: React.MouseEvent) => {
    if (e.button === 1) {
      e.preventDefault();
      drag.current = { on: true, sx: e.clientX, sy: e.clientY, ox: view.current.ox, oy: view.current.oy };
    }
  };

  useEffect(() => {
    const move = (e: MouseEvent) => {
      if (!drag.current.on) return;
      view.current.ox = drag.current.ox + (e.clientX - drag.current.sx);
      view.current.oy = drag.current.oy + (e.clientY - drag.current.sy);
      draw();
    };
    const up = () => { drag.current.on = false; };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); };
  }, [draw]);

  return (
    <div className="stage-canvas-wrap" ref={wrapRef}>
      {!imageUrl && (
        <div className="empty-hint">
          <h2>Drop an image to begin</h2>
          <p>Drag &amp; drop · paste with <kbd>Ctrl</kbd>+<kbd>V</kbd> · or pick from the gallery</p>
          <p>Left-click to grow · Right-click / Alt-click to omit · Scroll to zoom · Middle-drag to pan</p>
        </div>
      )}
      <canvas
        ref={canvasRef}
        onWheel={onWheel}
        onMouseDown={(e) => { onMiddleDown(e); onDown(e); }}
        onContextMenu={onContext}
        style={{ display: imageUrl ? "block" : "none" }}
      />
    </div>
  );
}
