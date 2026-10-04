import sys
import time

import serial

from boxes import BOX_BT_ADDRS, find_port

ports = sys.argv[1:] or [find_port(box_id) for box_id in BOX_BT_ADDRS]

for box_id, port in enumerate(ports, 1):
    if port is None:
        print(f"Box {box_id}: not paired with this PC")
        continue
    try:
        ser = serial.Serial(port, 115200, timeout=1)
    except serial.SerialException as e:
        print(f"{port}: can't open ({e})")
        continue
    with ser:
        print(f"Opened {port}.")
        for i in range(10):
            ser.reset_input_buffer()
            ser.write(b"?")                     # any byte means "your turn"
            reply = ser.readline().decode("utf-8", errors="ignore").strip()
            print(f"{i + 1:>2}: {reply or '(no reply)'}")
            time.sleep(0.2)
