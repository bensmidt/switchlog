# standard library imports
from datetime import datetime, timedelta
from typing import List
from dataclasses import dataclass

# internal library imports
from env import slack_bot_token

# third party imports
from dotenv import load_dotenv
from slack_sdk import WebClient


@dataclass
class SlackMessage:
    user: str
    type: str
    timestamp: datetime
    text: str

    def __lt__(self, other):
        return self.timestamp < other.timestamp

    def __le__(self, other):
        return self.timestamp <= other.timestamp

    def __gt__(self, other):
        return self.timestamp > other.timestamp

    def __ge__(self, other):
        return self.timestamp >= other.timestamp

    def __eq__(self, other):
        return self.timestamp == other.timestamp

    def __ne__(self, other):
        return self.timestamp != other.timestamp

    def __str__(self):
        formatted_user = f"user: {self.user}"
        formatted_type = f"type: {self.type}"
        formatted_timestamp = f"timestamp: {self.timestamp}"
        formatted_text = f"text: {self.text}"
        tab = "  "
        return (
            "Slack Message:" + "\n" +
            tab + formatted_text + "\n" +
            tab + formatted_timestamp + "\n" +
            tab + formatted_type + "\n" +
            tab + formatted_user
        )


class SlackClient:

    def __init__(self):
        client = WebClient(token=slack_bot_token())
        self.client = client

    def get_conversation_history(
        self,
        channel_id: str,
        latest: datetime | None = None,
        oldest: datetime | None = None,
    ) -> List[SlackMessage]:
        all_messages = []
        has_more = True
        next_cursor = None

        if latest:
            latest_timestamp = latest.timestamp()
        else:
            latest_timestamp = None
        if oldest:
            oldest_timestamp = oldest.timestamp()
        else:
            oldest_timestamp = None

        # retrieve the messages
        while has_more:
            response = self.client.conversations_history(
                channel=channel_id,
                # slack recommends 200 max
                # https://api.slack.com/methods/conversations.history#markdown
                limit=200,
                cursor=next_cursor,
                latest=latest_timestamp,
                oldest=oldest_timestamp,
            )

            messages = response['messages']
            all_messages.extend(messages)

            has_more = response['has_more']
            if has_more:
                next_cursor = response['response_metadata'].get('next_cursor')

        # transform them into more structured data
        slack_messages = []
        for message in all_messages:
            slack_message = SlackMessage(
                user=message["user"],
                type=message["type"],
                timestamp=datetime.fromtimestamp(float(message["ts"])),
                text=message["text"]
            )
            slack_messages.append(slack_message)

        return slack_messages

    # def list_conversations(self):
    #     return self.client.conversations_list()

    # def list_user_conversations(self):
    #     return self.client.users_conversations(types="im")

    # def get_switchlog_slackbot_dms(self):
    #     user_conversations = self.client.users_conversations(types="im")
    #     slackbot_conversations = []
    #     for user_conversation in user_conversations["channels"]:
    #         if user_conversation["user"] != 'USLACKBOT':
    #             slackbot_conversations.append()


def main():
    # load the environment variables
    load_dotenv()

    # scrape the slack channel
    channel_id = "D08SS90DC3X"
    slack_client = SlackClient()
    now = datetime.now()
    one_day = timedelta(days=1)
    one_day_ago = now - one_day
    messages = slack_client.get_conversation_history(
        channel_id,
        oldest=one_day_ago
    )
    for msg in messages:
        print(msg)


if __name__ == "__main__":
    main()
