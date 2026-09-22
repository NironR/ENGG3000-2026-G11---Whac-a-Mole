# ENGG3000 Group 11
## Whac'a Mole project

A Whac-a-Mole game built for ENGG3000. Players move through a
1.5 m x 1.4 m grid zone; ultrasonic sensor boxes track position over
Bluetooth and drive a Tkinter game on a Windows PC.

## How it works

- `sensor.ino`, ESP32 firmware. Each box has two RCWL-1601 ultrasonic
  sensors, polled on request over Bluetooth SPP (`ENGG3000_<BOX_ID>`).
  The PC asks one box at a time, so only one sensor is ever listening.
- `whacka.py`, the game. Polls each paired box in turn, picks the
  column from whichever box sees the player, and maps that box's
  distance reading to depth in the grid.
- `bt_test.py`, bench tool for testing one box over Bluetooth without
  launching the game.

## Running it

1. Flash `sensor.ino` to each ESP32 (set `BOX_ID` per box before
   flashing).
2. Pair each box's Bluetooth and note its outgoing COM port.
3. Set `box_ports` in `whacka.py` to match.
4. `python whacka.py`

## Status

One sensor box built and verified end-to-end. Column-based positioning
(box ID = grid column, depth = row); see the branch history for why
this replaced full 2D trilateration.
