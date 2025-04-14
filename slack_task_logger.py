import os
import json
import re
import logging
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from slack_sdk import WebClient
from slack_sdk.signature import SignatureVerifier
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv
import pandas as pd
import gspread
from gspread_dataframe import set_with_dataframe
import threading
import time
import argparse

# Load environment variables
load_dotenv()

# Setup logging
from rich.logging import RichHandler

# Logging configuration
# To change log level:
# 1. Use DEBUG for detailed logs including full event data: logging.basicConfig(level=logging.DEBUG)
# 2. Use INFO for standard logs with event summaries: logging.basicConfig(level=logging.INFO)
# 3. Or set LOG_LEVEL environment variable to 'DEBUG' or 'INFO'
log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level),  # Use DEBUG for full event data, INFO for summaries
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler()]
)

# Load secrets
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]
STATE_FILE = "todo_doc_state.json"
WEEK_SHEET_STATE_FILE = "week_sheet_state.json"
SERVICE_ACCOUNT_FILE = "service_account.json"

# Flask app
app = Flask(__name__)
slack_client = WebClient(token=SLACK_BOT_TOKEN)
verifier = SignatureVerifier(SLACK_SIGNING_SECRET)

# Set for tracking processed events (prevent duplicates)
processed_events = set()

# Google API clients
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file"
]
creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
sheets_service = build("sheets", "v4", credentials=creds)
docs_service = build("docs", "v1", credentials=creds)
drive_service = build("drive", "v3", credentials=creds)

# Gspread client
gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)

# --- Google Sheets State Management ---

def load_sheet_state():
    if not os.path.exists(WEEK_SHEET_STATE_FILE):
        return {}
    with open(WEEK_SHEET_STATE_FILE, "r") as f:
        return json.load(f)

def save_sheet_state(state):
    with open(WEEK_SHEET_STATE_FILE, "w") as f:
        json.dump(state, f)

def get_week_sheet_title(date):
    """Get the title for a week's sheet in format 'Week of MM.DD - MM.DD'"""
    # Get Monday of the week
    monday = date - timedelta(days=date.weekday())
    # Get Sunday of the week
    sunday = monday + timedelta(days=6)
    return f"Week of {monday.strftime('%m.%d')} - {sunday.strftime('%m.%d')}"

