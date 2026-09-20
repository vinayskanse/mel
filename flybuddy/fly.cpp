#include "fly.h"
#include <Arduino.h>
#include <math.h>
#include "board_config.h"
#include "motion.h"

namespace fly {
namespace {

using gfx::Pt;

// ---------------------------------------------------------------- geometry
// Everything is in fly units: the origin is the middle of the head, +x right,
// +y down, and one unit is the head's half-height, so the head runs from -1 to
// +1. The whole animal is described here and nowhere else, so changing the
// proportions changes the fly at every angle and every size at once.
//
// The numbers come off the design sheet (`../design/image.png`, panel 1) at
// 54 px to the unit.

// The head is two overlapping ellipses: a wide brow that the eyes sit either
// side of, and a narrower chin below it carrying the mouth. One ellipse cannot
// be both wide at the top and tapered at the bottom, and the taper is most of
// what makes this read as a fruit fly rather than a bee.
const float SKULL_Y = -0.30f, SKULL_A = 0.88f, SKULL_B = 0.70f;
const float CHIN_Y  =  0.30f, CHIN_A  = 0.62f, CHIN_B  = 0.72f;
const float HEAD_IA = 1.0f / 0.90f, HEAD_IB = 1.0f / 1.02f;  // the shared shading frame

// Tall compound eyes, leaning very slightly outward, reaching almost the whole
// height of the head. No pupils and no whites: the eye never changes shape.
const float EYE_X = 0.86f, EYE_Y = 0.02f, EYE_A = 0.53f, EYE_B = 0.76f;
const float EYE_TILT = 0.10f;

// Only the front of the body shows. There is no abdomen behind the wings and
// no thorax segmentation - it is a small mound under the chin that the legs
// hang off, and that is all the screen has room for anyway.
const float BODY_Y = 0.97f, BODY_A = 0.43f, BODY_B = 0.31f;

const float MOUTH_Y = 0.54f, MOUTH_W = 0.145f;
const float PIVOT_Y = 0.95f;          // the neck: the head turns about this

// How far the halo reaches past each part, and the ramp stretch that puts the
// whole falloff into that reach.
const float GLOW_PAD_HEAD = 0.075f, GLOW_PAD_EYE = 0.145f;
const float GLOW_K_HEAD = 430.0f, GLOW_K_EYE = 166.0f;

// What has to fit on the screen. The wing is the widest thing on the fly. Its
// half-extent is not simply the tip: for an ellipse tilted by t it is
// sqrt((a cos t)^2 + (b sin t)^2) from the wing's own centre, which at rest
// works out at 1.66 + 0.85 = 2.51. Keep this in step with the wing block in
// buildGeometry, or the tips get cut off against the edge of the screen.
// The eyes, which are solid and really must clear the edge, only reach 1.39.
const float SOFT_SIDE = 2.52f;
const float EXT_DOWN  = 1.44f;        // the feet
const float ANT_UP    = 1.94f;        // antenna tips, upright and alert
const float ANT_REST  = 0.30f;        // how far they drop when it sprawls
const float MARGIN    = 8.0f;         // clearance on every side

const int ANT_N = 7, LEG_N = 3, MOUTH_N = 9;   // a leg is hip, knee, foot

// Legs, right-hand side: hip, knee, foot. The other three are the mirror
// image. Order matters: 0 is the front pair - the ones it grooms with, and the
// ones that come up to grip the edge of the screen.
const float LEG[3][6] = {
  {0.40f, 0.84f,  0.72f, 1.04f,  0.80f, 1.32f},
  {0.34f, 0.90f,  0.48f, 1.10f,  0.46f, 1.32f},
  {0.26f, 0.95f,  0.24f, 1.12f,  0.13f, 1.28f},
};

// -------------------------------------------------------------------- moods
// A mood is not a different fly. It is the same layers with a few numbers
// changed: the mouth, the antennae, the wings, how low it sits, and at most
// one small symbol floating beside it. That is the whole trick - it is why ten
// moods cost about as much to draw as one.
enum { FX_NONE, FX_ZZZ, FX_NOTES, FX_QUERY, FX_ANGER, FX_SPARK, FX_FOOD, FX_BATTERY };

struct Pose {
  float mouthCurve;   // +1 smile, 0 flat dash, -1 frown
  float mouthOpen;    // 0 a line, 1 a round O
  float mouthWide;
  float antLift;      // +1 up and alert, 0 normal, -1 drooped
  float antSplay;
  float antAsym;      // one antenna tilted further than the other
  float wingSet;      // 0 folded in, 0.35 at rest, 1 swept up
  float wingBeat;     // side-to-side flutter
  float sink;         // how far it drops toward the floor, in fly units
  float legSpread;
  uint8_t fx;
};

//              mouth          antennae         wings      sink  legs   fx
const Pose POSE[MOOD_N] = {
  { 0.00f,0.00f,1.00f,  0.00f,0.00f,0.00f,  0.35f,0.00f,  0.00f, 0.00f, FX_NONE    },  // idle
  { 1.00f,0.00f,1.15f,  0.45f,0.15f,0.00f,  0.40f,0.00f, -0.04f, 0.05f, FX_NONE    },  // happy
  { 0.30f,1.00f,0.90f,  1.00f,0.35f,0.00f,  0.55f,0.35f, -0.10f, 0.10f, FX_SPARK   },  // excited
  { 0.20f,0.85f,0.95f, -0.20f,0.00f,0.00f,  0.30f,0.00f,  0.03f, 0.12f, FX_FOOD    },  // eating
  { 0.35f,0.00f,0.70f, -1.00f,0.10f,0.00f,  0.05f,0.00f,  0.22f,-0.10f, FX_ZZZ     },  // sleeping
  { 0.85f,0.30f,1.05f,  0.70f,0.30f,0.00f,  0.60f,1.00f, -0.02f, 0.25f, FX_NOTES   },  // dancing
  { 0.00f,0.35f,0.80f,  0.55f,0.10f,1.00f,  0.38f,0.00f,  0.00f, 0.00f, FX_QUERY   },  // curious
  {-1.00f,0.00f,1.00f,  0.85f,-0.30f,0.00f, 0.45f,0.55f,  0.04f, 0.15f, FX_ANGER   },  // angry
  {-0.85f,0.10f,1.10f,  0.60f,0.25f,0.00f,  0.20f,0.20f,  0.90f, 0.00f, FX_SPARK   },  // let me out
  {-0.55f,0.00f,0.90f, -0.55f,0.00f,0.00f,  0.18f,0.00f,  0.14f,-0.05f, FX_BATTERY },  // low battery
};

const char* MOOD_NAME[MOOD_N] = {
  "idle", "happy", "excited", "eating", "sleeping",
  "dancing", "curious", "angry", "letmeout", "lowbatt",
};

// ------------------------------------------------------------------ colour
uint16_t rampEye[gfx::RAMP_N], rampHead[gfx::RAMP_N], rampBody[gfx::RAMP_N], rampGlow[gfx::RAMP_N];
uint16_t colWing, colLimb, colMouth, colAccent, colFood;

// -------------------------------------------------------------------- state
enum { SIT, FLY, LAND };
int state = SIT;

float px = LCD_W * 0.5f, py = LCD_H * 0.6f, vx = 0, vy = 0;
float ang = 0, angV = 0;              // body rotation, radians
float scl = 55, sclV = 0;             // pixels per fly unit
float sqz = 0, sqzV = 0;              // >0 squashed wide, <0 stretched tall
float head = 0, headV = 0, headWant = 0;
float ant = 0, antV = 0;              // antennae trailing the head
float flick = 0, flickV = 0;
float blur = 0, tuck = 0, wide = 0, joy = 0;
float groom = 0, groomPhase = 0;
float lightA = 0;
float tsec = 0, wander = 0, stableMs = 0;
float sitAng = 0;                     // the angle it last settled at
unsigned long nextHead = 0, nextGroom = 0, nextFlick = 0, groomEnd = 0, nextHop = 0;
float hop = 0, hopV = 0;

// mood
Mood curMood = IDLE, askedMood = IDLE;
float moodHold = 0;                   // seconds left on a mood somebody asked for
bool  moodForced = false;
float fxPhase = 0, eatT = 0, sway = 0, grip = 0;
uint8_t fxCur = FX_NONE;
float   fxAmt = 0;
unsigned long nextWhim = 0, moodUntil = 0;
bool foodPending = false;             // offered, not yet eaten
unsigned long foodBy = 0;             // and it goes stale at this point
Pose pose = POSE[IDLE];               // the eased, currently-drawn pose

// ------------------------------------------------------------------ helpers
inline float wrapPi(float a) {
  while (a > (float)PI) a -= (float)TWO_PI;
  while (a < -(float)PI) a += (float)TWO_PI;
  return a;
}
inline float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }
inline float randf(float a, float b) { return a + (b - a) * (random(0, 10001) * 0.0001f); }

// One critically-ish damped spring step. Low damping is deliberate in places:
// the overshoot is what makes the landing read as a snap rather than a slide.
inline void spring(float& x, float& v, float target, float k, float damp, float dt) {
  v += (target - x) * k * dt;
  v -= v * clampf(damp * dt, 0.0f, 1.0f);
  x += v * dt;
}
inline void ease(float& x, float target, float rate, float dt) {
  x += (target - x) * clampf(rate * dt, 0.0f, 1.0f);
}

// A frame's worth of screen-space shapes, built once in update() and then just
// rasterised by each band.
struct Ell { float cx, cy, ra, rb, cs, sn; };

const int FX_SEG = 5, FX_PTS = 6;

struct Geo {
  Ell wing[2], body, skull, chin, eye[2], mouthO;
  float wingAlpha, ghostStep;
  int   ghosts;
  Pt    antP[2][ANT_N], legP[6][LEG_N], mouthP[MOUTH_N];
  float antT0, antT1, legT0, legT1, mouthT, mouthAlpha, openAlpha;
  float lightX, lightY;
  Pt    handP[2];
  float handR;
  float headIA, headIB, skullOY, chinOY;   // the frame the two head halves share
  // the small symbol beside it: a handful of polylines and up to two dots
  Pt       fxP[FX_SEG][FX_PTS];
  uint8_t  fxN[FX_SEG];
  float    fxT[FX_SEG], fxA[FX_SEG];
  uint16_t fxC[FX_SEG];
  Pt       fxDot[2];
  float    fxDotR[2], fxDotA[2];
  uint16_t fxDotC[2];
  bool     fxLive;
} g;

int bx0, by0, bx1, by1;

// A local frame: scale, then rotate, then translate.
struct Xf {
  float cx, cy, cs, sn, sx, sy;
  inline void map(float lx, float ly, float& X, float& Y) const {
    float ux = lx * sx, uy = ly * sy;
    X = cx + ux * cs - uy * sn;
    Y = cy + ux * sn + uy * cs;
  }
  inline Pt operator()(float lx, float ly) const { Pt p; map(lx, ly, p.x, p.y); return p; }
};

// Where the fly should sit, and how big it can be, for a given quarter turn.
// This is derived from gravity rather than from a table of cases, which is why
// 180 degrees and a full 360 need no special handling.
void sitTarget(int q, float snapAng, float wideAmt, float& tx, float& ty, float& ts) {
  float along  = (q & 1) ? (float)LCD_W : (float)LCD_H;
  float across = (q & 1) ? (float)LCD_H : (float)LCD_W;
  // Sprawling drops the antennae, which shortens the fly along the axis that
  // is tightest in landscape. That is where the extra size comes from: it is
  // not scaled up arbitrarily, it genuinely takes up the room it is given.
  float antUp = ANT_UP - ANT_REST * wideAmt;
  float s1 = (along  - 2 * MARGIN) / (antUp + EXT_DOWN);
  float s2 = (across - 2 * MARGIN) / (2 * (SOFT_SIDE + 0.26f * wideAmt));
  ts = s1 < s2 ? s1 : s2;

  float dvx = -sinf(snapAng), dvy = cosf(snapAng);    // "down" on the screen
  float t = 1e9f;
  if (fabsf(dvx) > 1e-3f) t = fminf(t, (LCD_W * 0.5f) / fabsf(dvx));
  if (fabsf(dvy) > 1e-3f) t = fminf(t, (LCD_H * 0.5f) / fabsf(dvy));
  float foot = EXT_DOWN * ts + MARGIN;
  tx = LCD_W * 0.5f + dvx * (t - foot);
  ty = LCD_H * 0.5f + dvy * (t - foot);
}

void takeoff(float dvx, float dvy) {
  if (state == FLY) return;
  state = FLY;
  stableMs = 0;
  vx += -dvx * randf(70, 130) + randf(-60, 60);       // push off the ground
  vy += -dvy * randf(70, 130) + randf(-60, 60);
  sqz = -0.11f;                                       // stretch as it leaves
  sqzV = 0;
  groom = 0; groomEnd = 0;
}

void land() {
  state = SIT;
  sitAng = ang;
  sqz = 0.17f; sqzV = 0;                              // squash on touchdown
  vx *= 0.1f; vy *= 0.1f;
  joy = 1.0f;                                         // grin about it for a second
  nextGroom = millis() + (unsigned long)randf(2200, 4200);
  nextHead  = millis() + (unsigned long)randf(500, 1400);
}

// --------------------------------------------------------------- the symbol
// Each of these fills in g.fx*: a few polylines and at most two dots, in body
// units, so the symbol rides along with the fly and turns with it.
void fxClear() {
  for (int i = 0; i < FX_SEG; i++) { g.fxN[i] = 0; g.fxA[i] = 1.0f; g.fxC[i] = colAccent; g.fxT[i] = 0.07f * scl; }
  g.fxDotR[0] = g.fxDotR[1] = 0.0f;
  g.fxDotA[0] = g.fxDotA[1] = 1.0f;
  g.fxDotC[0] = g.fxDotC[1] = colAccent;
  g.fxLive = false;
}

void fxBuild(const Xf& body, uint8_t kind, float amt) {
  fxClear();
  if (kind == FX_NONE || amt < 0.02f) return;
  g.fxLive = true;
  const float ph = fxPhase;

  switch (kind) {
    case FX_ZZZ: {
      // Three Zs, each born at the mouth's height beside the head and drifting
      // up and out as it grows. One cycle, three of them, evenly spaced in it.
      for (int k = 0; k < 3; k++) {
        float u = fmodf(ph + k * 0.3333f, 1.0f);
        float s  = 0.13f + 0.10f * u;
        float cx = 1.02f + 0.80f * u, cy = -1.00f - 1.40f * u;
        Pt* p = g.fxP[k];
        p[0] = body(cx - s, cy - s); p[1] = body(cx + s, cy - s);
        p[2] = body(cx - s, cy + s); p[3] = body(cx + s, cy + s);
        g.fxN[k] = 4;
        g.fxT[k] = (0.050f + 0.018f * u) * scl;
        g.fxA[k] = amt * clampf(3.0f * (1.0f - u), 0.0f, 1.0f) * clampf(u * 6.0f, 0.0f, 1.0f);
      }
      break;
    }
    case FX_NOTES: {
      // A note each side, bobbing out of step with the other.
      for (int s = 0; s < 2; s++) {
        float sgn = s ? -1.0f : 1.0f;
        float w = ph * (float)TWO_PI;
        float nx = sgn * (1.62f + 0.10f * sinf(w + s * 2.1f));
        float ny = -1.08f - 0.26f * sinf(w * 1.3f + s * 1.7f);
        g.fxDot[s]  = body(nx, ny);
        g.fxDotR[s] = 0.155f * scl;
        g.fxDotA[s] = amt;
        Pt* st = g.fxP[s];
        st[0] = body(nx + 0.14f, ny);  st[1] = body(nx + 0.14f, ny - 0.60f);
        g.fxN[s] = 2; g.fxT[s] = 0.055f * scl; g.fxA[s] = amt;
        Pt* fl = g.fxP[2 + s];
        fl[0] = body(nx + 0.14f, ny - 0.60f);
        fl[1] = body(nx + 0.30f, ny - 0.50f);
        fl[2] = body(nx + 0.38f, ny - 0.30f);
        g.fxN[2 + s] = 3; g.fxT[2 + s] = 0.050f * scl; g.fxA[2 + s] = amt;
      }
      break;
    }
    case FX_QUERY: {
      // Six points placed by hand. An arc sampled off a circle closes into a
      // loop at this size; a question mark needs the hook to stop and the tail
      // to come back under it.
      const float qx = 1.62f, qy = -1.44f + 0.05f * sinf(ph * (float)TWO_PI);
      const float r  = 0.30f;
      const float Q[6][2] = {
        {-0.72f, -0.50f}, {-0.58f, -1.18f}, {0.18f, -1.42f},
        { 0.80f, -0.92f}, { 0.48f, -0.26f}, {0.06f,  0.34f},
      };
      Pt* p = g.fxP[0];
      for (int i = 0; i < 6; i++) p[i] = body(qx + Q[i][0] * r, qy + Q[i][1] * r);
      g.fxN[0] = 6; g.fxT[0] = 0.070f * scl; g.fxA[0] = amt;
      g.fxDot[0] = body(qx + 0.06f * r, qy + 1.05f * r);
      g.fxDotR[0] = 0.078f * scl; g.fxDotA[0] = amt;
      break;
    }
    case FX_ANGER: {
      // Three short curls bursting off the temple, pulsing together.
      const float k = 1.0f + 0.12f * sinf(ph * (float)TWO_PI * 3.0f);
      const float M[3][6] = {
        {1.32f, -1.16f,  1.50f, -1.30f,  1.64f, -1.18f},
        {1.66f, -1.46f,  1.82f, -1.58f,  1.92f, -1.42f},
        {1.22f, -1.52f,  1.36f, -1.66f,  1.50f, -1.56f},
      };
      for (int i = 0; i < 3; i++) {
        Pt* p = g.fxP[i];
        for (int j = 0; j < 3; j++) p[j] = body(M[i][j * 2] * k, M[i][j * 2 + 1] * k);
        g.fxN[i] = 3; g.fxT[i] = 0.062f * scl; g.fxA[i] = amt;
      }
      break;
    }
    case FX_SPARK: {
      // Short marks flung off the shoulders, the length breathing with the
      // phase. Trying to escape, it only throws them one way.
      const bool oneSide = (curMood == LETMEOUT);
      for (int i = 0; i < 4; i++) {
        int s = i & 1;
        float sgn = (oneSide || s == 0) ? -1.0f : 1.0f;
        int   row = i >> 1;
        float len = 0.20f + 0.10f * sinf(ph * (float)TWO_PI + i * 1.3f);
        float bx = sgn * (1.36f + 0.20f * row), by = -0.86f - 0.34f * row;
        Pt* p = g.fxP[i];
        p[0] = body(bx, by);
        p[1] = body(bx + sgn * len * 1.5f, by - len * 0.7f);
        g.fxN[i] = 2; g.fxT[i] = 0.062f * scl; g.fxA[i] = amt;
        if (oneSide && s == 1) { g.fxP[i][0] = body(bx - 0.26f, by - 0.20f); g.fxP[i][1] = body(bx - 0.26f + sgn * len * 1.5f, by - 0.20f - len * 0.7f); }
      }
      break;
    }
    case FX_FOOD: {
      // A crumb under the mouth that gets smaller as it is eaten.
      float left = clampf(1.0f - eatT, 0.0f, 1.0f);
      g.fxDot[0]  = body(0.0f, 1.14f);
      g.fxDotR[0] = (0.08f + 0.16f * left) * scl;
      g.fxDotC[0] = colFood;
      g.fxDotA[0] = amt;
      g.fxDot[1]  = body(0.40f, 1.22f);
      g.fxDotR[1] = 0.050f * scl * left;
      g.fxDotC[1] = colFood;
      g.fxDotA[1] = amt * 0.8f;
      break;
    }
    case FX_BATTERY: {
      // An outline, a nub, and one short bar left inside it.
      const float cx = 1.34f, cy = -1.72f, hw = 0.40f, hh = 0.22f;
      Pt* p = g.fxP[0];
      p[0] = body(cx - hw, cy - hh); p[1] = body(cx + hw, cy - hh);
      p[2] = body(cx + hw, cy + hh); p[3] = body(cx - hw, cy + hh);
      p[4] = body(cx - hw, cy - hh);
      g.fxN[0] = 5; g.fxT[0] = 0.052f * scl; g.fxA[0] = amt;
      Pt* n = g.fxP[1];
      n[0] = body(cx + hw + 0.03f, cy - 0.09f); n[1] = body(cx + hw + 0.03f, cy + 0.09f);
      g.fxN[1] = 2; g.fxT[1] = 0.085f * scl; g.fxA[1] = amt;
      // The last bar blinks, slowly, the way they all do.
      Pt* bar = g.fxP[2];
      bar[0] = body(cx - hw + 0.10f, cy); bar[1] = body(cx - hw + 0.34f, cy);
      g.fxN[2] = 2; g.fxT[2] = 0.22f * scl;
      g.fxA[2] = amt * (0.35f + 0.65f * (sinf(ph * (float)TWO_PI) > 0.0f ? 1.0f : 0.0f));
      break;
    }
    default: g.fxLive = false; break;
  }
}

// ------------------------------------------------------------------ shaping
void buildGeometry() {
  const float cs = cosf(ang), sn = sinf(ang);
  Xf body;
  // Dancing slides the whole fly sideways along its own floor rather than
  // moving it across the screen, so it stays put and still reads as a shuffle.
  body.cx = px + sway * scl * cs;
  body.cy = py + hop + sway * scl * sn;
  body.cs = cs; body.sn = sn;
  body.sx = scl * (1.0f + sqz); body.sy = scl * (1.0f - sqz);

  // The head turns about the neck, so the eyes, antennae and mouth all swing
  // together and the body stays put.
  const float hAng = ang + head;
  Xf hx;
  hx.cs = cosf(hAng); hx.sn = sinf(hAng);
  hx.sx = body.sx; hx.sy = body.sy;
  Pt pivot = body(0.0f, PIVOT_Y);
  float uy = PIVOT_Y * hx.sy;
  hx.cx = pivot.x + uy * hx.sn;
  hx.cy = pivot.y - uy * hx.cs;

  // ---- wings. One number runs them: folded in against the body at 0, held
  // out the way a resting fruit fly holds them at about a third, swept up and
  // back for flight at 1. Landscape gives them room to drop and spread.
  const float w = clampf(pose.wingSet, 0.0f, 1.2f);
  const float wcx = 1.52f + 0.40f * w + 0.12f * wide;
  const float wcy = -0.15f - 0.42f * w;
  const float wa  = 0.76f + 0.34f * w + 0.12f * wide;
  const float wb  = 0.29f + 0.08f * w;
  const float wt  = 0.02f + 0.76f * w - 0.34f * wide;
  const float beat = pose.wingBeat * sinf(tsec * 19.0f) * 0.22f;
  for (int s = 0; s < 2; s++) {
    float sgn = s ? -1.0f : 1.0f;
    Pt c = body(sgn * wcx, wcy);
    float t = ang + sgn * (wt + beat);
    g.wing[s] = {c.x, c.y, wa * body.sx, wb * body.sy, cosf(t), sinf(t)};
  }
  // A fruit fly beats its wings about 200 times a second. At 30 frames a
  // second there is no honest way to draw that except as a blur, so in flight
  // it becomes three faint copies fanned apart instead of one crisp shape.
  g.ghosts    = blur > 0.25f ? 3 : 1;
  g.ghostStep = 0.30f * blur;
  g.wingAlpha = blur > 0.25f ? 0.26f : 0.44f;

  // ---- body, head, eyes
  Pt bc = body(0.0f, BODY_Y);
  g.body = {bc.x, bc.y, BODY_A * body.sx, BODY_B * body.sy, cs, sn};
  Pt sc = hx(0.0f, SKULL_Y);
  g.skull = {sc.x, sc.y, SKULL_A * hx.sx, SKULL_B * hx.sy, hx.cs, hx.sn};
  Pt cc = hx(0.0f, CHIN_Y);
  g.chin = {cc.x, cc.y, CHIN_A * hx.sx, CHIN_B * hx.sy, hx.cs, hx.sn};
  for (int s = 0; s < 2; s++) {
    float sgn = s ? -1.0f : 1.0f;
    Pt e = hx(sgn * EYE_X, EYE_Y);
    float t = hAng + sgn * EYE_TILT;
    g.eye[s] = {e.x, e.y, EYE_A * hx.sx, EYE_B * hx.sy, cosf(t), sinf(t)};
  }

  // ---- antennae. `bend` is the same sign on both so they sway together, the
  // way hair does, and it trails the head turn rather than following it.
  // `antLift` takes them from up and alert to drooping out sideways, which is
  // most of the difference between awake and asleep.
  const float bend  = ant + flick * 0.40f;
  const float drop  = ANT_REST * wide;
  const float lift  = pose.antLift;
  const float sag   = (lift > 0.0f ? 0.13f : 0.52f) * -lift;    // + drops the tip
  for (int s = 0; s < 2; s++) {
    float sgn = s ? -1.0f : 1.0f;
    // Curious tilts one of them further than the other; which one alternates
    // with the head turn, so it looks like it is listening rather than broken.
    float asym = pose.antAsym * (sgn * (head >= 0.0f ? 1.0f : -1.0f) > 0.0f ? 1.0f : 0.0f);
    float out  = 1.03f + 0.20f * pose.antSplay + 0.26f * fmaxf(0.0f, -lift) + 0.16f * asym;
    float tipY = -ANT_UP + 0.09f + sag + drop - 0.14f * asym;
    Pt p0 = hx(sgn * 0.46f, -0.98f);
    Pt p1 = hx(sgn * (0.56f + 0.10f * pose.antSplay) + bend * 0.26f,
               -1.46f + sag * 0.55f + drop * 0.55f);
    Pt p2 = hx(sgn * out + bend * 0.90f, tipY);
    gfx::quadBezier(p0, p1, p2, g.antP[s], ANT_N);
  }
  g.antT0 = 0.062f * scl; g.antT1 = 0.110f * scl;    // they club out at the tip

  // ---- legs. They tuck up under the body in flight, spread when it has room,
  // come up to the mouth to be rubbed together while grooming, and reach up to
  // grab the edge of the screen when it has had enough of being in there.
  const float rub = sinf(groomPhase) * groom;
  const float spread = pose.legSpread + 0.22f * wide;
  for (int s = 0; s < 2; s++) {
    float sgn = s ? -1.0f : 1.0f;
    for (int i = 0; i < 3; i++) {
      float hxx = sgn * LEG[i][0], hyy = LEG[i][1];
      float kxx = sgn * LEG[i][2], kyy = LEG[i][3];
      float fxx = sgn * LEG[i][4], fyy = LEG[i][5];
      if (spread > 0.002f) {
        fxx *= 1.0f + 0.26f * spread;  fyy += 0.04f * spread;
        kxx *= 1.0f + 0.14f * spread;
      }
      if (tuck > 0.002f) {
        // Stagger the tuck per pair so the legs stack under the body instead
        // of collapsing into one blob.
        float tkx = sgn * (0.30f + 0.05f * i), tky = 0.98f + 0.05f * i;
        float tfx = sgn * (0.21f + 0.06f * i), tfy = 1.14f + 0.06f * i;
        kxx += (tkx - kxx) * tuck;  kyy += (tky - kyy) * tuck;
        fxx += (tfx - fxx) * tuck;  fyy += (tfy - fyy) * tuck;
      }
      if (i == 0 && groom > 0.002f) {
        float tkx = sgn * 0.62f, tky = 0.80f;                   // elbow up and out
        float tfx = sgn * 0.08f + rub * 0.07f, tfy = 0.66f;     // hands at the mouth
        kxx += (tkx - kxx) * groom;  kyy += (tky - kyy) * groom;
        fxx += (tfx - fxx) * groom;  fyy += (tfy - fyy) * groom;
      }
      if (i == 0 && grip > 0.002f) {
        // Up past the eyes and out, so the hands land on the screen edge the
        // body has just dropped below.
        float tkx = sgn * 0.98f, tky = 0.86f;
        float tfx = sgn * 1.04f + rub * 0.04f, tfy = 0.48f;
        kxx += (tkx - kxx) * grip;  kyy += (tky - kyy) * grip;
        fxx += (tfx - fxx) * grip;  fyy += (tfy - fyy) * grip;
      }
      Pt* L = g.legP[s * 3 + i];
      L[0] = body(hxx, hyy); L[1] = body(kxx, kyy); L[2] = body(fxx, fyy);
      if (i == 0) g.handP[s] = L[2];
    }
  }
  g.legT0 = 0.105f * scl; g.legT1 = 0.058f * scl;
  g.handR = grip * 0.15f * scl;

  // ---- the mouth. A few pixels wide and that is all: a dash that bends into
  // a smile or a frown, or opens into an O. Everything the fly feels is here
  // and in the antennae.
  const float curve = clampf(pose.mouthCurve + 0.55f * joy, -1.3f, 1.3f);
  const float mw  = MOUTH_W * pose.mouthWide * (1.0f + 0.22f * wide + 0.14f * joy);
  const float sagM = 0.155f * curve * (1.0f + 0.25f * wide);
  for (int i = 0; i < MOUTH_N; i++) {
    float t = -1.0f + 2.0f * i / (float)(MOUTH_N - 1);
    g.mouthP[i] = hx(t * mw, MOUTH_Y + sagM * (1.0f - t * t));
  }
  g.mouthT = 0.042f * scl;
  const float op = clampf(pose.mouthOpen, 0.0f, 1.0f);
  g.mouthAlpha = 1.0f - 0.85f * op;
  g.openAlpha  = op;
  Pt mo = hx(0.0f, MOUTH_Y + 0.05f);
  g.mouthO = {mo.x, mo.y, (0.045f + 0.100f * op) * hx.sx, (0.045f + 0.125f * op) * hx.sy,
              hx.cs, hx.sn};

  // ---- the light. It is fixed above the person, so when the board tips and
  // the fly has not caught up yet, the highlight slides across the eyes.
  const float phi = -lightA;
  const float L0x = -0.40f, L0y = -0.64f;
  g.lightX = L0x * cosf(phi) - L0y * sinf(phi);
  g.lightY = L0x * sinf(phi) + L0y * cosf(phi);

  // The two halves of the head are shaded in one frame normalised to the whole
  // head, with each half's own centre offset into it. In pixels, because that
  // is what the rasteriser hands the shader.
  g.headIA  = HEAD_IA / hx.sx;
  g.headIB  = HEAD_IB / hx.sy;
  g.skullOY = SKULL_Y * hx.sy;
  g.chinOY  = CHIN_Y  * hx.sy;

  fxBuild(body, fxCur, fxAmt);

  // ---- what all of that covers, as a rotated box rather than a circle, so a
  // sitting fly does not dirty the whole screen. The symbol, when there is
  // one, reaches further up and out than the fly does.
  const float antUp = ANT_UP - ANT_REST * wide;
  float hxE = SOFT_SIDE + 0.06f, top = antUp, bot = EXT_DOWN;
  if (g.fxLive) {                       // a symbol reaches further up and out
    if (hxE < 2.34f) hxE = 2.34f;
    if (top < 2.78f) top = 2.78f;
  }
  const float hyE = (top + bot) * 0.5f;
  const float oy  = (bot - top) * 0.5f;
  Pt ctr = body(0.0f, oy);
  float ex = fabsf(hxE * body.sx * cs) + fabsf(hyE * body.sy * sn) + 3.0f;
  float ey = fabsf(hxE * body.sx * sn) + fabsf(hyE * body.sy * cs) + 3.0f;
  bx0 = (int)floorf(ctr.x - ex); bx1 = (int)ceilf(ctr.x + ex);
  by0 = (int)floorf(ctr.y - ey); by1 = (int)ceilf(ctr.y + ey);
}

// ------------------------------------------------------------- mood machine
// It picks its own mood from what the board is doing and, failing that, from
// whim. Anything asked for from outside wins until its hold runs out.
void chooseMood(float dt, unsigned long now, float spinR, float rough, int q) {
  if (moodHold > 0.0f) {
    moodHold -= dt;
    if (moodHold <= 0.0f) { moodForced = false; moodUntil = 0; }
  }
  if (foodPending) {
    if (now > foodBy) {
      foodPending = false;            // nobody came back for it
    } else if (state == SIT) {
      foodPending = false;
      askedMood = EATING; moodForced = true; moodHold = 1e9f;
      curMood = EATING; eatT = 0.0f;
      return;
    }
  }

  if (moodForced) { curMood = askedMood; return; }

  // A fly in the air has other things on its mind.
  if (state != SIT) { curMood = HAPPY; moodUntil = 0; return; }

  // Read the board first: these beat anything it came up with on its own.
  Mood fromBoard = MOOD_N;
  if (rough > 0.17f)                        fromBoard = ANGRY;
  else if (fabsf(spinR) > 0.28f)            fromBoard = CURIOUS;
  else if (q == 2 && motion::stillFor() > 2500) fromBoard = LETMEOUT;
  else if (motion::stillFor() > 25000)      fromBoard = SLEEPING;

  if (fromBoard != MOOD_N) {
    if (curMood != fromBoard) { curMood = fromBoard; moodUntil = now + 1200; nextWhim = now + 4000; }
    else moodUntil = now + 1200;               // keep it while the cause lasts
    return;
  }

  // Just landed: pleased with itself for a moment.
  if (joy > 0.45f) { curMood = HAPPY; moodUntil = now + 900; return; }

  if (moodUntil && now < moodUntil) return;    // still busy with the last one

  if (curMood != IDLE) { curMood = IDLE; moodUntil = 0; nextWhim = now + (unsigned long)randf(3000, 9000); return; }

  if (now > nextWhim) {
    // Nothing is happening, so it finds something to do. Eating and dancing
    // are the long ones; the rest are a moment's worth.
    static const Mood WHIM[] = {EATING, DANCING, EXCITED, HAPPY, CURIOUS, EATING};
    curMood = WHIM[random(0, 6)];
    moodUntil = now + (unsigned long)((curMood == EATING || curMood == DANCING)
                                        ? randf(4500, 7000) : randf(1600, 3000));
    nextWhim = moodUntil + (unsigned long)randf(4000, 11000);
    if (curMood == EATING) eatT = 0.0f;
  }
}

}  // namespace

