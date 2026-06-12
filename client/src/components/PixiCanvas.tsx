import { useEffect, useRef, useCallback } from "react";
import { Application, Sprite, Graphics, Container, Texture } from "pixi.js";
import type { Point } from "../api";

export type Marker = { x: number; y: number; kind: "pos" | "neg" };

type Props = {
  imageUrl: string | null;
  boundary: Point[][];
  previewBoundary: Point[][];
  markers: Marker[];
  hoverActive: boolean;
  onPoint: (x: number, y: number, omit: boolean) => void;
  onHover: (x: number, y: number) => void;
  onHoverEnd: () => void;
  onImageSize: (w: number, h: number) => void;
  onImageData?: (data: ImageData | null) => void;
};

/**
 * PixiJS-backed interactive canvas: GPU-composited image + committed-mask
 * polygon + live hover-preview polygon + seed markers, with zoom (wheel) and
 * pan (middle-drag / shift-drag). Image-space coordinates are reported back to
 * the parent so the backend always works in native pixels regardless of zoom.
 */
export default function PixiCanvas({
  imageUrl, boundary, previewBoundary, markers, hoverActive,
  onPoint, onHover, onHoverEnd, onImageSize, onImageData,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const appRef = useRef<Application | null>(null);
  const worldRef = useRef<Container | null>(null);
  const spriteRef = useRef<Sprite | null>(null);
  const boundaryGfxRef = useRef<Graphics | null>(null);
  const previewGfxRef = useRef<Graphics | null>(null);
  const markersGfxRef = useRef<Graphics | null>(null);
  const view = useRef({ scale: 1, ox: 0, oy: 0 });
  const drag = useRef<{ on: boolean; sx: number; sy: number; ox: number; oy: number }>({
    on: false, sx: 0, sy: 0, ox: 0, oy: 0,
  });
  const sizeRef = useRef({ w: 0, h: 0 });
  const ready = useRef(false);

  // ---- init pixi app once ----
  useEffect(() => {
    let cancelled = false;
    const app = new Application();
    const wrap = wrapRef.current!;
    app.init({
      resizeTo: wrap,
      backgroundAlpha: 0,
      antialias: true,
      resolution: window.devicePixelRatio || 1,
      autoDensity: true,
    }).then(() => {
      if (cancelled) { app.destroy(true, { children: true }); return; }
      wrap.appendChild(app.canvas);
      appRef.current = app;

      const world = new Container();
      app.stage.addChild(world);
      worldRef.current = world;

      const sprite = new Sprite();
      world.addChild(sprite);
      spriteRef.current = sprite;

      const boundaryGfx = new Graphics();
      world.addChild(boundaryGfx);
      boundaryGfxRef.current = boundaryGfx;

      const previewGfx = new Graphics();
      world.addChild(previewGfx);
      previewGfxRef.current = previewGfx;

      const markersGfx = new Graphics();
      world.addChild(markersGfx);
      markersGfxRef.current = markersGfx;

      ready.current = true;
      applyView();
      redrawAll();
    });

    return () => {
      cancelled = true;
      ready.current = false;
      const a = appRef.current;
      appRef.current = null;
      if (a) a.destroy(true, { children: true });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- view transform ----
  const applyView = () => {
    const world = worldRef.current;
    if (!world) return;
    const { scale, ox, oy } = view.current;
    world.position.set(ox, oy);
    world.scale.set(scale, scale);
  };

  const fit = useCallback(() => {
    const wrap = wrapRef.current;
    const { w, h } = sizeRef.current;
    if (!wrap || !w || !h) return;
    const cw = wrap.clientWidth, ch = wrap.clientHeight;
    const s = Math.min(cw / w, ch / h) * 0.92;
    view.current = { scale: s, ox: (cw - w * s) / 2, oy: (ch - h * s) / 2 };
    applyView();
  }, []);

  // ---- load image ----
  useEffect(() => {
    if (!imageUrl) {
      if (spriteRef.current) spriteRef.current.texture = Texture.EMPTY;
      sizeRef.current = { w: 0, h: 0 };
      onImageData?.(null);
      return;
    }
    let cancelled = false;
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      if (cancelled) return;
      sizeRef.current = { w: img.width, h: img.height };
      onImageSize(img.width, img.height);

      if (onImageData) {
        try {
          const off = document.createElement("canvas");
          off.width = img.width;
          off.height = img.height;
          const ctx = off.getContext("2d", { willReadFrequently: true });
          if (ctx) {
            ctx.drawImage(img, 0, 0);
            onImageData(ctx.getImageData(0, 0, img.width, img.height));
          } else {
            onImageData(null);
          }
        } catch {
          onImageData(null);
        }
      }

      const tex = Texture.from(img);
      const wait = () => {
        if (!ready.current || !spriteRef.current) { requestAnimationFrame(wait); return; }
        spriteRef.current.texture = tex;
        fit();
        redrawAll();
      };
      wait();
    };
    img.src = imageUrl;
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imageUrl]);

  // ---- draw helpers ----
  const drawPolys = (gfx: Graphics, polys: Point[][], fill: number, fillAlpha: number, stroke: number, strokeWidth: number) => {
    gfx.clear();
    if (!polys.length) return;
    for (const poly of polys) {
      if (poly.length < 2) continue;
      gfx.moveTo(poly[0].x, poly[0].y);
      for (let i = 1; i < poly.length; i++) gfx.lineTo(poly[i].x, poly[i].y);
      gfx.closePath();
    }
    gfx.fill({ color: fill, alpha: fillAlpha });
    const sw = strokeWidth / Math.max(view.current.scale, 1e-6);
    gfx.stroke({ color: stroke, width: sw, alpha: 0.95 });
  };

  const redrawAll = useCallback(() => {
    if (!ready.current) return;
    const css = getComputedStyle(document.documentElement);
    const accentHex = css.getPropertyValue("--boundary").trim() || "#ffffff";
    const posHex = css.getPropertyValue("--pos").trim() || "#4ade80";
    const negHex = css.getPropertyValue("--neg").trim() || "#fb7185";
    const accent = parseInt(accentHex.replace("#", "0x"));
    const posC = parseInt(posHex.replace("#", "0x"));
    const negC = parseInt(negHex.replace("#", "0x"));

    if (boundaryGfxRef.current) {
      drawPolys(boundaryGfxRef.current, boundary, 0x78aaff, 0.20, accent, 1.6);
    }
    if (previewGfxRef.current) {
      drawPolys(previewGfxRef.current, previewBoundary, 0xffd166, 0.16, 0xffd166, 1.4);
    }
    if (markersGfxRef.current) {
      const gfx = markersGfxRef.current;
      gfx.clear();
      const r = 5 / Math.max(view.current.scale, 1e-6);
      const sw = 2 / Math.max(view.current.scale, 1e-6);
      for (const m of markers) {
        gfx.circle(m.x, m.y, r);
        gfx.fill({ color: m.kind === "pos" ? posC : negC });
        gfx.stroke({ color: 0xffffff, width: sw, alpha: 0.85 });
      }
    }
  }, [boundary, previewBoundary, markers]);

  useEffect(() => { redrawAll(); }, [redrawAll]);

  // ---- resize ----
  useEffect(() => {
    const ro = new ResizeObserver(() => { applyView(); });
    if (wrapRef.current) ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, []);

  // ---- coordinate transform: screen -> image px ----
  const toImage = (clientX: number, clientY: number) => {
    const rect = wrapRef.current!.getBoundingClientRect();
    const { scale, ox, oy } = view.current;
    return {
      x: Math.round((clientX - rect.left - ox) / scale),
      y: Math.round((clientY - rect.top - oy) / scale),
    };
  };

  const inBounds = (p: { x: number; y: number }) => {
    const { w, h } = sizeRef.current;
    return w > 0 && h > 0 && p.x >= 0 && p.y >= 0 && p.x < w && p.y < h;
  };

  // ---- interactions ----
  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const rect = wrapRef.current!.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const v = view.current;
    const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
    const ns = Math.min(40, Math.max(0.05, v.scale * factor));
    v.ox = mx - (mx - v.ox) * (ns / v.scale);
    v.oy = my - (my - v.oy) * (ns / v.scale);
    v.scale = ns;
    applyView();
    redrawAll();
  };

  const onDown = (e: React.MouseEvent) => {
    if (e.button === 0 && e.shiftKey) {
      drag.current = { on: true, sx: e.clientX, sy: e.clientY, ox: view.current.ox, oy: view.current.oy };
      return;
    }
    if (e.button === 0 && !e.metaKey && !e.ctrlKey) {
      const p = toImage(e.clientX, e.clientY);
      if (inBounds(p)) onPoint(p.x, p.y, e.altKey);
    }
  };

  const onContext = (e: React.MouseEvent) => {
    e.preventDefault();
    const p = toImage(e.clientX, e.clientY);
    if (inBounds(p)) onPoint(p.x, p.y, true);
  };

  const onMiddleDown = (e: React.MouseEvent) => {
    if (e.button === 1) {
      e.preventDefault();
      drag.current = { on: true, sx: e.clientX, sy: e.clientY, ox: view.current.ox, oy: view.current.oy };
    }
  };

  const onMove = (e: React.MouseEvent) => {
    if (drag.current.on) return;
    if (!hoverActive) return;
    const p = toImage(e.clientX, e.clientY);
    if (inBounds(p)) onHover(p.x, p.y);
    else onHoverEnd();
  };

  const onLeaveWrap = () => { onHoverEnd(); };

  useEffect(() => {
    const move = (e: MouseEvent) => {
      if (!drag.current.on) return;
      view.current.ox = drag.current.ox + (e.clientX - drag.current.sx);
      view.current.oy = drag.current.oy + (e.clientY - drag.current.sy);
      applyView();
      redrawAll();
    };
    const up = () => { drag.current.on = false; };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); };
  }, [redrawAll]);

  return (
    <div className="stage-canvas-wrap" ref={wrapRef}>
      {!imageUrl && (
        <div className="empty-hint">
          <h2>Drop an image to begin</h2>
          <p>Drag &amp; drop · paste with <kbd>Ctrl</kbd>+<kbd>V</kbd> · or pick from the gallery</p>
          <p>Left-click to grow · Right-click / Alt-click to omit · Scroll to zoom · Middle-drag to pan</p>
        </div>
      )}
      <div
        className="pixi-host"
        style={{ display: imageUrl ? "block" : "none", width: "100%", height: "100%" }}
        onWheel={onWheel}
        onMouseDown={(e) => { onMiddleDown(e); onDown(e); }}
        onMouseMove={onMove}
        onMouseLeave={onLeaveWrap}
        onContextMenu={onContext}
      />
    </div>
  );
}
