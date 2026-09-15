import sys
import time

import serial

port = sys.argv[1] if len(sys.argv) > 1 else "COM7"

with serial.Serial(port, 115200, timeout=1) as ser:
    print(f"Opened {port}.")
    for i in range(10):
        ser.reset_input_buffer()
        ser.write(b"?")                     # any byte means "your turn"
        reply = ser.readline().decode("utf-8", errors="ignore").strip()
        print(f"{i + 1:>2}: {reply or '(no reply)'}")
        time.sleep(0.2)