def get_or_create_switchlog_folder():
    """Get or create the SwitchLog Productivity Tracking folder"""
    drive_service = build('drive', 'v3', credentials=creds)
    user_email = os.environ.get('GOOGLE_SHARE_EMAIL')
    
    # Search for existing folder
    results = drive_service.files().list(
        q="name='SwitchLog Productivity Tracking' and mimeType='application/vnd.google-apps.folder' and trashed=false",
        spaces='drive',
        fields='files(id, name, owners)'
    ).execute()
    
    if results.get('files'):
        folder_id = results['files'][0]['id']
        folder_link = f"https://drive.google.com/drive/folders/{folder_id}"
        logging.info(f"Found existing SwitchLog folder: {folder_id}")
        logging.info(f"Folder link: {folder_link}")
        
        # Check if user is already owner
        owners = results['files'][0].get('owners', [])
        if not any(owner.get('emailAddress') == user_email for owner in owners):
            try:
                # First share with user as writer
                drive_service.permissions().create(
                    fileId=folder_id,
                    body={
                        'type': 'user',
                        'role': 'writer',
                        'emailAddress': user_email
                    },
                    sendNotificationEmail=True
                ).execute()
                logging.info(f"Shared folder with {user_email}")
                
                time.sleep(2)  # Wait for sharing to take effect
                
                # Then transfer ownership
                drive_service.permissions().create(
                    fileId=folder_id,
                    body={
                        'type': 'user',
                        'role': 'owner',
                        'emailAddress': user_email,
                        'transferOwnership': True
                    },
                    transferOwnership=True,
                    sendNotificationEmail=True
                ).execute()
                logging.info(f"Transferred folder ownership to {user_email}")
            except Exception as e:
                logging.error(f"Failed to transfer folder ownership: {e}")
        
        return folder_id
    
    # Create new folder if it doesn't exist
    folder_metadata = {
        'name': 'SwitchLog Productivity Tracking',
        'mimeType': 'application/vnd.google-apps.folder'
    }
    
    folder = drive_service.files().create(
        body=folder_metadata,
        fields='id'
    ).execute()
    
    folder_id = folder.get('id')
    folder_link = f"https://drive.google.com/drive/folders/{folder_id}"
    logging.info(f"Created new SwitchLog folder: {folder_id}")
    logging.info(f"Folder link: {folder_link}")
    
    if user_email:
        try:
            # First share with user as writer
            drive_service.permissions().create(
                fileId=folder_id,
                body={
                    'type': 'user',
                    'role': 'writer',
                    'emailAddress': user_email
                },
                sendNotificationEmail=True
            ).execute()
            logging.info(f"Shared folder with {user_email}")
            
            time.sleep(2)  # Wait for sharing to take effect
            
            # Then transfer ownership
            drive_service.permissions().create(
                fileId=folder_id,
                body={
                    'type': 'user',
                    'role': 'owner',
                    'emailAddress': user_email,
                    'transferOwnership': True
                },
                transferOwnership=True,
                sendNotificationEmail=True
            ).execute()
            logging.info(f"Transferred folder ownership to {user_email}")
            
            time.sleep(2)  # Wait for ownership transfer
            
            # Keep service account as editor
            service_account_email = json.load(open(SERVICE_ACCOUNT_FILE))['client_email']
            drive_service.permissions().create(
                fileId=folder_id,
                body={
                    'type': 'user',
                    'role': 'writer',
                    'emailAddress': service_account_email
                },
                sendNotificationEmail=False
            ).execute()
            logging.info(f"Kept service account as editor")
            
        except Exception as e:
            logging.error(f"Failed to set up folder permissions: {e}")
    
    return folder_id

def create_new_weekly_sheet(title):
    """Create a new Google Sheet for a week with a Raw_Log tab"""
    try:
        folder_id = get_or_create_switchlog_folder()
        
        # Create the spreadsheet
        spreadsheet = {
            'properties': {
                'title': title
            },
            'sheets': [
                {
                    'properties': {
                        'title': 'Raw_Log',
                        'gridProperties': {
                            'rowCount': 1000,
                            'columnCount': 26
                        }
                    }
                }
            ]
        }
        
        spreadsheet = sheets_service.spreadsheets().create(body=spreadsheet).execute()
        spreadsheet_id = spreadsheet.get('spreadsheetId')
        sheet_link = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        logging.info(f"Created new weekly sheet: {title} with ID: {spreadsheet_id}")
        logging.info(f"Sheet link: {sheet_link}")
        
        # Move the sheet to our folder
        drive_service = build('drive', 'v3', credentials=creds)
        drive_service.files().update(
            fileId=spreadsheet_id,
            addParents=folder_id,
            fields='id, parents'
        ).execute()
        
        # Add headers to Raw_Log
        headers = [['Date', 'Timestamp', 'Task', 'Category']]
        body = {'values': headers}
        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range='Raw_Log!A1',
            valueInputOption='RAW',
            body=body
        ).execute()

        # Share the sheet with the user's email
        user_email = os.environ.get('GOOGLE_SHARE_EMAIL')
        if user_email:
            try:
                drive_service.permissions().create(
                    fileId=spreadsheet_id,
                    body={
                        'type': 'user',
                        'role': 'writer',
                        'emailAddress': user_email
                    },
                    sendNotificationEmail=True
                ).execute()
                logging.info(f"Shared sheet with {user_email}")
            except Exception as e:
                logging.error(f"Failed to share sheet: {e}")
        
        logging.info(f"Created new weekly sheet: {title} with ID: {spreadsheet_id} in folder {folder_id}")
        logging.info(f"Folder link: https://drive.google.com/drive/folders/{folder_id}")
        logging.info(f"Sheet link: {sheet_link}")
        return spreadsheet_id
        
    except Exception as e:
        logging.error(f"Failed to create weekly sheet: {e}")
        raise

