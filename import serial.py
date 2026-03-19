import serial

ser = serial.Serial("COM3", 9600, timeout=1)
print("COM3 opened successfully!")
ser.close()