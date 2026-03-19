#include <SPI.h>
#include <MFRC522.h>

#define SS_PIN 10
#define RST_PIN 9

MFRC522 rfid(SS_PIN, RST_PIN);

const int RED_LED_PIN = 3;
const int GREEN_LED_PIN = 4;
const int BUZZER_PIN = 5;

// Special admin/blue key UID (must match Main.py BLUE_KEY_UID)
byte blueKeyUID[] = {0x3E, 0x76, 0xC3, 0x01};

static bool matchUID(byte *uid1, byte *uid2, byte size1, byte size2) {
  if (size1 != size2) return false;
  for (byte i = 0; i < size1; i++) {
    if (uid1[i] != uid2[i]) return false;
  }
  return true;
}

static void beepOnce(int durationMs) {
  tone(BUZZER_PIN, 1000);
  delay(durationMs);
  noTone(BUZZER_PIN);
}

static void beepTwice() {
  for (int i = 0; i < 2; i++) {
    tone(BUZZER_PIN, 1000);
    delay(150);
    noTone(BUZZER_PIN);
    delay(100);
  }
}

void setup() {
  Serial.begin(9600);
  SPI.begin();
  rfid.PCD_Init();

  pinMode(RED_LED_PIN, OUTPUT);
  pinMode(GREEN_LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);

  digitalWrite(RED_LED_PIN, LOW);
  digitalWrite(GREEN_LED_PIN, LOW);

  // Optional boot line; Flask ignores non-UID lines.
  Serial.println("READY");
}

void loop() {
  if (!rfid.PICC_IsNewCardPresent()) return;
  if (!rfid.PICC_ReadCardSerial()) return;

  // Build UID as a single uppercase hex string with no spaces.
  String uidStr = "";
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) uidStr += "0";
    uidStr += String(rfid.uid.uidByte[i], HEX);
  }
  uidStr.toUpperCase();

  // IMPORTANT: Flask expects a clean UID line like "3E76C301"
  Serial.println(uidStr);

  // Feedback (green+1 beep for blue key, red+2 beeps for others)
  if (matchUID(rfid.uid.uidByte, blueKeyUID, rfid.uid.size, sizeof(blueKeyUID))) {
    digitalWrite(GREEN_LED_PIN, HIGH);
    digitalWrite(RED_LED_PIN, LOW);
    beepOnce(200);
  } else {
    digitalWrite(RED_LED_PIN, HIGH);
    digitalWrite(GREEN_LED_PIN, LOW);
    beepTwice();
  }

  delay(700);
  digitalWrite(RED_LED_PIN, LOW);
  digitalWrite(GREEN_LED_PIN, LOW);

  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
}