def get_or_create_weekly_sheet_id():
    """Get the current week's sheet ID, creating it if necessary"""
    today = datetime.now()
    title = get_week_sheet_title(today)
    
    sheet_state = load_sheet_state()
    logging.info(f"Current sheet state: {sheet_state}")
    
    # Check if we already have a sheet for this week
    if title in sheet_state:
        logging.info(f"Reusing existing sheet for week: {title}")
        return sheet_state[title]
    
    # Create new sheet if none exists for this week
    logging.info(f"Creating new sheet for week: {title}")
    new_id = create_new_weekly_sheet(title)
    sheet_state[title] = new_id
    save_sheet_state(sheet_state)
    logging.info(f"Created and saved new sheet with ID: {new_id}")
    return new_id

# --- Google Sheets Operations ---

def append_to_sheet(date, timestamp, task, category):
    spreadsheet_id = get_or_create_weekly_sheet_id()
    logging.info(f"[SHEET] Appending to sheet {spreadsheet_id}: {date}, {timestamp}, {task}, {category}")
    try:
        values = [[date, timestamp, task, category]]
        body = {"values": values}
        sheets_service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range="Raw_Log!A1",
            valueInputOption="RAW",
            body=body
        ).execute()
        logging.info(f"[SHEET] Successfully wrote to sheet {spreadsheet_id}")
    except Exception as e:
        logging.error(f"[SHEET ERROR] Failed to write to sheet {spreadsheet_id}: {e}")


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

    logging.info(f"Processing message: {text}")

    ts_match = re.match(r"ts:\s*(.+)\s+\((.+)\)", text, re.IGNORECASE)
    tdo_match = re.match(r"tdo:\s*(.+)\s+\((.+)\)", text, re.IGNORECASE)

    if ts_match:
        task, category = ts_match.groups()
        logging.info(f"[TS] Task: {task} | Category: {category}")
        append_to_sheet(date, timestamp, task, category)

    elif tdo_match:
        task, category = tdo_match.groups()
        logging.info(f"[TDO] Task: {task} | Category: {category}")
        handle_tdo(timestamp, task, category)

    else:
        logging.warning(f"Ignored message — invalid format: '{text}'")

def process_task_message(text, user_id, channel_id):
    """Process a task message and return True if it was processed successfully"""
    # Extract task and category using regex
    match = re.match(r'^ts:\s*([^(]+)\s*\(([^)]+)\)\s*$', text.strip())
    if not match:
        logging.info("Invalid task format")
        # Send error message back to Slack
        slack_client.chat_postMessage(
            channel=channel_id,
            text=":warning: Invalid task format. Please use the format:\n`ts: task description (category)`\nExample: `ts: implemented error handling (coding)`"
        )
        return False
    
    task = match.group(1).strip()
    category = match.group(2).strip()
    
    if not task or not category:
        logging.info("Empty task or category")
        slack_client.chat_postMessage(
            channel=channel_id,
            text=":warning: Task and category cannot be empty. Please use the format:\n`ts: task description (category)`\nExample: `ts: implemented error handling (coding)`"
        )
        return False
    
    # Process the task
    now = datetime.now()
    date = now.strftime("%Y-%m-%d")
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    logging.info(f"Logging task: {task} ({category})")
    append_to_sheet(date, timestamp, task, category)
    return True

def process_todo_message(text, user_id, channel_id):
    """Process a todo message"""
    # Extract todo and category using regex
    match = re.match(r'^tdo:\s*([^(]+)\s*\(([^)]+)\)\s*$', text.strip())
    if not match:
        logging.info("Invalid todo format")
        # Send error message back to Slack
        slack_client.chat_postMessage(
            channel=channel_id,
            text=":warning: Invalid todo format. Please use the format:\n`tdo: todo description (category)`\nExample: `tdo: implement error handling (coding)`"
        )
        return False
    
    todo = match.group(1).strip()
    category = match.group(2).strip()
    
    if not todo or not category:
        logging.info("Empty todo or category")
        slack_client.chat_postMessage(
            channel=channel_id,
            text=":warning: Todo and category cannot be empty. Please use the format:\n`tdo: todo description (category)`\nExample: `tdo: implement error handling (coding)`"
        )
        return False
    
    # Process the todo
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    logging.info(f"Logging todo: {todo} ({category})")
    handle_tdo(timestamp, todo, category)
    return True

