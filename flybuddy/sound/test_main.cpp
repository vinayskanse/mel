// Renders each voice to a .wav on the Mac so the engine can be heard and
// measured without flashing the board.
#include "song.h"
#include <stdio.h>
#include <string.h>
#include <vector>
static void writeWav(const char* p, const std::vector<int16_t>& s, int sr) {
  FILE* f = fopen(p, "wb");
  uint32_t dn = s.size() * 2, rn = 36 + dn; uint16_t one = 1, bits = 16, ba = 2;
  uint32_t fs = 16, br = sr * 2;
  fwrite("RIFF", 1, 4, f); fwrite(&rn, 4, 1, f); fwrite("WAVEfmt ", 1, 8, f);
  fwrite(&fs, 4, 1, f); fwrite(&one, 2, 1, f); fwrite(&one, 2, 1, f);
  fwrite(&sr, 4, 1, f); fwrite(&br, 4, 1, f); fwrite(&ba, 2, 1, f); fwrite(&bits, 2, 1, f);
  fwrite("data", 1, 4, f); fwrite(&dn, 4, 1, f); fwrite(s.data(), 2, s.size(), f);
  fclose(f); printf("wrote %s  %.2fs\n", p, s.size() / (float)sr);
}
static void run(const char* path, song::Voice v, float secs, int sr) {
  song::begin(sr); song::play(v);
  std::vector<int16_t> buf((size_t)(secs * sr));
  song::render(buf.data(), buf.size());
  writeWav(path, buf, sr);
}
int main(int argc, char** argv) {
  const int sr = 16000;
  if (argc > 1 && !strcmp(argv[1], "--nopitch")) song::P.pitch = 1.0f;
  const char* tag = (argc > 1 && !strcmp(argv[1], "--nopitch")) ? "_raw" : "";
  char p[256];
  snprintf(p, sizeof p, "c_court%s.wav",   tag); run(p, song::COURT,   11.0f, sr);
  snprintf(p, sizeof p, "c_flight%s.wav",  tag); run(p, song::FLIGHT,   2.5f, sr);
  snprintf(p, sizeof p, "c_loom%s.wav",    tag); run(p, song::LOOM,     1.8f, sr);
  snprintf(p, sizeof p, "c_eat%s.wav",     tag); run(p, song::EAT,      1.5f, sr);
  snprintf(p, sizeof p, "c_takeoff%s.wav", tag); run(p, song::TAKEOFF,  1.5f, sr);
  return 0;
}
