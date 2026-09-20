// FlyBuddy - one happy fruit fly living on the Cheeko Gotchi board.
//
// It sits at the bottom of the screen, breathes, looks around, and rubs its
// front legs together. Turn the board and it loses its footing and flies; hold
// it still and it snaps back down onto whichever edge is now the floor. In
// landscape it has more room, so it sits bigger and grins wider.
//
// The display driver and the accelerometer driver came from the deskbuddy
// firmware in this repo's history; the renderer and the fly are new.
//
// Nothing here allocates: the whole frame goes out through one 15 KB band.
#include <Arduino.h>
#include <Wire.h>
#include "board_config.h"
#include "lcd.h"
#include "gfx.h"
#include "motion.h"
#include "fly.h"
#include "audio.h"
#include "voice.h"
#include "buttons.h"

// The only frame memory in the program. A full 240x296 canvas would be 142 KB;
// this is two bands of 15 KB. Two, because one is being pushed down the SPI bus
// by the other core while this one is being drawn into.
static uint16_t band[2][BAND_PIXELS];

struct BandJob { uint16_t* px; size_t n; };
static QueueHandle_t jobQ;
static SemaphoreHandle_t freeSem;

// Pinned to core 0. Pushing pixels is not DMA here, it is the CPU feeding the
// SPI FIFO, so it really does cost a core - which is exactly why it is worth
// giving it the one that would otherwise be idle.
static void senderTask(void*) {
  BandJob j;
  for (;;)
    if (xQueueReceive(jobQ, &j, portMAX_DELAY) == pdTRUE) {
      lcd::pushPixels(j.px, j.n);
      xSemaphoreGive(freeSem);
    }
}

static unsigned long lastFrame = 0;
static int pvx0 = 0, pvy0 = 0, pvx1 = LCD_W - 1, pvy1 = LCD_H - 1;
static bool firstFrame = true;

// Draw and send one frame. Only the rectangle the fly covered last frame or
// covers this frame is touched; the rest of the screen is already black.
static void renderFrame(uint32_t& drawUs, uint32_t& sendUs) {
  int x0, y0, x1, y1;
  fly::bbox(x0, y0, x1, y1);

  if (firstFrame) { x0 = 0; y0 = 0; x1 = LCD_W - 1; y1 = LCD_H - 1; firstFrame = false; }
  else { x0 = min(x0, pvx0); y0 = min(y0, pvy0); x1 = max(x1, pvx1); y1 = max(y1, pvy1); }

  fly::bbox(pvx0, pvy0, pvx1, pvy1);
  pvx0 = constrain(pvx0, 0, LCD_W - 1); pvx1 = constrain(pvx1, 0, LCD_W - 1);
  pvy0 = constrain(pvy0, 0, LCD_H - 1); pvy1 = constrain(pvy1, 0, LCD_H - 1);

  x0 = constrain(x0, 0, LCD_W - 1); x1 = constrain(x1, x0, LCD_W - 1);
  y0 = constrain(y0, 0, LCD_H - 1); y1 = constrain(y1, y0, LCD_H - 1);

  const int w = x1 - x0 + 1;
  int rows = BAND_PIXELS / w;
  if (rows < 1) rows = 1;

  lcd::beginBlit(x0, y0, x1, y1);
  int cur = 0;
  for (int y = y0; y <= y1; y += rows) {
    const int h = min(rows, y1 - y + 1);
    const size_t n = (size_t)w * h;

    uint32_t t0 = micros();
    xSemaphoreTake(freeSem, portMAX_DELAY);       // wait for a band to come free
    sendUs += micros() - t0;                      // time spent waiting on the panel

    t0 = micros();
    uint16_t* buf = band[cur];
    memset(buf, 0, n * 2);
    gfx::Band b{buf, (int16_t)x0, (int16_t)y, (int16_t)w, (int16_t)h};
    fly::draw(b);
    for (size_t i = 0; i < n; i++) buf[i] = __builtin_bswap16(buf[i]);
    drawUs += micros() - t0;

    BandJob j{buf, n};
    xQueueSend(jobQ, &j, portMAX_DELAY);
    cur ^= 1;
  }
  // Both bands back in hand means the panel has had the lot.
  xSemaphoreTake(freeSem, portMAX_DELAY);
  xSemaphoreTake(freeSem, portMAX_DELAY);
  xSemaphoreGive(freeSem);
  xSemaphoreGive(freeSem);
  lcd::endBlit();
}

void setup() {
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);        // never block the draw loop waiting for a reader

  lcd::begin();
  lcd::fillScreen(0x0000);
  lcd::backlight(true);

  gfx::begin();
  randomSeed(esp_random());
  fly::begin();

  jobQ = xQueueCreate(4, sizeof(BandJob));
  freeSem = xSemaphoreCreateCounting(2, 2);
  xTaskCreatePinnedToCore(senderTask, "blit", 3072, nullptr, 3, nullptr, 0);

  const bool a = audio::begin();
  voice::begin();
  buttons::begin();

  bool m = motion::begin();
  Serial.printf("flybuddy: motion %s, audio %s, band %u B, free heap %u B\n",
                m ? "ok" : "MISSING", a ? "ok" : "MISSING",
                (unsigned)sizeof(band), (unsigned)ESP.getFreeHeap());
  if (!a) Serial.println("flybuddy: no codec, the fly will be mute");
  if (!m) Serial.println("flybuddy: no accelerometer, the fly will just sit there");

  lastFrame = millis();
}

void loop() {
  motion::update();
  buttons::update();

  // "+" feeds it. It puts the crumb down wherever the fly is; if the fly is in
  // the air it finishes its flight and eats when it lands.
  if (buttons::pressedPlus()) {
    fly::feed();
    Serial.println("fly: fed");
  }
  // "-" twice mutes it. Once does nothing on purpose: a single press on a
  // volume key should not silence the thing by accident.
  if (buttons::doublePressedMinus()) {
    const bool m = !audio::muted();
    audio::setMute(m);
    Serial.printf("fly: %s\n", m ? "muted" : "unmuted");
  }

  const unsigned long now = millis();
  if (now - lastFrame < FRAME_MS) return;
  const float dt = (now - lastFrame) * 0.001f;
  lastFrame = now;

  fly::update(dt);
  voice::update(dt);      // reads the fly, tells the synthesiser what to sing

  static uint32_t drawUs = 0, sendUs = 0;
  renderFrame(drawUs, sendUs);

  // One line every couple of seconds: frame rate, where the time goes, and
  // that the heap is not moving.
  static unsigned long window = 0;
  static int frames = 0;
  static const char* lastState = "";
  frames++;
  if (now - window > 2000) {
    Serial.printf("fps %.1f  draw %lu us  wait %lu us  %s/%s  voice %s  heap %u\n",
                  frames * 1000.0f / (now - window), (unsigned long)(drawUs / frames),
                  (unsigned long)(sendUs / frames), fly::stateName(), fly::moodName(),
                  voice::name(), (unsigned)ESP.getFreeHeap());
    window = now; frames = 0; drawUs = sendUs = 0;
  }
  if (fly::stateName() != lastState) { lastState = fly::stateName(); Serial.printf("fly: %s\n", lastState); }
}