// -------------------------------------------------------------------- setup
void begin() {
  // The palette off the design sheet, and not one colour more: a warm orange
  // body, a red compound eye, and a smoky warm wing. Everything else on the
  // screen is black.
  const uint32_t eyeC[]  = {0x6E1409, 0xB51F12, 0xFF3B18, 0xFF5425, 0xFF7A32};
  const float    eyeS[]  = {0.00f, 0.22f, 0.52f, 0.80f, 1.00f};
  const uint32_t headC[] = {0x4A210D, 0x9A4818, 0xD8802F, 0xFFAA60};
  const float    headS[] = {0.00f, 0.30f, 0.66f, 1.00f};
  const uint32_t bodyC[] = {0x3A1809, 0x8A3E14, 0xD87C2C};
  const float    bodyS[] = {0.00f, 0.52f, 1.00f};
  gfx::buildRamp(rampEye,  eyeC,  eyeS,  5);
  gfx::buildRamp(rampHead, headC, headS, 4);
  gfx::buildRamp(rampBody, bodyC, bodyS, 3);

  // The halo, with its falloff curve baked in so the pixel loop is a lookup.
  for (int i = 0; i < gfx::RAMP_N; i++) {
    float t = powf(i / (float)(gfx::RAMP_N - 1), 1.8f);
    rampGlow[i] = gfx::rgb((int)(0xD4 * t), (int)(0x2E * t), (int)(0x10 * t));
  }

  colWing   = gfx::rgb(0xC4, 0x9A, 0x78);
  colLimb   = gfx::rgb(0xFF, 0x8A, 0x35);
  colMouth  = gfx::rgb(0x2A, 0x10, 0x04);
  colAccent = gfx::rgb(0xFF, 0x6A, 0x2A);
  colFood   = gfx::rgb(0xFF, 0xC1, 0x5A);

  int q = 0;
  float ts;
  sitTarget(q, 0.0f, 0.0f, px, py, ts);
  scl = ts;
  ang = 0; sitAng = 0;
  unsigned long now = millis();
  nextHead = now + 900; nextGroom = now + 3500; nextFlick = now + 2600; nextHop = now + 6000;
  nextWhim = now + 4000;
  pose = POSE[IDLE];
  fxClear();
  buildGeometry();
}

