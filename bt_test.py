import statistics
import sys
import time

import serial

from boxes import BOX_IDS, find_port, open_port

ports = [a for a in sys.argv[1:] if a != "--bt"] or [find_port(box_id) for box_id in BOX_IDS]

for box_id, port in enumerate(ports, 1):
    if port is None:
        print(f"Box {box_id}: no port answered")
        continue
    try:
        ser = open_port(port, timeout=1)
    except serial.SerialException as e:
        print(f"{port}: can't open ({e})")
        continue
    with ser:
        print(f"Opened {port}.")
        round_trips = []
        for i in range(10):
            ser.reset_input_buffer()
            sent_at = time.perf_counter()
            ser.write(b"?")                     # any byte means "your turn"
            reply = ser.readline().decode("utf-8", errors="ignore").strip()
            ms = (time.perf_counter() - sent_at) * 1000
            if reply:
                round_trips.append(ms)
            print(f"{i + 1:>2}: {reply or '(no reply)':<40} {ms:4.0f} ms")
            time.sleep(0.2)
        if round_trips:
            print(f"    typical round trip: {statistics.median(round_trips):.0f} ms")
