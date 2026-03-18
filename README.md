# SmartLibrary (Flask + Arduino RFID)

## What this project does
- **Users** can log in normally, or scan an RFID card to log in automatically.
- **Admins** see dashboard stats and can be notified when a special “blue key” card is scanned.
- **Arduino UNO + MFRC522** reads RFID cards and sends the UID to the Flask app over Serial.

## Arduino setup
1. Open `arduino/SmartLibraryRFID/SmartLibraryRFID.ino` in Arduino IDE.
2. Install the **MFRC522** library (Arduino IDE → Library Manager).
3. Select the correct **COM port** and upload.

**Serial protocol:** the Arduino prints **one line per scan** containing only the UID, e.g. `3E76C301`.

## Flask setup
1. Install Python (make sure `python` works in PowerShell).
2. Install packages:

```bash
pip install -r requirements.txt
```

3. Make sure MySQL is running and the database `library` exists with tables:
- `user` (the app will try to add `rfid_uid` automatically)
- `admin`
- `book_borrower`

4. (Optional) Configure Serial port:
- `RFID_SERIAL_PORT` (default `COM3`)
- `RFID_SERIAL_BAUD` (default `9600`)

Example (PowerShell):

```powershell
$env:RFID_SERIAL_PORT="COM3"
$env:RFID_SERIAL_BAUD="9600"
python Main.py
```

## UI themes
- **User pages** load `static/css/base.css` + `static/css/user.css`
- **Admin pages** load `static/css/base.css` + `static/css/admin.css`

