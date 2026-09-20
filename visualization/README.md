# The viewer, and everything wired into it

One page, one process, one fly. The connectome steps, the fly listens to
whatever is playing, and the board on the desk pulls a face about it — and all
three are the same fly, so a thing that happens to one happens to all of them.

```sh
python visualization/sim_server.py       # http://127.0.0.1:8010
```

That is the whole command. It brings up the brain, the ears, the page and the
board link together, because they are one animal and starting them separately
was the thing that made them feel like three demos.

## What is connected to what

```
   a song in the room                  a button on the page
           |                                    |
           v                                    |
   learning/ears.py                             |
   guess from memory, ask only if it must       |
           |                                    |
           v                                    |
   learning/events.py  ── the notice board ─────+
           |
           +──────────────┬──────────────┬─────────────────┐
           v              v              v                 v
      reactions.py    the brain      the board        the page
      what it means   a stimulus     a face, a        narration,
                      is driven      crumb, the       and the pathway
                                     bubble           draws itself
```

Everything crosses at `learning/events.py`, a local notice board with no
sockets in it. Nothing polls anything, and **no call was added to any external
service**: a song still costs at most one Shazam lookup in its life, exactly as
[`../learning/README.md`](../learning/README.md) describes.

## The table

`reactions.py` is the join, and it is a table on purpose — every row is a claim
that can be read and argued with.

| What happens | What the brain does | What the board does |
|---|---|---|
| Ears armed | — | curious face |
| Music starts | drives `sound` | curious |
| "Name it now" | drives `sound` | curious |
| Knows the song from memory | drives `sound` | dancing (excited, if it has heard it under three times) |
| Shazam just named it | drives `sound` | excited |
| Nobody could name it | drives `sound` | curious |
| **You agree — sweet** | **drives `sugar`** | **eating, and a crumb goes down** |
| You disagree — bitter | — | angry |
| The music stops | — | back to choosing its own face |

Two rules the table keeps to, and they are why some cells are empty:

**The brain column is anatomy.** A row drives a stimulus only where a real fly
has a sense organ for it. There is no "recognition" input and no "happiness"
input in a connectome, so those rows drive nothing rather than driving something
vaguely related. A thumbs-up is the exception that proves it: sweetness *is* a
real input, so agreeing with the fly drives the 17 sugar receptor neurons of the
right labellum through 24.5M synapses to MN9, the motor neuron that extends the
proboscis, with nothing scripted in between. Watch the MN9 meter when you press
it.

**The bitter row is empty on purpose.** This pack's labellar bitter cells are
not identified in `context/circuits.md`, and naming a cell type on a hunch would
put a false claim on screen. A thumbs-down moves the fly's confidence and its
face and leaves the connectome alone. When the right type is known, `find_types.py`
finds how the pack spells it and it becomes one line in `sim_server.STIMULI`.

## Two stimuli that may not exist

`sugar`, `water`, `smell` and `looming` name cells that `context/circuits.md`
verified against this pack. `sound` and `bitter` name cells from the literature
instead, so they are written as candidate lists and **a stimulus that resolves
to nothing is dropped rather than fatal** — the panel says which, and the page
says so where the missing drive would have been.

```sh
python visualization/find_types.py JO --counts     # what this pack calls the ear
python visualization/find_types.py LB --class sensory
```

`sound` prefers JO-B, the sub-population of Johnston's organ — the fly's
ear — tuned to courtship song. Failing that it settles for `AMMC-A1`, one
synapse further in, where JO terminates. The panel says which it got.

## The page

Two things it does on its own:

- **Full screen (`f`) takes the panel away.** There is nothing to click in full
  screen, so 252 px of controls is 252 px of brain not being shown. The fly card
  stays, because it is the one thing you keep using; the camera slides over to
  fill the space the panel gave up.
- **A stimulus traces itself.** Press Sugar — or agree with the fly's guess,
  which is the same thing — and the sugar → MN9 pathway draws itself over the
  live brain, each neuron lighting at the millisecond it actually first fired.
  The point cloud stays on and the brain keeps turning: the spikes and the route
  are the same event seen two ways, 27 ms of biological time apart. The camera
  leans in and leans back out on its own. Switch it off in the panel, or take it
  over with the manual trace.

## The board

The board is on the WiFi and holds one socket. It is never given an address:
`sim_server.py` broadcasts `flybuddy <port>` to the LAN twice a second and the
board dials whoever sent it, so a new DHCP lease or a different network needs no
reflash. See [`../flybuddy/uplink.cpp`](../flybuddy/uplink.cpp).

Host to board, one line at a time:

```
MOOD <NAME> <seconds>    pull this face; 0 seconds holds it
AUTO                     stop overriding; choose your own again
FEED                     a crumb: it eats, then looks pleased
SAY <text> / SUB <text>  the two lines of the bubble under its face
PING                     keep the socket honest
```

The board sends `FEED` in the other direction when its physical `+` button is
pressed. The crumb is handled on the board; the server uses the event to trigger
the sugar pathway on every connected visualization, including full screen.

**A guest network with client isolation passes neither broadcast nor
peer-to-peer traffic**, and then the board simply never connects. Nothing else
depends on it: the page and the brain do not know or care whether a board is
listening, and the fly on the desk goes on choosing its own moods from the
accelerometer exactly as it did before any of this existed.

## Tests

```sh
python -m unittest discover -s visualization -p 'test_*.py'
```

These run anywhere. `sim_server.py` cannot be imported without MLX, the pack and
an Apple GPU, which is why the rules worth testing live in `reactions.py`,
`flystate.py` and `device.py` instead, and are exercised there against a fake
simulator and a fake board.

## The files

| File | |
|---|---|
| `sim_server.py` | the hub: the brain's thread, the page's socket, the ears, the board |
| `live_engine.py` | the connectome, stepping in chunks, with a drive that can change mid-run |
| `reactions.py` | the table above: one event in, what the brain and the body do about it |
| `flystate.py` | what the fly is doing about sound, and the one place an event becomes actions |
| `device.py` | the board's socket, the beacon it is found by, and the line protocol |
| `find_types.py` | what this pack calls a cell type, for filling in the table |
| `index.html` | the page: the point cloud, the neuropils, the pathways, the fly card |
| `build_*.py` | the data files under `data/`, built once from the pack and the meshes |