# --- Slack Events Endpoint ---

@app.route('/slack/events', methods=['POST'])
def slack_events():
    """Handle Slack events"""
    # Verify the request signature
    try:
        if not verifier.is_valid_request(request.get_data(), request.headers):
            logging.error("Invalid Slack request signature")
            return "Invalid request signature", 403
    except Exception as e:
        logging.error(f"Error verifying Slack request: {e}")
        return "Error verifying request", 403
        
    data = request.json
    
    # Log full data in debug mode
    logging.debug(f"Full event data: {json.dumps(data, indent=2)}")
    
    # Slack URL verification
    if data and data.get('type') == 'url_verification':
        challenge = data.get('challenge')
        logging.info("Handling Slack URL verification challenge")
        return jsonify({'challenge': challenge})
    
    # Process events
    if data and data.get('type') == 'event_callback':
        event = data.get('event', {})
        event_id = data.get('event_id')
        
        # Log event summary in info mode
        if event.get('type') == 'message':
            logging.info(f"Event {event_id}: {get_event_summary(event)}")
        
        # Skip if we've seen this event before
        if event_id in processed_events:
            logging.debug(f"Skipping duplicate event {event_id}")
            return jsonify({'status': 'ok'})
        
        # Add to processed events (with size limit to prevent memory issues)
        processed_events.add(event_id)
        if len(processed_events) > 1000:
            processed_events.clear()
            processed_events.add(event_id)
        
        # Only process message events
        if event.get('type') == 'message':
            # Skip message subtypes (like message_changed)
            if 'subtype' in event:
                logging.debug(f"Skipping message subtype: {event.get('subtype')}")
                return jsonify({'status': 'ok'})
            
            # Skip bot messages
            if event.get('bot_id'):
                logging.debug("Skipping bot message")
                return jsonify({'status': 'ok'})
            
            text = event.get('text', '').strip()
            channel_id = event.get('channel')
            
            # Check for task-like messages that might be misformatted
            lower_text = text.lower()
            if 'ts' in lower_text or 'tdo' in lower_text:
                # Process task logging messages
                if lower_text.startswith('ts:'):
                    logging.info(f"Processing task: {text}")
                    process_task_message(text, event.get('user'), channel_id)
                # Process todo messages
                elif lower_text.startswith('tdo:'):
                    logging.info(f"Processing todo: {text}")
                    process_todo_message(text, event.get('user'), channel_id)
                # Handle misformatted task messages
                else:
                    logging.info(f"Invalid task format: {text}")
                    slack_client.chat_postMessage(
                        channel=channel_id,
                        text=":warning: Invalid task format. Please use one of these formats:\n• For tasks: `ts: task description (category)`\n• For todos: `tdo: todo description (category)`"
                    )
    
    return jsonify({'status': 'ok'})

# --- Analytics Functions ---

def get_daily_analytics_sheet_title(date):
    """Get the title for a day's analytics sheet"""
    return f"{date.strftime('%a %m.%d')} Analytics"

def calculate_time_spent(df):
    """Calculate time spent on each task based on timestamps"""
    # Convert timestamps to datetime
    df['Timestamp'] = pd.to_datetime(df['Timestamp'])
    
    # Sort by timestamp
    df = df.sort_values('Timestamp')
    
    # Calculate time difference between consecutive tasks
    df['Time_Spent'] = df['Timestamp'].diff()
    
    # For the first task of the day, use time until next task
    df.loc[df.index[0], 'Time_Spent'] = df.loc[df.index[1], 'Timestamp'] - df.loc[df.index[0], 'Timestamp']
    
    # Convert to hours
    df['Time_Spent'] = df['Time_Spent'].dt.total_seconds() / 3600
    
    return df

