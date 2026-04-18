import os
import re
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, request, Response
import requests

# ---------- CONFIGURATION ----------
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")
WHATSAPP_API_URL = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"

GOOGLE_SHEETS_CREDS_JSON = os.environ.get("GOOGLE_SHEETS_CREDS")
SHEET_NAME = os.environ.get("SHEET_NAME", "Escort Bookings")

app = Flask(__name__)

# ---------- DATE/TIME PARSER ----------
def parse_message(message):
    msg_lower = message.lower()
    
    if "escort needed" not in msg_lower:
        return (None, None)
    
    day_match = re.search(r'\b(2[3-9]|30)\b', msg_lower)
    if not day_match:
        return (None, None)
    day = int(day_match.group(1))
    
    time_found = False
    if re.search(r'\b(1[0-9]|2[0-3])(?::[0-5][0-9])?\s*(?:am|pm|hrs?)?\b', msg_lower):
        time_found = True
    elif re.search(r'9\.[3-9][0-9]|9:3[0-9]|9\.3[0-9]', msg_lower):
        time_found = True
    elif re.search(r'(1[3-9]|2[0-3])[0-5][0-9]\s*hrs?', msg_lower):
        time_found = True
    
    if not time_found:
        return (None, None)
    
    return ("me", day)

# ---------- GOOGLE SHEETS ----------
def get_available_days():
    creds_dict = json.loads(GOOGLE_SHEETS_CREDS_JSON)
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open(SHEET_NAME).sheet1
    
    available = set()
    records = sheet.get_all_records()
    for row in records:
        date_str = str(row.get('Date', ''))
        status = str(row.get('Available', '')).upper()
        day_match = re.search(r'\b(\d{1,2})\b', date_str)
        if day_match and status in ('TRUE', 'AVAILABLE'):
            day = int(day_match.group(1))
            if 23 <= day <= 30:
                available.add(day)
    return available

def mark_booked(day):
    creds_dict = json.loads(GOOGLE_SHEETS_CREDS_JSON)
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open(SHEET_NAME).sheet1
    
    cells = sheet.findall(str(day))
    for cell in cells:
        if cell.col == 1:
            sheet.update_cell(cell.row, 2, "FALSE")
            return True
    return False

# ---------- SEND QUOTED REPLY ----------
def send_quoted_reply(to_number, reply_text, original_msg_id):
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "text",
        "text": {
            "body": reply_text,
            "context": {"message_id": original_msg_id}
        }
    }
    return requests.post(WHATSAPP_API_URL, headers=headers, json=data)

# ---------- WEBHOOK ----------
@app.route('/webhook', methods=['GET'])
def verify():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    if mode and token and mode == 'subscribe' and token == VERIFY_TOKEN:
        return challenge, 200
    return "Verification failed", 403

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    try:
        msg = data['entry'][0]['changes'][0]['value']['messages'][0]
        if msg['type'] == 'text':
            text = msg['text']['body']
            from_num = msg['from']
            msg_id = msg['id']
            
            reply, day = parse_message(text)
            if reply and day:
                available = get_available_days()
                if day in available:
                    send_quoted_reply(from_num, reply, msg_id)
                    mark_booked(day)
    except Exception as e:
        print(f"Error: {e}")
    return Response(status=200)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
