// Board: OSTB_XIAOZHI_V1.2 ("Cheeko Gotchi"), ESP32-S3.
// Pins decoded from the factory firmware and cross-checked against the board
// notes. See ../context/hardware.md.
#pragma once

// ---- Display: JD9853 over SPI -------------------------------------------
#define LCD_SCLK   9
#define LCD_MOSI   10
#define LCD_CS     14
#define LCD_DC     8
#define LCD_RST    18     // factory firmware uses 18; board notes say 17. 18 works here.
#define LCD_BL     13     // backlight, HIGH = on
#define LCD_SPI_HZ 80000000   // factory used 40 MHz; 80 MHz doubles the frame rate

// The panel really is 240x296 portrait. The factory init table only opened a
// 240x284 window, which is why it left a stale band along one edge.
#define LCD_W      240
#define LCD_H      296
#define LCD_X_GAP  0
#define LCD_Y_GAP  0
#define LCD_MADCTL 0x00   // portrait, no mirroring, no axis swap

// ---- I2C ----------------------------------------------------------------
// touch 0x15 (CST810, dead on this unit), speaker 0x18 (ES8311),
// motion 0x19 (LIS2DH12), mic 0x40 (ES7210)
#define I2C_SDA    12
#define I2C_SCL    11

// ---- Audio: ESP32 is I2S master, ES8311 codec -> NS4150B amp -> 4 ohm speaker
#define PIN_PA_CTRL   4    // amp enable, HIGH = on. Must be LOW at rest or it hisses.
#define PIN_I2S_MCLK  5    // 4.096 MHz (256 x 16 kHz)
#define PIN_I2S_DOUT  6    // ESP32 -> ES8311 (playback)
#define PIN_I2S_DIN   7    // ES7210 -> ESP32 (capture, unused here)
#define PIN_I2S_BCLK  15
#define PIN_I2S_LRCK  16

// ---- Buttons (not used yet, kept so the pins stay written down) ---------
#define BTN_VOL_DOWN  39   // "-", active LOW
#define BTN_VOL_UP    40   // "+", active LOW
#define BTN_POWER_KEY 3    // middle, active HIGH

// NEVER drive GPIO 2: it is the power-off latch and driving it HIGH cuts power.

// ---- Renderer -----------------------------------------------------------
// One scratch band instead of a whole framebuffer. A full 240x296 canvas is
// 142 KB; this is 15 KB and the fly usually dirties far less than the screen.
#define BAND_PIXELS   (LCD_W * 32)

// Frame pacing. 22 ms caps us at ~45 fps, which the panel can just about take
// on a full-screen redraw and beats comfortably when the fly is sitting still.
#define FRAME_MS      22
