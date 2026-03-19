import os
import re

# RFID / Serial configuration
SERIAL_PORT = os.environ.get("RFID_SERIAL_PORT", "COM3")
SERIAL_BAUD = int(os.environ.get("RFID_SERIAL_BAUD", "9600"))

# Special admin/blue key UID
BLUE_KEY_UID = "3E76C301"

# Accept hex UID strings like: 3E76C301
UID_PATTERN = re.compile(r"^[0-9A-F]{8,}$")

