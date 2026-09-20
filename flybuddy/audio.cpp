// Speaker output: I2S -> ES8311 -> NS4150B amp.
// The pin map and the codec register sequence come from the cheeko-gotchi board
// notes (OSTB_XIAOZHI_V1.2) by way of the deskbuddy firmware, and match what we
// measured on this unit. See ../context/hardware.md.
//
// The task below is the only thing that ever writes to I2S. It blocks inside
// i2s_channel_write until the DMA has room, which is what paces it: it wakes
// exactly often enough to keep 16 kHz fed and does nothing else. The amp is
// powered only while the fly is actually making a noise, because the board
// hisses audibly with it enabled and silent.
#include "audio.h"
#include <Arduino.h>
#include <Wire.h>
#include <math.h>
#include <string.h>
#include <driver/i2s_std.h>
#include <freertos/FreeRTOS.h>
#include "board_config.h"
#include "song.h"

namespace audio {
namespace {

const uint32_t SAMPLE_RATE = 16000;
const uint8_t  ES8311_ADDR = 0x18;
const int      BLOCK       = 128;     // 8 ms at 16 kHz

i2s_chan_handle_t tx = nullptr;
volatile bool  ok = false;
volatile float volume = 0.8f;
volatile bool  isMuted = false;
volatile float loudness = 0.0f;

void reg(uint8_t r, uint8_t v) {
  Wire.beginTransmission(ES8311_ADDR);
  Wire.write(r);
  Wire.write(v);
  Wire.endTransmission();
}

// DAC-only setup for 16-bit / 16 kHz / 4.096 MHz MCLK. Taken as-is from
// deskbuddy, where it is known to work on this board; not worth rediscovering.
bool initCodec() {
  // Shared bus: motion:: brings it up too, and Wire.begin() is idempotent on
  // the ESP32, so neither driver has to care which of them ran first.
  Wire.begin(I2C_SDA, I2C_SCL, 400000);
  Wire.beginTransmission(ES8311_ADDR);
  if (Wire.endTransmission() != 0) return false;     // nobody home at 0x18
  const uint8_t seq[][2] = {
    {0x00, 0x1f}, {0x00, 0x00}, {0x00, 0x80}, {0x01, 0x3f}, {0x02, 0x00},
    {0x03, 0x10}, {0x04, 0x10}, {0x05, 0x00}, {0x06, 0x03}, {0x07, 0x00},
    {0x08, 0xff}, {0x09, 0x0c}, {0x0a, 0x0c}, {0x0d, 0x01}, {0x0e, 0x02},
    {0x12, 0x00}, {0x13, 0x10}, {0x1c, 0x6a}, {0x31, 0x00},
    {0x32, 0xbf},   // DAC volume
    {0x37, 0x08},
  };
  for (size_t i = 0; i < sizeof(seq) / sizeof(seq[0]); i++) {
    reg(seq[i][0], seq[i][1]);
    if (i == 0) delay(20);      // reset needs a moment
  }
  return true;
}

// Core 0, alongside the SPI sender. Core 1 is left alone to draw.
void audioTask(void*) {
  static int16_t mono[BLOCK];
  static int16_t frames[BLOCK * 2];
  bool ampOn = false;
  int  tailBlocks = 0;          // keep the amp up briefly after the last sound

  for (;;) {
    song::render(mono, BLOCK);

    // Is there anything in this block? song:: fades to zero over 4 ms when a
    // voice ends, so this goes quiet a little after the fly does.
    uint32_t peak = 0, sum = 0;
    for (int i = 0; i < BLOCK; i++) {
      const uint32_t a = abs(mono[i]);
      if (a > peak) peak = a;
      sum += a;
    }
    const bool live = !isMuted && peak > 24;

    if (live) tailBlocks = 12;               // ~100 ms
    else if (tailBlocks > 0) tailBlocks--;

    const bool want = live || tailBlocks > 0;
    if (want != ampOn) {
      digitalWrite(PIN_PA_CTRL, want ? HIGH : LOW);
      ampOn = want;
    }

    loudness = loudness * 0.7f + (sum / (float)BLOCK / 32768.0f) * 3.0f * 0.3f;
    if (loudness > 1.0f) loudness = 1.0f;

    const float g = isMuted ? 0.0f : volume;
    for (int i = 0; i < BLOCK; i++) {
      int32_t v = (int32_t)(mono[i] * g);
      if (v >  32767) v =  32767;
      if (v < -32768) v = -32768;
      frames[i * 2] = frames[i * 2 + 1] = (int16_t)v;   // mono out to both slots
    }

    size_t written = 0;
    i2s_channel_write(tx, frames, sizeof(frames), &written, portMAX_DELAY);
  }
}

}  // namespace

bool begin() {
  pinMode(PIN_PA_CTRL, OUTPUT);
  digitalWrite(PIN_PA_CTRL, LOW);        // silent until there is something to say

  i2s_chan_config_t chan = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  chan.auto_clear = true;                // zero the DMA on underrun: never loops
  if (i2s_new_channel(&chan, &tx, nullptr) != ESP_OK) return false;

  i2s_std_config_t cfg = {
    .clk_cfg  = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
    .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT,
                                                    I2S_SLOT_MODE_STEREO),
    .gpio_cfg = {
      .mclk = (gpio_num_t)PIN_I2S_MCLK,
      .bclk = (gpio_num_t)PIN_I2S_BCLK,
      .ws   = (gpio_num_t)PIN_I2S_LRCK,
      .dout = (gpio_num_t)PIN_I2S_DOUT,
      .din  = I2S_GPIO_UNUSED,           // no capture here; the mic is not used
      .invert_flags = {false, false, false},
    },
  };
  cfg.clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_256;      // 4.096 MHz
  if (i2s_channel_init_std_mode(tx, &cfg) != ESP_OK) return false;
  if (i2s_channel_enable(tx) != ESP_OK) return false;

  if (!initCodec()) return false;
  song::begin((float)SAMPLE_RATE);

  xTaskCreatePinnedToCore(audioTask, "voice", 3072, nullptr, 3, nullptr, 0);
  ok = true;
  return true;
}

bool  ready() { return ok; }
void  setVolume(float v) { volume = v < 0 ? 0 : (v > 1 ? 1 : v); }
void  setMute(bool m) { isMuted = m; }
bool  muted() { return isMuted; }
float level() { return loudness; }

}  // namespace audio