void setMood(Mood m, float holdSec) {
  askedMood = m;
  moodForced = true;
  moodHold = holdSec > 0.0f ? holdSec : 1e9f;
  curMood = m;
  if (m == EATING) eatT = 0.0f;
}
void feed() {
  if (curMood == EATING) { eatT = 0.0f; return; }   // another crumb on the pile
  foodPending = true;
  foodBy = millis() + 8000;
}
bool eating() { return curMood == EATING; }

void autoMood() { moodForced = false; moodHold = 0.0f; moodUntil = 0; nextWhim = millis() + 1500; }
Mood mood() { return curMood; }
const char* moodName() { return MOOD_NAME[curMood]; }

// ------------------------------------------------------------------- update
void update(float dt) {
  if (dt > 0.12f) dt = 0.12f;
  tsec += dt;
  unsigned long now = millis();

  const float gAng  = motion::uprightAngle();
  const float snap  = motion::orientationAngle();
  const int   q     = motion::orientation();
  const float spinR = motion::spin();
  const float rough = motion::jolt();

  float tx, ty, ts;
  sitTarget(q, snap, wide, tx, ty, ts);
  const float dvx = -sinf(snap), dvy = cosf(snap);

  // ---- when to fly and when to come down
  const bool calm = fabsf(spinR) < 0.45f && rough < 0.17f;
  if (state == SIT) {
    // Turned well past the corner, spun, or shaken: it loses its footing.
    if (fabsf(spinR) > 1.05f || rough > 0.30f || fabsf(wrapPi(gAng - sitAng)) > 0.58f)
      takeoff(dvx, dvy);
  } else {
    stableMs = calm ? stableMs + dt * 1000.0f : 0.0f;
    if (state == FLY && stableMs > 360.0f) state = LAND;
    else if (state == LAND && !calm) state = FLY;
  }

  // ---- what it is feeling, and the pose that goes with it
  chooseMood(dt, now, spinR, rough, q);
  const Pose& want = POSE[curMood];
  const float pr = 5.0f;                       // moods arrive, they do not snap
  ease(pose.mouthCurve, want.mouthCurve, pr, dt);
  ease(pose.mouthOpen,  want.mouthOpen,  pr * 1.6f, dt);
  ease(pose.mouthWide,  want.mouthWide,  pr, dt);
  ease(pose.antLift,    want.antLift,    pr * 0.8f, dt);
  ease(pose.antSplay,   want.antSplay,   pr, dt);
  ease(pose.antAsym,    want.antAsym,    pr, dt);
  ease(pose.wingBeat,   want.wingBeat,   pr * 2.0f, dt);
  ease(pose.sink,       want.sink,       pr * 0.7f, dt);
  ease(pose.legSpread,  want.legSpread,  pr, dt);
  // Flight owns the wings whatever the mood says, and the symbol crossfades
  // rather than cutting, so a mood change never pops.
  const bool flying = (state != SIT);
  ease(pose.wingSet, flying ? 1.0f : want.wingSet, flying ? 9.0f : 6.0f, dt);
  // One symbol at a time: the old one fades out before the new one exists, so
  // a mood change never swaps a Z for a music note mid-air.
  if (want.fx != fxCur) {
    ease(fxAmt, 0.0f, 9.0f, dt);
    if (fxAmt < 0.05f) fxCur = want.fx;
  } else {
    ease(fxAmt, fxCur == FX_NONE ? 0.0f : 1.0f, 6.0f, dt);
  }

  fxPhase += dt * (curMood == DANCING ? 0.85f : (curMood == SLEEPING ? 0.30f : 0.5f));
  if (fxPhase > 1.0f) fxPhase -= 1.0f;
  ease(grip, curMood == LETMEOUT ? 1.0f : 0.0f, 4.0f, dt);
  ease(sway, curMood == DANCING ? sinf(tsec * 4.4f) * 0.15f : 0.0f, 8.0f, dt);
  if (curMood == EATING) {
    eatT = clampf(eatT + dt * 0.22f, 0.0f, 1.0f);
    if (moodForced && eatT >= 1.0f) setMood(HAPPY, 1.6f);   // pleased, then back to its own life
  }

  // ---- where it is trying to be
  float wantX, wantY, wantAng, k, damp;
  if (state == FLY) {
    wander += dt;
    // Two slow waves per axis, so it drifts rather than orbiting.
    float wxr = 0.5f * sinf(wander * 1.70f) + 0.5f * sinf(wander * 0.73f + 1.3f);
    float wyr = 0.5f * sinf(wander * 1.31f + 2.1f) + 0.5f * sinf(wander * 0.57f + 0.4f);
    float clear = 1.90f * scl;
    wantX = LCD_W * 0.5f + wxr * fmaxf(14.0f, LCD_W * 0.5f - clear);
    wantY = LCD_H * 0.5f + wyr * fmaxf(14.0f, LCD_H * 0.5f - clear);
    // Bank into the turn, like anything that flies.
    float vLocal = vx * cosf(ang) + vy * sinf(ang);
    wantAng = gAng + clampf(-vLocal * 0.0026f, -0.42f, 0.42f);
    k = 21.0f; damp = 3.9f;
  } else {
    // The mood can sink the fly toward the floor - and, trying to get out, all
    // the way past it, so only the top of it is left on the screen.
    wantX = tx + dvx * pose.sink * scl;
    wantY = ty + dvy * pose.sink * scl;
    // Sitting, it leans a little with the board before giving up and flying.
    wantAng = snap + (state == SIT ? clampf(wrapPi(gAng - snap), -0.26f, 0.26f) * 0.30f : 0.0f);
    k = (state == LAND) ? 96.0f : 150.0f;
    damp = (state == LAND) ? 9.0f : 13.0f;      // underdamped on the way down: it snaps
  }

  spring(px, vx, wantX, k, damp, dt);
  spring(py, vy, wantY, k, damp, dt);

  // Angles are sprung on the shortest way round, then unwrapped, so spinning
  // the board through 360 degrees never makes the fly unwind the long way.
  float aErr = wrapPi(wantAng - ang);
  angV += aErr * (state == FLY ? 30.0f : 105.0f) * dt;
  angV -= angV * clampf((state == FLY ? 5.0f : 10.0f) * dt, 0.0f, 1.0f);
  ang += angV * dt;

  spring(scl, sclV, ts, 60.0f, 11.0f, dt);

  if (state == LAND) {
    float near2 = (px - tx) * (px - tx) + (py - ty) * (py - ty);
    float speed2 = vx * vx + vy * vy;
    if (near2 < 90.0f && speed2 < 2600.0f && fabsf(aErr) < 0.16f) land();
  }

  // ---- the body's own springs
  ease(blur, flying ? 1.0f : 0.0f, flying ? 16.0f : 7.0f, dt);
  ease(tuck, state == FLY ? 0.85f : 0.0f, 7.0f, dt);
  ease(wide, (q & 1) ? 1.0f : 0.0f, 4.5f, dt);
  ease(joy, 0.0f, 1.4f, dt);
  ease(lightA, clampf(wrapPi(gAng - ang), -0.85f, 0.85f), 7.0f, dt);

  // Breathing, plus whatever squash the last impact left over.
  spring(sqz, sqzV, 0.0f, 150.0f, 12.0f, dt);
  spring(hop, hopV, 0.0f, 190.0f, 13.0f, dt);

  // ---- head. It drifts about on its own and tips with the board.
  if (state == SIT) {
    if (now > nextHead) {
      headWant = randf(-0.17f, 0.17f);
      nextHead = now + (unsigned long)randf(1700, 4300);
    }
  } else {
    headWant = 0.0f;
  }
  float headT = headWant + clampf(wrapPi(gAng - ang), -0.3f, 0.3f) * 0.40f;
  headT *= (1.0f - 0.65f * groom);                  // it looks down at its hands
  if (curMood == CURIOUS) headT += 0.12f;           // a cocked head goes with the question mark
  spring(head, headV, headT, 44.0f, 6.6f, dt);

  // Antennae trail the head turn and settle after it: secondary motion, which
  // is most of what makes a small movement read as alive.
  float antT = clampf(-headV * 0.055f - angV * 0.030f, -0.30f, 0.30f);
  if (state == FLY) antT += sinf(tsec * 11.0f) * 0.035f;
  if (curMood == DANCING) antT += sinf(tsec * 8.8f) * 0.10f;
  spring(ant, antV, antT, 120.0f, 9.0f, dt);
  spring(flick, flickV, 0.0f, 260.0f, 12.0f, dt);

  // ---- idle business, only when it is settled and nothing is happening
  if (state == SIT && curMood == IDLE && rough < 0.12f) {
    if (now > nextGroom) {
      groomEnd  = now + (unsigned long)randf(1500, 2600);
      nextGroom = groomEnd + (unsigned long)randf(6500, 13000);
    }
    if (now > nextFlick) { flickV += randf(3.0f, 5.5f); nextFlick = now + (unsigned long)randf(3500, 9000); }
    if (now > nextHop)   { hopV += randf(-30.0f, -14.0f); sqzV += 1.1f; nextHop = now + (unsigned long)randf(5000, 11000); }
  } else {
    groomEnd = 0;
  }
  float groomT = (groomEnd && now < groomEnd) ? 1.0f : 0.0f;
  ease(groom, groomT, 9.0f, dt);
  if (groom > 0.05f) groomPhase += dt * 7.4f * (float)TWO_PI;

  // Eating chews; dancing bounces.
  float extra = 0.0f;
  if (curMood == EATING && eatT < 1.0f) extra += fabsf(sinf(tsec * 7.0f)) * 0.030f;
  if (curMood == DANCING)               extra += sinf(tsec * 8.8f) * 0.022f;

  float breathe = sinf(tsec * 1.55f) * 0.016f;
  float saved = sqz;
  sqz = saved + breathe + extra;
  buildGeometry();
  sqz = saved;
}

