// WiFi, discovery, and a socket that tells the fly what to do about a song.
//
// Discovery first, because it is the part that is not obvious. The board is
// never given the laptop's address. sim_server.py broadcasts "flybuddy <port>"
// to 255.255.255.255 twice a second; this listens on that port, takes the
// sender's address, and opens a TCP connection back to it. That is why there is
// no host in wifi_config.h and why the board survives a new DHCP lease, a
// different network or a restarted router without being reflashed.
//
// It also means a network with client isolation -- which guest WiFi often has,
// and which passes neither broadcast nor peer-to-peer traffic -- will never
// connect, and nothing can be done about that from this end. `status()` says
// which of the two it is stuck on, which is the whole reason it reports "wifi"
// and "looking" separately.
//
// Then the protocol, which is one line at a time, host to board:
//
//     MOOD <NAME> <seconds>    pull this face; 0 seconds holds it
//     AUTO                     stop overriding; go back to choosing your own
//     FEED                     a crumb goes down: it eats, then looks pleased
//     SAY <text>               the bubble's first line; empty clears it
//     SUB <text>               the bubble's second line
//     PING                     keep the socket honest
//
// Reading is non-blocking and bounded: at most a few lines per frame, out of
// whatever has arrived, so a chatty host cannot stretch a frame. The draw loop
// is 22 ms and this has to fit in the gaps.
#include "uplink.h"
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <string.h>
#include "bubble.h"
#include "fly.h"
#include "wifi_config.h"

namespace uplink {
namespace {

const uint16_t BEACON_PORT = 8023;
const unsigned long RETRY_MS = 2000;      // how often to try the address we have
const unsigned long QUIET_MS = 20000;     // no line in this long: the socket is dead
const int MAX_LINES_PER_FRAME = 8;

WiFiUDP beacon;
WiFiClient host;
IPAddress hostIp;
uint16_t hostPort = 0;
bool listening = false;
unsigned long nextTry = 0, lastLine = 0;
char line[160];
size_t fill = 0;

// The ten faces in fly.h, by the names the host sends. Kept in enum order, so
// the table and the enum are checked against each other by the compiler
// through the static_assert below rather than by eye.
const char* const MOOD_NAME[fly::MOOD_N] = {
  "IDLE", "HAPPY", "EXCITED", "EATING", "SLEEPING",
  "DANCING", "CURIOUS", "ANGRY", "LETMEOUT", "LOWBATT",
};
static_assert(fly::MOOD_N == 10, "a face was added to fly.h; name it here too");

bool moodFromName(const char* name, fly::Mood& out) {
  for (int i = 0; i < fly::MOOD_N; i++)
    if (!strcasecmp(name, MOOD_NAME[i])) { out = (fly::Mood)i; return true; }
  return false;
}

void listenForHost() {
  if (listening) return;
  listening = beacon.begin(BEACON_PORT);
  if (!listening) Serial.printf("link: cannot listen on udp %u\n", BEACON_PORT);
}

// One beacon packet, if there is one. It carries the port; the address is the
// sender's, which is the whole trick.
void readBeacon() {
  int size = beacon.parsePacket();
  if (size <= 0) return;
  char payload[32] = "";
  int n = beacon.read(payload, sizeof(payload) - 1);
  if (n <= 0) return;
  payload[n] = 0;
  unsigned port = 0;
  if (sscanf(payload, "flybuddy %u", &port) != 1 || port == 0 || port > 65535) return;
  const IPAddress from = beacon.remoteIP();
  if (from != hostIp || port != hostPort) {
    hostIp = from;
    hostPort = (uint16_t)port;
    nextTry = 0;                      // a new address is worth trying immediately
    Serial.printf("link: laptop announced itself at %s:%u\n",
                  hostIp.toString().c_str(), hostPort);
  }
}

void apply(char* text) {
  // strsep-style: the verb, then the rest of the line untouched, because a
  // song title has spaces in it and splitting on them would lose them.
  char* rest = strchr(text, ' ');
  if (rest) *rest++ = 0;
  else rest = text + strlen(text);

  if (!strcmp(text, "MOOD")) {
    char name[16] = "";
    float hold = 0.0f;
    if (sscanf(rest, "%15s %f", name, &hold) >= 1) {
      fly::Mood mood;
      if (moodFromName(name, mood)) {
        fly::setMood(mood, hold);
        Serial.printf("link: face %s%s\n", name,
                      hold > 0.0f ? " (briefly)" : "");
      } else {
        Serial.printf("link: no such face %s\n", name);
      }
    }
  } else if (!strcmp(text, "AUTO")) {
    fly::autoMood();
  } else if (!strcmp(text, "FEED")) {
    fly::feed();
    Serial.println("link: fed");
  } else if (!strcmp(text, "SAY")) {
    // SAY with nothing after it takes the whole band down. With text, it
    // changes only the title -- the artist keeps whatever SUB last said, so
    // the two lines can be set in either order and in separate messages.
    if (rest[0]) bubble::set(rest, nullptr);
    else bubble::clear();
  } else if (!strcmp(text, "SUB")) {
    bubble::set(nullptr, rest);
  } else if (!strcmp(text, "PING")) {
    host.println("PONG");
  }
}

void drop(const char* why) {
  if (host.connected() || host) {
    host.stop();
    Serial.printf("link: laptop gone (%s)\n", why);
  }
  fill = 0;
  bubble::clear();
  fly::autoMood();                    // it goes back to its own life
}

}  // namespace

void begin() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);               // a sleeping radio adds hundreds of ms to a face
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.printf("link: joining %s\n", WIFI_SSID);
}

