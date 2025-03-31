import os
import json
import re
from datetime import datetime, timedelta
from flask import Flask, request
from slack_sdk import WebClient
from slack_sdk.signature import SignatureVerifier
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Load secrets
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
STATE_FILE = "todo_doc_state.json"
SERVICE_ACCOUNT_FILE = "service_account.json"

# Flask app
app = Flask(__name__)
slack_client = WebClient(token=SLACK_BOT_TOKEN)
verifier = SignatureVerifier(SLACK_SIGNING_SECRET)

# Google API clients
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
]
creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
sheets_service = build("sheets", "v4", credentials=creds)
docs_service = build("docs", "v1", credentials=creds)

# --- Google Sheets ---

def append_to_sheet(date, timestamp, task, category):
    values = [[date, timestamp, task, category]]
    body = {"values": values}
    sheets_service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range="Sheet1!A1",
        valueInputOption="RAW",
        body=body,
    ).execute()

# --- Google Docs ---

def load_state():
    if not os.path.exists(STATE_FILE):
        return {"current_doc_id": None, "week_start": None, "days_written": []}
    with open(STATE_FILE, "r") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def get_week_start(date):
    return (date - timedelta(days=date.weekday())).strftime("%Y-%m-%d")

def create_new_doc(week_start):
    title = f"Todo Log - Week of {datetime.strptime(week_start, '%Y-%m-%d').strftime('%m.%d.%Y')}"
    doc = docs_service.documents().create(body={"title": title}).execute()
    return doc["documentId"]

def add_day_header(doc_id, date):
    date_obj = datetime.strptime(date, "%Y-%m-%d")
    day_str = date_obj.strftime("%A, %m.%d.%Y")
    header_text = f"\n\n{day_str}\n"
    requests = [{
        "insertText": {
            "location": {"index": 1},
            "text": header_text,
        }
    }]
    docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

def append_to_doc(doc_id, text):
    requests = [{
        "insertText": {
            "location": {"index": 1},
            "text": text,
        }
    }]
    docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

def handle_tdo(timestamp, task, category):
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    week_start = get_week_start(now)

    state = load_state()

    if state.get("week_start") != week_start:
        new_doc_id = create_new_doc(week_start)
        state = {
            "current_doc_id": new_doc_id,
            "week_start": week_start,
            "days_written": [],
        }

    doc_id = state["current_doc_id"]

    if date_str not in state["days_written"]:
        add_day_header(doc_id, date_str)
        state["days_written"].append(date_str)

    text = f"{timestamp} - {task} ({category})\n"
    append_to_doc(doc_id, text)
    save_state(state)

# --- Main message handler ---

def process_message(text):
    now = datetime.now()
    date = now.strftime("%Y-%m-%d")
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    # Match: ts: description (category)
    ts_match = re.match(r"ts:\s*(.+)\s+\((.+)\)", text, re.IGNORECASE)

    # Match: tdo: description (category)
    tdo_match = re.match(r"tdo:\s*(.+)\s+\((.+)\)", text, re.IGNORECASE)

    if ts_match:
        task, category = ts_match.groups()
        print(f"[INFO] Logging TS → {task} ({category})")
        append_to_sheet(date, timestamp, task, category)

    elif tdo_match:
        task, category = tdo_match.groups()
        print(f"[INFO] Logging TDO → {task} ({category})")
        handle_tdo(timestamp, task, category)

    else:
        print(f"[WARN] Ignored message — invalid format: '{text}'")
        
        # Optional: Reply in Slack to let user know
        # slack_client.chat_postMessage(
        #     channel="your-channel-id",  # Optional: or extract from event
        #     text="❗ Couldn't parse that. Use:\n• ts: task (category)\n• tdo: task (category)"
        # )


# --- Slack Events Endpoint ---

@app.route("/slack/events", methods=["POST"])
def slack_events():
    # Optional: check signature
    if not verifier.is_valid_request(request.get_data(), request.headers):
        return "Invalid request", 403

    payload = request.json

    # Slack's initial verification ping
    if payload.get("type") == "url_verification":
        return payload.get("challenge"), 200

    # Handle Slack messages
    if "event" in payload:
        event = payload["event"]
        if event.get("type") == "message" and "bot_id" not in event:
            text = event.get("text")
            print(f"[INFO] Received Slack message: {text}")
            process_message(text)

    return "OK", 200



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Render provides PORT as env var
    app.run(host="0.0.0.0", port=port)