def generate_daily_analytics(spreadsheet_id, date):
    """Generate daily analytics for a given date"""
    try:
        # Get the spreadsheet
        spreadsheet = gc.open_by_key(spreadsheet_id)
        
        # Read the Raw_Log sheet
        raw_log = spreadsheet.worksheet('Raw_Log')
        data = raw_log.get_all_records()
        df = pd.DataFrame(data)
        
        # Filter for today's data
        df['Date'] = pd.to_datetime(df['Date'])
        today_df = df[df['Date'].dt.date == date.date()]
        
        if today_df.empty:
            logging.info(f"No data found for {date.date()}")
            return None
        
        # Calculate time spent
        today_df = calculate_time_spent(today_df)
        
        # Group by category and sum time spent
        category_summary = today_df.groupby('Category')['Time_Spent'].sum().reset_index()
        category_summary = category_summary.sort_values('Time_Spent', ascending=False)
        
        # Create analytics sheet
        analytics_title = get_daily_analytics_sheet_title(date)
        try:
            analytics_sheet = spreadsheet.worksheet(analytics_title)
        except gspread.WorksheetNotFound:
            analytics_sheet = spreadsheet.add_worksheet(title=analytics_title, rows=100, cols=20)
        
        # Write category summary
        set_with_dataframe(analytics_sheet, category_summary, row=1, col=1)
        
        # Add total time
        total_time = category_summary['Time_Spent'].sum()
        analytics_sheet.update('D1', [['Total Time (hours)'], [total_time]])
        
        # Format the sheet
        analytics_sheet.format('A1:B1', {'textFormat': {'bold': True}})
        analytics_sheet.format('D1:D2', {'textFormat': {'bold': True}})
        
        logging.info(f"Generated daily analytics for {date.date()}")
        return analytics_sheet
        
    except Exception as e:
        logging.error(f"Failed to generate daily analytics: {e}")
        raise

# def run_daily_analytics():
#     """Run daily analytics at 11:59 PM"""
#     while True:
#         now = datetime.now()
#         # Check if it's 11:59 PM
#         if now.hour == 23 and now.minute == 59:
#             try:
#                 # Get the current week's sheet ID
#                 sheet_state = load_sheet_state()
#                 title = get_week_sheet_title(now)
#                 if title in sheet_state:
#                     spreadsheet_id = sheet_state[title]
#                     # Generate analytics for today
#                     generate_daily_analytics(spreadsheet_id, now)
#                     logging.info(f"Generated daily analytics for {now.date()}")
#             except Exception as e:
#                 logging.error(f"Failed to run daily analytics: {e}")
        
#         # Sleep for 1 minute
#         time.sleep(60)

# --- Test Functions ---

def cleanup_test_resources():
    """Clean up test folders and sheets"""
    try:
        drive_service = build('drive', 'v3', credentials=creds)
        
        # Find the test folder
        results = drive_service.files().list(
            q="name='SwitchLog Productivity Tracking' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            spaces='drive',
            fields='files(id, name)'
        ).execute()
        
        if results.get('files'):
            folder_id = results['files'][0]['id']
            logging.info(f"Found test folder: {folder_id}")
            
            # Find all sheets in the folder
            sheets = drive_service.files().list(
                q=f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
                spaces='drive',
                fields='files(id, name)'
            ).execute()
            
            # Delete all sheets
            if sheets.get('files'):
                for sheet in sheets['files']:
                    drive_service.files().delete(fileId=sheet['id']).execute()
                    logging.info(f"Deleted sheet: {sheet['name']} ({sheet['id']})")
            
            # Delete the folder itself
            drive_service.files().delete(fileId=folder_id).execute()
            logging.info(f"Deleted folder: {folder_id}")
            
            logging.info("Cleanup completed successfully")
            
            # Clear the sheet state
            with open(WEEK_SHEET_STATE_FILE, "w") as f:
                json.dump({}, f)
            logging.info("Cleared sheet state")
        else:
            # If no folder exists, ensure state is cleared
            with open(WEEK_SHEET_STATE_FILE, "w") as f:
                json.dump({}, f)
            logging.info("No folder found, cleared sheet state")
        
    except Exception as e:
        logging.error(f"Cleanup failed: {e}")
        raise

