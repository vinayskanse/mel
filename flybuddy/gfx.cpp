#include "gfx.h"

namespace gfx {

uint8_t facetTile[256];
float sqrtLut[SQRT_N + 1];

void buildRamp(uint16_t* out, const uint32_t* colors, const float* stops, int n) {
  for (int i = 0; i < RAMP_N; i++) {
    float t = i / (float)(RAMP_N - 1);
    int seg = 0;
    while (seg < n - 2 && t > stops[seg + 1]) seg++;
    float a = stops[seg], b = stops[seg + 1];
    float f = b > a ? (t - a) / (b - a) : 0.0f;
    if (f < 0.0f) f = 0.0f; else if (f > 1.0f) f = 1.0f;
    uint32_t c0 = colors[seg], c1 = colors[seg + 1];
    int r = (int)(((c0 >> 16) & 0xFF) + (((int)((c1 >> 16) & 0xFF) - (int)((c0 >> 16) & 0xFF)) * f));
    int g = (int)(((c0 >> 8) & 0xFF) + (((int)((c1 >> 8) & 0xFF) - (int)((c0 >> 8) & 0xFF)) * f));
    int b2 = (int)((c0 & 0xFF) + (((int)(c1 & 0xFF) - (int)(c0 & 0xFF)) * f));
    out[i] = rgb(r, g, b2);
  }
}

void begin() {
  for (int i = 0; i <= SQRT_N; i++) sqrtLut[i] = sqrtf(i / (float)SQRT_N);

  // The ommatidia of a compound eye sit on a hexagonal lattice, not a grid. A
  // square grid of dots reads as a golf ball; offsetting alternate rows by half
  // a cell reads as an eye. Four cells across a 16x16 tile, and the tile wraps,
  // so neighbours one cell outside are included when finding the nearest centre.
  for (int y = 0; y < 16; y++) {
    for (int x = 0; x < 16; x++) {
      float best = 1e9f;
      for (int j = -1; j <= 4; j++) {
        float cy = j * 4.0f;
        float cx0 = (j & 1) ? 2.0f : 0.0f;
        for (int i = -1; i <= 4; i++) {
          float dx = x - (i * 4.0f + cx0), dy = y - cy;
          float d2 = dx * dx + dy * dy;
          if (d2 < best) best = d2;
        }
      }
      float v = 1.0f - sqrtf(best) / 2.35f;
      if (v < 0.0f) v = 0.0f; else if (v > 1.0f) v = 1.0f;
      v = v * v * (3.0f - 2.0f * v);                 // soften the seam
      facetTile[(y << 4) | x] = (uint8_t)(64.0f + 150.0f * v);
    }
  }
}

// Squared distance from a point to a segment. The reciprocal of the segment
// length is passed in rather than computed here: it only depends on the
// segment, and a float divide per pixel was costing more than everything else
// in the stroke put together.
static inline float segDist2(float px, float py, float ax, float ay,
                             float vx, float vy, float invLen2) {
  float wx = px - ax, wy = py - ay;
  float t = (wx * vx + wy * vy) * invLen2;
  if (t < 0.0f) t = 0.0f; else if (t > 1.0f) t = 1.0f;
  float dx = wx - t * vx, dy = wy - t * vy;
  return dx * dx + dy * dy;
}

void strokePoly(Band& b, const Pt* pts, int n, float t0, float t1,
                uint16_t color, float alpha) {
  if (n < 2 || alpha <= 0.004f) return;
  const int aBase = (int)(alpha * 256.0f + 0.5f);
  const int yLast = b.y0 + b.h - 1, xLast = b.x0 + b.w - 1;

  for (int i = 0; i < n - 1; i++) {
    const float f = (n > 2) ? i / (float)(n - 2) : 0.0f;
    const float half = 0.5f * (t0 + (t1 - t0) * f);
    if (half < 0.25f) continue;
    const float ax = pts[i].x, ay = pts[i].y;
    const float vx = pts[i + 1].x - ax, vy = pts[i + 1].y - ay;
    const float len2 = vx * vx + vy * vy;
    const float invLen2 = len2 > 1e-6f ? 1.0f / len2 : 0.0f;
    const float pad = half + 1.0f;

    int ys = (int)floorf(fminf(ay, ay + vy) - pad);
    int ye = (int)ceilf (fmaxf(ay, ay + vy) + pad);
    if (ys < b.y0) ys = b.y0;
    if (ye > yLast) ye = yLast;
    if (ys > ye) continue;
    int xs = (int)floorf(fminf(ax, ax + vx) - pad);
    int xe = (int)ceilf (fmaxf(ax, ax + vx) + pad);
    if (xs < b.x0) xs = b.x0;
    if (xe > xLast) xe = xLast;
    if (xs > xe) continue;

    // Two radii: inside the inner one the pixel is solid and needs no square
    // root, outside the outer one it is untouched. Only the thin ring between
    // them - the antialiased edge - pays for a root.
    const float rOut = half + 0.5f, outer = rOut * rOut;
    const float rIn = half - 0.5f, inner = rIn > 0.0f ? rIn * rIn : -1.0f;

    for (int Y = ys; Y <= ye; Y++) {
      uint16_t* p = b.row(Y) + (xs - b.x0);
      const float py = Y + 0.5f;
      for (int X = xs; X <= xe; X++, p++) {
        float d2 = segDist2(X + 0.5f, py, ax, ay, vx, vy, invLen2);
        if (d2 > outer) continue;
        if (d2 <= inner) { *p = blend(*p, color, aBase); continue; }
        float cov = rOut - sqrtf(d2);
        if (cov <= 0.0f) continue;
        if (cov > 1.0f) cov = 1.0f;
        *p = blend(*p, color, (int)(cov * aBase));
      }
    }
  }
}

void fillGlow(Band& b, float cx, float cy, float ra, float rb,
              float cs, float sn, float k, const uint16_t* ramp) {
  if (ra < 0.5f || rb < 0.5f) return;
  const float ia2 = 1.0f / (ra * ra), ib2 = 1.0f / (rb * rb);
  const float Ry = sqrtf(ra * ra * sn * sn + rb * rb * cs * cs) + 1.0f;
  int ys = (int)floorf(cy - Ry), ye = (int)ceilf(cy + Ry);
  const int bandLast = b.y0 + b.h - 1;
  if (ys < b.y0) ys = b.y0;
  if (ye > bandLast) ye = bandLast;
  if (ys > ye) return;

  const float A  = cs * cs * ia2 + sn * sn * ib2;
  const float Cc = sn * sn * ia2 + cs * cs * ib2;
  const float Bk = 2.0f * cs * sn * (ia2 - ib2);
  const float invA2 = 0.5f / A;
  const int xLast = b.x0 + b.w - 1;

  for (int Y = ys; Y <= ye; Y++) {
    const float v = (Y + 0.5f) - cy;
    const float B = Bk * v;
    const float C = Cc * v * v - 1.0f;
    const float disc = B * B - 4.0f * A * C;
    if (disc <= 0.0f) continue;
    const float sq = sqrtf(disc);
    int xs = (int)floorf(cx + (-B - sq) * invA2);
    int xe = (int)ceilf (cx + (-B + sq) * invA2);
    if (xs < b.x0) xs = b.x0;
    if (xe > xLast) xe = xLast;
    if (xs > xe) continue;

    const float u = (xs + 0.5f) - cx;
    float lx = u * cs + v * sn;
    float ly = -u * sn + v * cs;
    uint16_t* p = b.row(Y) + (xs - b.x0);
    for (int X = xs; X <= xe; X++, p++, lx += cs, ly -= sn) {
      const float q2 = lx * lx * ia2 + ly * ly * ib2;
      if (q2 >= 1.0f) continue;
      int i = (int)((1.0f - q2) * k);
      if (i > RAMP_N - 1) i = RAMP_N - 1;
      uint16_t c = ramp[i];
      if (c > *p) *p = c;              // brighter of the two, so halos merge
    }
  }
}

void quadBezier(Pt p0, Pt p1, Pt p2, Pt* out, int n) {
  for (int i = 0; i < n; i++) {
    float t = i / (float)(n - 1), u = 1.0f - t;
    out[i].x = u * u * p0.x + 2.0f * u * t * p1.x + t * t * p2.x;
    out[i].y = u * u * p0.y + 2.0f * u * t * p1.y + t * t * p2.y;
  }
}

}  // namespace gfx