// --------------------------------------------------------------------- draw
void draw(gfx::Band& b) {
  gfx::Veil wing{colWing, 0.50f};
  gfx::Flat mouth{colMouth};

  // Wings, behind everything else. In flight they are three faint copies fanned
  // apart, which is the honest way to draw a 200 Hz wingbeat at 30 fps.
  for (int s = 0; s < 2; s++) {
    const Ell& e = g.wing[s];
    for (int k = 0; k < g.ghosts; k++) {
      float off = (g.ghosts == 1) ? 0.0f : (k - 1) * g.ghostStep;
      float c = e.cs, sn = e.sn;
      if (off != 0.0f) { float co = cosf(off), so = sinf(off); c = e.cs * co - e.sn * so; sn = e.cs * so + e.sn * co; }
      gfx::fillEllipse(b, e.cx, e.cy, e.ra, e.rb, c, sn, g.wingAlpha, wing);
    }
  }

  // The halo, once around the head and once around each eye, so it follows the
  // silhouette. It goes over the wings, which is what makes them look lit.
  const float padH = GLOW_PAD_HEAD * scl, padE = GLOW_PAD_EYE * scl;
  gfx::fillGlow(b, g.skull.cx, g.skull.cy, g.skull.ra + padH, g.skull.rb + padH,
                g.skull.cs, g.skull.sn, GLOW_K_HEAD, rampGlow);
  for (int s = 0; s < 2; s++)
    gfx::fillGlow(b, g.eye[s].cx, g.eye[s].cy, g.eye[s].ra + padE, g.eye[s].rb + padE,
                  g.eye[s].cs, g.eye[s].sn, GLOW_K_EYE, rampGlow);

  // Middle and hind legs go behind the body, the front pair in front of it.
  for (int i = 0; i < 6; i++) {
    if (i % 3 == 0) continue;
    gfx::strokePoly(b, g.legP[i], LEG_N, g.legT0, g.legT1, colLimb, 1.0f);
  }

  gfx::Sphere bodySh{rampBody, 1.0f / g.body.ra, 1.0f / g.body.rb,
                     g.lightX * 0.8f, g.lightY * 0.45f, 0.90f, 0.44f, 0.34f, 0.3f, 0.22f, 0.0f};
  gfx::fillEllipse(b, g.body.cx, g.body.cy, g.body.ra, g.body.rb,
                   g.body.cs, g.body.sn, 1.0f, bodySh);

  // The head is two ellipses sharing one shading frame, so the overlap does
  // not show. `oy` is where each of them sits in that frame.
  gfx::Sphere skull{rampHead, g.headIA, g.headIB,
                    g.lightX * 0.50f, g.lightY * 0.30f, 0.98f, 0.60f, 0.26f, 0.22f, 0.05f,
                    g.skullOY};
  gfx::Sphere chin = skull;
  chin.oy = g.chinOY;
  gfx::fillEllipse(b, g.chin.cx, g.chin.cy, g.chin.ra, g.chin.rb,
                   g.chin.cs, g.chin.sn, 1.0f, chin);
  gfx::fillEllipse(b, g.skull.cx, g.skull.cy, g.skull.ra, g.skull.rb,
                   g.skull.cs, g.skull.sn, 1.0f, skull);

  // The eyes are lit from outside on each side rather than from one point, the
  // way the sheet draws them; the board's tilt still slides the highlight.
  for (int s = 0; s < 2; s++) {
    const Ell& e = g.eye[s];
    float sgn = s ? -1.0f : 1.0f;
    float Lx = clampf(sgn * 0.45f + g.lightX * 0.30f, -0.85f, 0.85f);
    gfx::Compound eye{{rampEye, 1.0f / e.ra, 1.0f / e.rb,
                       Lx, g.lightY * 0.86f, 0.62f, 0.30f, 0.42f, 0.5f, 0.18f, 0.0f},
                      1.05f, 1.0f / 900.0f};
    gfx::fillEllipse(b, e.cx, e.cy, e.ra, e.rb, e.cs, e.sn, 1.0f, eye);
  }

  for (int s = 0; s < 2; s++)
    gfx::strokePoly(b, g.antP[s], ANT_N, g.antT0, g.antT1, colLimb, 1.0f);

  // The mouth crossfades between the line and the open O so a gasp does not pop.
  if (g.mouthAlpha > 0.02f)
    gfx::strokePoly(b, g.mouthP, MOUTH_N, g.mouthT, g.mouthT, colMouth, g.mouthAlpha);
  if (g.openAlpha > 0.02f)
    gfx::fillEllipse(b, g.mouthO.cx, g.mouthO.cy, g.mouthO.ra, g.mouthO.rb,
                     g.mouthO.cs, g.mouthO.sn, g.openAlpha, mouth);

  for (int i = 0; i < 6; i += 3)
    gfx::strokePoly(b, g.legP[i], LEG_N, g.legT0, g.legT1, colLimb, 1.0f);

  // Gripping the edge, the front feet become little hands.
  if (g.handR > 0.8f) {
    gfx::Flat hand{colLimb};
    for (int s = 0; s < 2; s++)
      gfx::fillEllipse(b, g.handP[s].x, g.handP[s].y, g.handR * 1.25f, g.handR * 0.78f,
                       1.0f, 0.0f, 1.0f, hand);
  }

  // The symbol last, over everything, so a Z is never half behind a wing.
  if (g.fxLive) {
    for (int i = 0; i < FX_SEG; i++)
      if (g.fxN[i] >= 2 && g.fxA[i] > 0.02f)
        gfx::strokePoly(b, g.fxP[i], g.fxN[i], g.fxT[i], g.fxT[i], g.fxC[i], g.fxA[i]);
    for (int i = 0; i < 2; i++)
      if (g.fxDotR[i] > 0.6f && g.fxDotA[i] > 0.02f) {
        gfx::Flat dot{g.fxDotC[i]};
        gfx::fillEllipse(b, g.fxDot[i].x, g.fxDot[i].y, g.fxDotR[i], g.fxDotR[i] * 0.86f,
                         1.0f, 0.0f, g.fxDotA[i], dot);
      }
  }
}

void bbox(int& x0, int& y0, int& x1, int& y1) { x0 = bx0; y0 = by0; x1 = bx1; y1 = by1; }

const char* stateName() { return state == SIT ? "sit" : (state == FLY ? "fly" : "land"); }

}  // namespace fly
