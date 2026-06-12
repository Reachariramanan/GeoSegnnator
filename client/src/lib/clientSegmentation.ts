import type { Point } from "../api";

/**
 * Pure client-side, single-seed region growing + vectorization.
 * Adapted from the automated multi-seed engine in Experiments/researckwork.md,
 * specialized to grow/subtract one region per click (incremental workflow).
 */

const DX4 = [1, -1, 0, 0];
const DY4 = [0, 0, 1, -1];

/** Iterative BFS flood fill from a single seed, growing while the running mean
 * color of the region stays within `colorTolerance` of the candidate pixel. */
export function floodFillFromSeed(
  imageData: ImageData,
  seed: Point,
  colorTolerance: number
): Uint8Array {
  const { width, height, data } = imageData;
  const mask = new Uint8Array(width * height);
  const sx = Math.round(seed.x);
  const sy = Math.round(seed.y);
  if (sx < 0 || sy < 0 || sx >= width || sy >= height) return mask;

  const startIdx = sy * width + sx;
  const queue = new Int32Array(width * height);
  let head = 0;
  let tail = 0;

  mask[startIdx] = 1;
  queue[tail++] = startIdx;

  let meanR = data[startIdx * 4];
  let meanG = data[startIdx * 4 + 1];
  let meanB = data[startIdx * 4 + 2];
  let count = 1;

  while (head < tail) {
    const idx = queue[head++];
    const cx = idx % width;
    const cy = (idx - cx) / width;

    for (let i = 0; i < 4; i++) {
      const nx = cx + DX4[i];
      const ny = cy + DY4[i];
      if (nx < 0 || nx >= width || ny < 0 || ny >= height) continue;
      const nIdx = ny * width + nx;
      if (mask[nIdx]) continue;

      const rIdx = nIdx * 4;
      const nr = data[rIdx];
      const ng = data[rIdx + 1];
      const nb = data[rIdx + 2];

      const dr = nr - meanR, dg = ng - meanG, db = nb - meanB;
      const dist = Math.sqrt(dr * dr + dg * dg + db * db);
      if (dist < colorTolerance) {
        mask[nIdx] = 1;
        queue[tail++] = nIdx;
        meanR = (meanR * count + nr) / (count + 1);
        meanG = (meanG * count + ng) / (count + 1);
        meanB = (meanB * count + nb) / (count + 1);
        count++;
      }
    }
  }

  return mask;
}

/** union (add) / subtract (omit) / replace combine, mirroring server combine(). */
export function combineMasks(
  prev: Uint8Array | null,
  next: Uint8Array,
  mode: "add" | "omit" | "replace"
): Uint8Array {
  if (!prev || mode === "replace") return next;
  const out = new Uint8Array(prev.length);
  if (mode === "add") {
    for (let i = 0; i < out.length; i++) out[i] = prev[i] || next[i] ? 1 : 0;
  } else {
    // omit: prev AND NOT next
    for (let i = 0; i < out.length; i++) out[i] = prev[i] && !next[i] ? 1 : 0;
  }
  return out;
}

/** Trace the outer boundary of a single labeled region using Moore-Neighbor
 * tracing with Jacob's stopping criterion. */
function traceContour(mask: Uint8Array, width: number, height: number, startX: number, startY: number): Point[] {
  const contour: Point[] = [];
  let px = startX;
  let py = startY;
  contour.push({ x: px, y: py });

  const directions = [
    { dx: -1, dy: -1 }, { dx: 0, dy: -1 }, { dx: 1, dy: -1 },
    { dx: 1, dy: 0 }, { dx: 1, dy: 1 }, { dx: 0, dy: 1 },
    { dx: -1, dy: 1 }, { dx: -1, dy: 0 },
  ];

  const getDirIndex = (dx: number, dy: number): number => {
    for (let i = 0; i < 8; i++) {
      if (directions[i].dx === dx && directions[i].dy === dy) return i;
    }
    return 0;
  };

  let bx = px - 1;
  let by = py;
  let cIdx = getDirIndex(bx - px, by - py);
  let enteredStartCount = 0;
  const maxIterations = width * height * 2;
  let iterations = 0;

  const at = (x: number, y: number) => mask[y * width + x] === 1;

  while (iterations++ < maxIterations) {
    let foundNext = false;

    for (let i = 0; i < 8; i++) {
      const idx = (cIdx + i) % 8;
      const nx = px + directions[idx].dx;
      const ny = py + directions[idx].dy;

      if (nx >= 0 && nx < width && ny >= 0 && ny < height && at(nx, ny)) {
        const prevIdx = (idx - 1 + 8) % 8;
        bx = px + directions[prevIdx].dx;
        by = py + directions[prevIdx].dy;

        px = nx;
        py = ny;
        contour.push({ x: px, y: py });

        cIdx = getDirIndex(bx - px, by - py);
        foundNext = true;
        break;
      }
    }

    if (!foundNext) break;
    if (px === startX && py === startY) {
      enteredStartCount++;
      if (enteredStartCount >= 2) break;
    }
  }

  return contour;
}