void update() {
  if (WiFi.status() != WL_CONNECTED) {
    if (host) drop("wifi went");
    if (listening) { beacon.stop(); listening = false; }
    // The address is dropped with the network. Coming back up on a different
    // one and dialling the old laptop's old lease is the one way this could
    // sit there failing instead of finding it again.
    hostPort = 0;
    return;
  }
  listenForHost();
  readBeacon();

  if (!host.connected()) {
    if (!hostPort || millis() < nextTry) return;
    nextTry = millis() + RETRY_MS;
    // A short timeout: this runs inside the frame loop, and three seconds of
    // blocking connect would be 130 dropped frames. On a LAN a host that is
    // there answers in a few milliseconds.
    if (!host.connect(hostIp, hostPort, 400)) return;
    host.setNoDelay(true);
    host.printf("HELLO flybuddy\n");
    lastLine = millis();
    Serial.printf("link: connected to %s:%u\n", hostIp.toString().c_str(), hostPort);
    return;
  }

  for (int taken = 0; taken < MAX_LINES_PER_FRAME && host.available(); ) {
    const int c = host.read();
    if (c < 0) break;
    if (c == '\r') continue;
    if (c == '\n') {
      line[fill] = 0;
      if (fill) apply(line);
      fill = 0;
      lastLine = millis();
      taken++;
      continue;
    }
    if (fill < sizeof(line) - 1) line[fill++] = (char)c;
    // A line longer than the buffer is not truncated into a different command:
    // the overflow is dropped and the rest of the line with it, at the newline.
  }

  // Half-open sockets are the normal way a laptop leaves: it sleeps or its
  // WiFi drops and nothing ever arrives to say so. The host sends PING, so
  // silence for this long means the connection is gone whatever it claims.
  if (millis() - lastLine > QUIET_MS) drop("silent too long");
}

bool joined() { return WiFi.status() == WL_CONNECTED; }
bool connected() { return host.connected(); }

const char* status() {
  if (WiFi.status() != WL_CONNECTED) return "wifi";
  if (!host.connected()) return hostPort ? "dialling" : "looking";
  return "linked";
}

}  // namespace uplink
