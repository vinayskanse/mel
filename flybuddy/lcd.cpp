#include "lcd.h"
#include <SPI.h>

namespace lcd {
namespace {

SPISettings spiSettings(LCD_SPI_HZ, MSBFIRST, SPI_MODE0);
bool inBlit = false;

struct InitCmd {
  uint8_t cmd;
  uint8_t len;
  uint8_t data[32];
  uint16_t delayMs;
};

// Extracted from the factory firmware. Entries that pointed at zero-initialised
// bytes are sent as 0x00.
const InitCmd kInit[] = {
  {0xDF, 2, {0x98, 0x53}, 0},
  {0xDE, 1, {0x00}, 0},
  {0xB2, 1, {0x25}, 0},
  {0xB7, 4, {0x00, 0x21, 0x00, 0x49}, 0},
  {0xBB, 6, {0x1F, 0x9A, 0x55, 0x73, 0x63, 0xF0}, 0},
  {0xC0, 2, {0x22, 0x22}, 0},
  {0xC1, 1, {0x12}, 0},
  {0xC3, 8, {0x7D, 0x07, 0x14, 0x06, 0xC8, 0x6A, 0x6C, 0x77}, 0},
  {0xC4, 12, {0x00, 0x00, 0xA0, 0x6F, 0x1E, 0x1A, 0x16, 0x79, 0x1E, 0x1A, 0x16, 0x82}, 0},
  {0xC8, 32, {0x3F, 0x2C, 0x26, 0x20, 0x25, 0x26, 0x21, 0x21, 0x1F, 0x1F, 0x1F, 0x13, 0x11, 0x0B, 0x04, 0x00,
              0x3F, 0x2C, 0x26, 0x20, 0x25, 0x27, 0x21, 0x21, 0x1F, 0x1F, 0x1F, 0x13, 0x11, 0x0B, 0x04, 0x00}, 0},
  {0xD0, 5, {0x04, 0x06, 0x62, 0x0F, 0x00}, 0},
  {0xD7, 2, {0x00, 0x30}, 0},
  {0xE6, 1, {0x14}, 0},
  {0xDE, 1, {0x01}, 0},
  {0xB7, 5, {0x03, 0x13, 0xEF, 0x35, 0x35}, 0},
  {0xC1, 3, {0x14, 0x15, 0xC0}, 0},
  {0xC2, 3, {0x06, 0x3A, 0xC7}, 0},
  {0xC4, 2, {0x72, 0x12}, 0},
  {0xBE, 1, {0x00}, 0},
  {0xDE, 1, {0x00}, 0},
  {0x35, 1, {0x00}, 0},
  {0x36, 1, {0x00}, 0},
  {0x3A, 1, {0x05}, 0},
  {0x2A, 4, {0x00, 0x00, 0x00, 0xEF}, 0},
  {0x2B, 4, {0x00, 0x00, 0x01, 0x1B}, 0},
  {0x11, 0, {}, 120},
  {0x29, 0, {}, 50},
};

void writeCmd(uint8_t cmd, const uint8_t* data, size_t len) {
  SPI.beginTransaction(spiSettings);
  digitalWrite(LCD_CS, LOW);
  digitalWrite(LCD_DC, LOW);
  SPI.write(cmd);
  if (len) {
    digitalWrite(LCD_DC, HIGH);
    SPI.writeBytes(data, len);
  }
  digitalWrite(LCD_CS, HIGH);
  SPI.endTransaction();
}

}  // namespace

void begin() {
  pinMode(LCD_BL, OUTPUT);
  digitalWrite(LCD_BL, LOW);       // stay dark until there is something to show
  pinMode(LCD_CS, OUTPUT);
  digitalWrite(LCD_CS, HIGH);
  pinMode(LCD_DC, OUTPUT);
  pinMode(LCD_RST, OUTPUT);
  SPI.begin(LCD_SCLK, -1, LCD_MOSI, -1);

  digitalWrite(LCD_RST, LOW);
  delay(10);
  digitalWrite(LCD_RST, HIGH);
  delay(120);

  for (const InitCmd& c : kInit) {
    writeCmd(c.cmd, c.data, c.len);
    if (c.delayMs) delay(c.delayMs);
  }

  writeCmd(0x20, nullptr, 0);      // no inversion: this panel is already right
  uint8_t madctl = LCD_MADCTL;
  writeCmd(0x36, &madctl, 1);
  writeCmd(0x29, nullptr, 0);
}

void backlight(bool on) { digitalWrite(LCD_BL, on ? HIGH : LOW); }

void beginBlit(int x0, int y0, int x1, int y1) {
  x0 = constrain(x0, 0, LCD_W - 1);
  x1 = constrain(x1, x0, LCD_W - 1);
  y0 = constrain(y0, 0, LCD_H - 1);
  y1 = constrain(y1, y0, LCD_H - 1);
  uint16_t cx0 = x0 + LCD_X_GAP, cx1 = x1 + LCD_X_GAP;
  uint16_t ry0 = y0 + LCD_Y_GAP, ry1 = y1 + LCD_Y_GAP;
  uint8_t ca[] = {uint8_t(cx0 >> 8), uint8_t(cx0), uint8_t(cx1 >> 8), uint8_t(cx1)};
  uint8_t ra[] = {uint8_t(ry0 >> 8), uint8_t(ry0), uint8_t(ry1 >> 8), uint8_t(ry1)};
  writeCmd(0x2A, ca, 4);
  writeCmd(0x2B, ra, 4);

  // Hold CS low and DC high for the whole rectangle so the bands stream out
  // back to back with no per-band command overhead.
  SPI.beginTransaction(spiSettings);
  digitalWrite(LCD_CS, LOW);
  digitalWrite(LCD_DC, LOW);
  SPI.write(0x2C);                 // RAMWR
  digitalWrite(LCD_DC, HIGH);
  inBlit = true;
}

void pushPixels(const uint16_t* be, size_t count) {
  if (!inBlit || !count) return;
  SPI.writeBytes((const uint8_t*)be, count * 2);
}

void endBlit() {
  if (!inBlit) return;
  digitalWrite(LCD_CS, HIGH);
  SPI.endTransaction();
  inBlit = false;
}

void fillScreen(uint16_t color) {
  static uint16_t row[LCD_W];
  uint16_t be = __builtin_bswap16(color);
  for (int x = 0; x < LCD_W; x++) row[x] = be;
  beginBlit(0, 0, LCD_W - 1, LCD_H - 1);
  for (int y = 0; y < LCD_H; y++) pushPixels(row, LCD_W);
  endBlit();
}

}  // namespace lcd
