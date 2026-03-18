import serial

try:
    ser = serial.Serial("COM3", 9600, timeout=1)
    print("COM3 opened successfully!")
    ser.close()
except Exception as e:
    print("Error:", e)