function findSqPointToSegmentDistance(p: Point, p1: Point, p2: Point): number {
  let x = p1.x;
  let y = p1.y;
  let dx = p2.x - x;
  let dy = p2.y - y;

  if (dx !== 0 || dy !== 0) {
    const t = ((p.x - x) * dx + (p.y - y) * dy) / (dx * dx + dy * dy);
    if (t > 1) {
      x = p2.x;
      y = p2.y;
    } else if (t > 0) {
      x += dx * t;
      y += dy * t;
    }
  }

  dx = p.x - x;
  dy = p.y - y;
  return dx * dx + dy * dy;
}

/** Ramer-Douglas-Peucker polygon simplification. */
function simplifyRDP(points: Point[], epsilon: number): Point[] {
  if (points.length <= 2 || epsilon <= 0) return points;

  let maxSqDistance = 0;
  let index = -1;
  const end = points.length - 1;

  for (let i = 1; i < end; i++) {
    const sqDistance = findSqPointToSegmentDistance(points[i], points[0], points[end]);
    if (sqDistance > maxSqDistance) {
      index = i;
      maxSqDistance = sqDistance;
    }
  }

  if (maxSqDistance > epsilon * epsilon) {
    const left = simplifyRDP(points.slice(0, index + 1), epsilon);
    const right = simplifyRDP(points.slice(index), epsilon);
    return left.slice(0, left.length - 1).concat(right);
  }

  return [points[0], points[end]];
}

/** Connected-component labeling (4-connectivity) over a binary mask. */
function labelComponents(mask: Uint8Array, width: number, height: number): { labels: Int32Array; count: number } {
  const labels = new Int32Array(width * height).fill(0);
  const queue = new Int32Array(width * height);
  let nextLabel = 0;

  for (let i = 0; i < mask.length; i++) {
    if (!mask[i] || labels[i]) continue;
    nextLabel++;
    let head = 0, tail = 0;
    queue[tail++] = i;
    labels[i] = nextLabel;

    while (head < tail) {
      const idx = queue[head++];
      const cx = idx % width;
      const cy = (idx - cx) / width;
      for (let d = 0; d < 4; d++) {
        const nx = cx + DX4[d];
        const ny = cy + DY4[d];
        if (nx < 0 || nx >= width || ny < 0 || ny >= height) continue;
        const nIdx = ny * width + nx;
        if (mask[nIdx] && !labels[nIdx]) {
          labels[nIdx] = nextLabel;
          queue[tail++] = nIdx;
        }
      }
    }
  }

  return { labels, count: nextLabel };
}

/** Convert a binary mask into simplified outer-boundary polygons, one per
 * connected component (components below `minSize` pixels are skipped). */
export function maskToPolygons(
  mask: Uint8Array,
  width: number,
  height: number,
  rdpEpsilon: number,
  minSize = 4
): Point[][] {
  const { labels, count } = labelComponents(mask, width, height);
  if (count === 0) return [];

  const sizes = new Int32Array(count + 1);
  const starts = new Int32Array(count + 1).fill(-1);
  for (let i = 0; i < labels.length; i++) {
    const l = labels[i];
    if (l) {
      sizes[l]++;
      if (starts[l] === -1) starts[l] = i;
    }
  }

  const polys: Point[][] = [];
  for (let l = 1; l <= count; l++) {
    if (sizes[l] < minSize || starts[l] === -1) continue;
    const start = starts[l];
    const sx = start % width;
    const sy = (start - sx) / width;
    const componentMask = new Uint8Array(width * height);
    for (let i = 0; i < labels.length; i++) if (labels[i] === l) componentMask[i] = 1;

    const raw = traceContour(componentMask, width, height, sx, sy);
    if (raw.length < 3) continue;
    const simplified = simplifyRDP(raw, rdpEpsilon);
    polys.push(simplified);
  }
  return polys;
}