def test_sheet_creation():
    """Test sheet and folder creation logic with task entries"""
    try:
        # Clean up existing resources first
        logging.info("\n=== Starting cleanup ===")
        cleanup_test_resources()
        logging.info("Cleanup completed, exiting...")
        import sys
        sys.exit(0)  # Exit after cleanup
        
        # Rest of the test code commented out for now
        """
        # Test 1: Add task for 04.07
        logging.info("\n=== Adding test task for 04.07 ===")
        append_to_sheet("2024-04-07", "2024-04-07 10:00:00", "test1", "debug")
        
        # Test 2: Add task for 04.08
        logging.info("\n=== Adding test task for 04.08 ===")
        append_to_sheet("2024-04-08", "2024-04-08 10:00:00", "test2", "debug")
        
        # Test 3: Add task for 04.09
        logging.info("\n=== Adding test task for 04.09 ===")
        append_to_sheet("2024-04-09", "2024-04-09 10:00:00", "test3", "debug")
        
        # Test 4: Add task for 04.14
        logging.info("\n=== Adding test task for 04.14 ===")
        append_to_sheet("2024-04-14", "2024-04-14 10:00:00", "test4", "debug")
        
        # Test 5: Add task for 04.15
        logging.info("\n=== Adding test task for 04.15 ===")
        append_to_sheet("2024-04-15", "2024-04-15 10:00:00", "test5", "debug")
        
        # Test 6: Add task for 05.01
        logging.info("\n=== Adding test task for 05.01 ===")
        append_to_sheet("2024-05-01", "2024-05-01 10:00:00", "test6", "debug")
        
        # Verify folder and sheets
        drive_service = build('drive', 'v3', credentials=creds)
        results = drive_service.files().list(
            q="name='SwitchLog Productivity Tracking' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            spaces='drive',
            fields='files(id, name)'
        ).execute()
        
        if results.get('files'):
            folder_id = results['files'][0]['id']
            logging.info(f"\n=== Folder Verification ===")
            logging.info(f"Folder ID: {folder_id}")
            logging.info(f"Folder link: https://drive.google.com/drive/folders/{folder_id}")
            
            # Verify sheets
            sheets = drive_service.files().list(
                q=f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
                spaces='drive',
                fields='files(id, name)'
            ).execute()
            
            if sheets.get('files'):
                logging.info("\n=== Sheet Verification ===")
                for sheet in sheets['files']:
                    logging.info(f"Sheet: {sheet['name']} ({sheet['id']})")
                    # Verify sheet content
                    sheet_service = build('sheets', 'v4', credentials=creds)
                    result = sheet_service.spreadsheets().values().get(
                        spreadsheetId=sheet['id'],
                        range='Raw_Log!A:D'
                    ).execute()
                    values = result.get('values', [])
                    logging.info(f"Tasks in sheet: {len(values) - 1}")  # -1 for header
                    for row in values[1:]:  # Skip header
                        logging.info(f"Task: {row}")
        else:
            logging.error("No folder found!")
        """
        
    except Exception as e:
        logging.error(f"Test failed: {e}")
        raise

def get_event_summary(event):
    """Get a concise summary of a Slack event.
    Used in INFO mode to show relevant event data without full JSON payload.
    In DEBUG mode, the full event data will also be logged."""
    if not event:
        return "Empty event"
    
    summary = {
        'type': event.get('type'),
        'text': event.get('text', '')[:50] + ('...' if len(event.get('text', '')) > 50 else ''),  # Truncate long messages
        'user': event.get('user'),
        'channel': event.get('channel')
    }
    return summary

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true', help='Run test cases')
    args = parser.parse_args()
    
    if args.test:
        test_sheet_creation()
    else:
        # Start the analytics thread
        analytics_thread = threading.Thread(target=run_daily_analytics)
        analytics_thread.daemon = True
        analytics_thread.start()
        
        # Start the Flask app
        port = int(os.environ.get("PORT", 3000))
        app.run(host="0.0.0.0", port=port)

