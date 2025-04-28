# standard library imports
import os

# local imports
from env import slack_bot_token

# third party imports
from dotenv import load_dotenv
import json
from pprint import pprint
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

def fetch_slack_messages(client: WebClient, channel_id: str, limit: int=100):
    all_messages = []
    has_more = True
    next_cursor = None

    while has_more:
        response = client.conversations_history(
            channel=channel_id,
            limit=limit,
            cursor=next_cursor
        )

        messages = response['messages']
        all_messages.extend(messages)

        has_more = response['has_more']
        if has_more:
            next_cursor = response['response_metadata'].get('next_cursor')

    return all_messages

def main():

    # load the environment variables
    load_dotenv()

    # scrape the slack channel
    client = WebClient(token=slack_bot_token())
    channel_id = "C08MY4U66SZ"
    messages = fetch_slack_messages(client, channel_id)
    for msg in messages:
        print(f"{msg.get('user')}: {msg.get('text')}")

if __name__ == "__main__":
    main()