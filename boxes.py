import sys

import serial
from serial.tools import list_ports

# Windows hands out a new COM number every time a box is re-paired, so boxes are
# pinned by Bluetooth address instead
BOX_BT_ADDRS = {   # BOX_ID -> Bluetooth address
    1: "383E516EB8AE",
    2: "E465B85C762E",
    3: "68094725D102",
}
BOX_IDS = tuple(BOX_BT_ADDRS)

BAUD_RATE = 115200
USB_UART_VIDS = {0x10C4, 0x1A86, 0x0403, 0x303A}  # CP210x, CH340, FTDI, ESP32 native USB
BT_ONLY = "--bt" in sys.argv  # skip boxes plugged in over USB


def open_port(port, timeout):
    """Open a box's port without pulsing DTR/RTS, which would reset an ESP32 on USB."""
    ser = serial.Serial(baudrate=BAUD_RATE, timeout=timeout, write_timeout=timeout)
    ser.port = port
    ser.dtr = False
    ser.rts = False
    ser.open()
    return ser


def answers_as(line, box_id):
    parts = line.split()
    return len(parts) >= 3 and parts[0] == str(box_id) and parts[1] == "DIST"


def probe(port, box_id):
    """True if the box on this port replies to a request as `box_id`."""
    try:
        with open_port(port, timeout=1.0) as ser:
            ser.reset_input_buffer()
            ser.write(b"?")
            for _ in range(4):
                line = ser.readline().decode("utf-8", errors="ignore")
                if not line:
                    return False
                if answers_as(line, box_id):
                    return True
    except serial.SerialException:
        pass
    return False


def find_port(box_id):
    """COM port that answers as this box: USB first (its replies carry d1/d2), then Bluetooth.
    Windows makes two COM ports per paired box; only the outgoing one carries the address."""
    ports = list_ports.comports()
    usb = [] if BT_ONLY else [p.device for p in ports if p.vid in USB_UART_VIDS]
    bt = [p.device for p in ports if BOX_BT_ADDRS[box_id] in p.hwid.upper()]
    for port in usb + bt:
        if probe(port, box_id):
            return port
    return None


if __name__ == "__main__":
    assert answers_as("2 DIST 1234", 2)
    assert answers_as("1 DIST -1  (d1=-1 d2=-1)", 1)
    assert not answers_as("1 DIST 900", 2)
    assert not answers_as("1 WARNING", 1)
    assert not answers_as("Reset reason: 1", 1)
    for box_id in BOX_IDS:
        print(f"Box {box_id}: {find_port(box_id) or 'not found'}")
