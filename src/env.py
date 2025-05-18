# standard library imports
import os


def slack_bot_token():
    return os.environ["SLACK_BOT_TOKEN"]


def slack_signing_secret():
    return os.environ["SLACK_SIGNING_SECRET"]


def state_file():
    return "todo_doc_state.json"


def week_sheet_state_file():
    return "week_sheet_state.json"


def service_account_file():
    return "service_account.json"
