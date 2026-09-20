// A band canvas: a horizontal strip of the screen, drawn into and pushed out,
// so nothing ever has to hold a whole frame.
//
// The shapes are analytic rather than bitmaps: a rotated ellipse solves for its
// own span on each row, so the loop only ever visits pixels it is going to
// touch, and every edge is antialiased from the real distance to the curve.
// That is what makes the fly stay smooth while it turns at any angle, without
// a single rotated sprite in memory.
#pragma once
#include <Arduino.h>
#include <math.h>

namespace gfx {

// Shading ramps. 33 entries was not enough: a big smooth face quantised into
// 33 steps shows every one of them as a contour ring, and RGB565 only has 32
// red levels to spend anyway. 65 entries plus the ordered dither below puts
// the rings under the noise floor. Four ramps at 130 bytes each is nothing.
const int RAMP_N = 65;
const float RAMP_TOP = (float)(RAMP_N - 1);

// 4x4 ordered dither, a fraction of a ramp step. The shaders index it with
// their own local coordinates, which are rotated screen pixels, so the pattern
// sits still on the shape rather than crawling.
const float BAYER[16] = {
  0.0625f, 0.5625f, 0.1875f, 0.6875f,
  0.8125f, 0.3125f, 0.9375f, 0.4375f,
  0.2500f, 0.7500f, 0.1250f, 0.6250f,
  1.0000f, 0.5000f, 0.8750f, 0.3750f,
};
inline float dither(float lx, float ly) {
  return BAYER[((((int)(ly + 512.0f)) & 3) << 2) | (((int)(lx + 512.0f)) & 3)] - 0.5f;
}



struct Band {
  uint16_t* px;             // native-endian while drawing; byte-swapped on the way out
  int16_t x0, y0;           // top-left of the band in screen coordinates
  int16_t w, h;
  inline uint16_t* row(int y) { return px + (y - y0) * w; }
};

inline uint16_t rgb(int r, int g, int b) {
  return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | ((b & 0xF8) >> 3);
}

// src over dst, coverage 0..256.
inline uint16_t blend(uint16_t dst, uint16_t src, int cov) {
  if (cov >= 256) return src;
  int ia = 256 - cov;
  // Round rather than truncate. Truncating at low coverage throws away the
  // 5-bit red and blue while keeping the 6-bit green, which turns anything
  // faint - the wings especially - a dirty green.
  int r = (((src >> 11) & 0x1F) * cov + ((dst >> 11) & 0x1F) * ia + 128) >> 8;
  int g = (((src >> 5) & 0x3F) * cov + ((dst >> 5) & 0x3F) * ia + 128) >> 8;
  int b = ((src & 0x1F) * cov + (dst & 0x1F) * ia + 128) >> 8;
  return (r << 11) | (g << 5) | b;
}

// Build a 33-entry ramp through up to 4 colours placed at stops[] in 0..1.
void buildRamp(uint16_t* out, const uint32_t* colors, const float* stops, int n);

// 16x16 tile of the compound-eye facet pattern, values around 128. Built once.
extern uint8_t facetTile[256];

// sqrt over 0..1, which is all the sphere normal ever needs. A real sqrtf per
// pixel was one of the two things keeping the frame rate down; the error here
// is worst at the rim, where the sphere is darkest and nobody can see it.
const int SQRT_N = 512;
extern float sqrtLut[SQRT_N + 1];
inline float sqrtUnit(float v) {
  int i = (int)(v * (float)SQRT_N);
  if (i <= 0) return 0.0f;
  if (i >= SQRT_N) return 1.0f;
  return sqrtLut[i];
}

void begin();

// ---------------------------------------------------------------- shaders
// Each shader is a plain struct with operator() returning the colour for a
// point, and alphaAt() for shapes that fade out. They are passed by template
// so the compiler inlines them straight into the pixel loop.

struct Flat {
  uint16_t c;
  inline uint16_t operator()(float, float, float) const { return c; }
  inline float alphaAt(float) const { return 1.0f; }
};

// A soft-edged translucent blob: wings.
struct Veil {
  uint16_t c;
  float fade;                    // how much the far edge thins out
  inline uint16_t operator()(float, float, float) const { return c; }
  inline float alphaAt(float q2) const { return 1.0f - fade * q2; }
};

// A lit sphere. `ia`/`ib` normalise the local coordinates and `oy` shifts them,
// so a shape drawn off-centre can still be shaded as part of a larger surface.
// The head is two overlapping ellipses - a wide brow and a narrower chin - and
// giving both the same normalised frame is what makes them one head rather than
// two blobs with a seam down the overlap.
//
// Everything, the rim included, comes off that shared frame: inside the union
// the rim term is small, so the overlap does not darken, and it only bites at
// the silhouette, where both ellipses agree.
struct Sphere {
  const uint16_t* ramp;
  float ia, ib;
  float Lx, Ly, Lz;
  float ambient, gain, spec, rim;
  float oy;                      // this shape's centre in the shading frame
  inline uint16_t operator()(float lx, float ly, float) const {
    float nx = lx * ia, ny = (ly + oy) * ib;
    float q = nx * nx + ny * ny;
    float z = sqrtUnit(1.0f - q);
    float d = nx * Lx + ny * Ly + z * Lz;
    if (d < 0.0f) d = 0.0f;
    float t = ambient + gain * d * d;
    float s = d - 0.90f;
    if (s > 0.0f) t += s * spec;
    t -= rim * q * q;
    int i = (int)(t * RAMP_TOP + dither(lx, ly));
    if (i < 0) i = 0; else if (i > RAMP_N - 1) i = RAMP_N - 1;
    return ramp[i];
  }
  inline float alphaAt(float) const { return 1.0f; }
};

// The compound eye: a lit sphere with the facet grid pressed into it.
struct Compound {
  Sphere s;
  float facetK;                  // facet cells per pixel
  float facetAmt;
  inline uint16_t operator()(float lx, float ly, float q2) const {
    float nx = lx * s.ia, ny = ly * s.ib;
    float z = sqrtUnit(1.0f - q2);
    float d = nx * s.Lx + ny * s.Ly + z * s.Lz;
    if (d < 0.0f) d = 0.0f;
    float t = s.ambient + s.gain * d * d;
    float sp = d - 0.90f;
    if (sp > 0.0f) t += sp * s.spec;
    // Facets crowd together towards the rim, the way they do on a real eye.
    float k = facetK * (1.0f + 0.90f * (1.0f - z));
    int fx = (int)(lx * k + 512.0f) & 15;
    int fy = (int)(ly * k + 512.0f) & 15;
    t += (facetTile[(fy << 4) | fx] - 128) * facetAmt;
    t -= s.rim * q2 * q2;
    int i = (int)(t * RAMP_TOP + dither(lx, ly));
    if (i < 0) i = 0; else if (i > RAMP_N - 1) i = RAMP_N - 1;
    return s.ramp[i];
  }
  inline float alphaAt(float) const { return 1.0f; }
};

// ------------------------------------------------------------- primitives

// Filled ellipse centred at (cx,cy), semi-axes (ra,rb), rotated by (cs,sn).
// Solves the conic per row for its exact span, so it never scans empty pixels,
// and takes the antialiased edge from the distance to the curve.
template <class SH>
void fillEllipse(Band& b, float cx, float cy, float ra, float rb,
                 float cs, float sn, float alpha, const SH& sh) {
  if (ra < 0.4f || rb < 0.4f || alpha <= 0.004f) return;
  const float ia2 = 1.0f / (ra * ra), ib2 = 1.0f / (rb * rb);

  const float Ry = sqrtf(ra * ra * sn * sn + rb * rb * cs * cs) + 1.5f;
  int ys = (int)floorf(cy - Ry), ye = (int)ceilf(cy + Ry);
  const int bandLast = b.y0 + b.h - 1;
  if (ys < b.y0) ys = b.y0;
  if (ye > bandLast) ye = bandLast;
  if (ys > ye) return;

  const float A  = cs * cs * ia2 + sn * sn * ib2;
  const float Cc = sn * sn * ia2 + cs * cs * ib2;
  const float Bk = 2.0f * cs * sn * (ia2 - ib2);
  const float invA2 = 0.5f / A;
  const float aaK = 0.5f * (ra < rb ? ra : rb);   // pixels per unit of q2 at the rim
  const int aBase = (int)(alpha * 256.0f + 0.5f);
  const int xLast = b.x0 + b.w - 1;

  for (int Y = ys; Y <= ye; Y++) {
    const float v = (Y + 0.5f) - cy;
    const float B = Bk * v;
    const float C = Cc * v * v - 1.0f;
    const float disc = B * B - 4.0f * A * C;
    if (disc <= 0.0f) continue;
    const float sq = sqrtf(disc);
    int xs = (int)floorf(cx + (-B - sq) * invA2 - 1.5f);
    int xe = (int)ceilf (cx + (-B + sq) * invA2 + 1.5f);
    if (xs < b.x0) xs = b.x0;
    if (xe > xLast) xe = xLast;
    if (xs > xe) continue;

    const float u = (xs + 0.5f) - cx;
    float lx = u * cs + v * sn;
    float ly = -u * sn + v * cs;
    uint16_t* p = b.row(Y) + (xs - b.x0);
    for (int X = xs; X <= xe; X++, p++, lx += cs, ly -= sn) {
      const float q2 = lx * lx * ia2 + ly * ly * ib2;
      if (q2 > 1.5f) continue;
      // Near the rim, which is the only place the edge matters, q-1 is
      // (q2-1)/2 to well under a pixel. So the square root goes.
      float cov = 0.5f - (q2 - 1.0f) * aaK;
      if (cov <= 0.0f) continue;
      if (cov > 1.0f) cov = 1.0f;
      int a = (int)(cov * sh.alphaAt(q2) * aBase);
      if (a <= 0) continue;
      *p = blend(*p, sh(lx, ly, q2), a);
    }
  }
}

// A soft warm halo. One of these is drawn just outside each of the head and the
// two eyes, so the glow hugs the actual silhouette; a single ellipse around the
// lot spills into the gap between the eyes and reads as a red donut.
//
// It keeps whichever of the halo and what is already there is brighter, rather
// than blending, so overlapping halos merge instead of erasing one another and
// the wings still show through the dim outer part. `ramp` has the falloff baked
// in and reaches black at the top, so the outer edge needs no antialiasing.
//
// `k` maps the visible rim onto the whole ramp: RAMP_N-1 over 1-(inner/outer)^2.
void fillGlow(Band& b, float cx, float cy, float ra, float rb,
              float cs, float sn, float k, const uint16_t* ramp);

struct Pt { float x, y; };

// Polyline with round joins and caps, thickness tapering from t0 to t1.
// Antennae, legs and the smile are all this.
void strokePoly(Band& b, const Pt* pts, int n, float t0, float t1,
                uint16_t color, float alpha);

// Sample a quadratic bezier into `out` (n points, endpoints included).
void quadBezier(Pt p0, Pt p1, Pt p2, Pt* out, int n);

}  // namespace gfx
