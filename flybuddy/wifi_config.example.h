// Copy to wifi_config.h and fill in. wifi_config.h is gitignored: it holds a
// password.
//
// The host's address is deliberately absent. The board does not store one: it
// listens for the UDP broadcast that sim_server.py sends twice a second and
// takes the address from whoever sent it. Move the laptop to another network,
// get a different DHCP lease, restart the router -- the board finds it again
// without being reflashed. See link.cpp.
#pragma once

#define WIFI_SSID      "your network"
#define WIFI_PASSWORD  "your password"
