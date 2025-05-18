# standard library imports
from datetime import datetime, timedelta
import logging
import socket

# internal librar imports
import slack
import tasks as task_lib


# =========================== INPUT DATETIME RANGE ======================== #
def input_day(self) -> tuple[datetime, datetime]:
    date = input("Enter the day (YYYY-MM-DD). Press Enter for today:\n")
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    start_datetime = date + "T00:00:00-07:00"
    end_datetime = date + "T23:59:59-07:00"
    return (
        datetime.fromisoformat(start_datetime),
        datetime.fromisoformat(end_datetime)
    )


def input_week(self) -> tuple[datetime, datetime]:
    date = input(
        (
            "Enter the start day (YYYY-MM-DD) of the week. "
            "Press Enter for today:\n"
        )
    )
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    start_datetime = date + "T00:00:00-07:00"
    date_obj = datetime.fromisoformat(date) + timedelta(days=6)
    end_datetime = date_obj.strftime("%Y-%m-%d") + "T23:59:59-07:00"
    return (
        datetime.fromisoformat(start_datetime),
        datetime.fromisoformat(end_datetime)
    )


def input_datetime_range(self) -> tuple[datetime, datetime]:
    start_date = input(
        "Enter the start day (YYYY-MM-DD). Press Enter for today:\n"
    )
    if not start_date:
        start_date = datetime.now().strftime("%Y-%m-%d")
    start_time = input("Enter the start time (HH:MM): ")
    if not start_time:
        start_time = "00:00"
    end_date = input("Enter the end date (YYYY-MM-DD): ")
    if not end_date:
        end_date = start_date
    end_time = input("Enter the end time (HH:MM): ")
    if not end_time:
        end_time = "23:59"
    start_datetime = f"{start_date}T{start_time}:00-07:00"
    end_datetime = f"{end_date}T{end_time}:00-07:00"
    return (
        datetime.fromisoformat(start_datetime),
        datetime.fromisoformat(end_datetime)
    )


# =========================== AUDIT =============================== #
def _audit(start_datetime: datetime, end_datetime: datetime):
    events = query_events(start_datetime, end_datetime)
    if not events:
        print(f"No events found for {start_datetime}-{end_datetime}")
        return
    categories = self.categorize_events(events)
    self.print_analysis(categories)


def audit_day(self):
    self.set_tag_option()
    start_date, end_date = input_day()
    self._audit(start_date, end_date)


def audit_week(self):
    self.set_tag_option()
    print(self._audit_first_tag_only)
    # audit week
    start_datetime, end_datetime = self._date_inputter.input_week()
    events = self.query_events(start_datetime, end_datetime)
    if not events:
        print(f"No events found for {start_datetime}-{end_datetime}")
        return
    categories = self.categorize_events(events)
    self.print_analysis(categories)

    # audit each day of the week
    cur_datetime = start_datetime
    while cur_datetime <= end_datetime:
        cur_events = []
        self._total_duration = SECS_IN_DAY
        print(DAYS_OF_WEEK[cur_datetime.weekday()], cur_datetime.date())
        for event in events:
            if event["start"]["dateTime"].day == cur_datetime.day:
                cur_events.append(event)
        if not cur_events:
            print(f"No events found for {cur_datetime}")
            cur_datetime += timedelta(days=1)
            continue
        categories = self.categorize_events(cur_events)
        self.print_analysis(categories)
        cur_datetime += timedelta(days=1)


def audit_datetime_range(self):
    self.set_tag_option()
    start_date, end_date = self._date_inputter.input_datetime_range()
    self._audit(start_date, end_date)


def audit(self):
    print("Select from one of the following audit options:")
    options = ["day", "week", "datetime range"]
    count = 1
    for option in options:
        print(f"{count}. {option}")
        count += 1
    option = input(f"Select a number 1-{len(options)}: ")
    if option == "1":
        return self.audit_day()
    elif option == "2":
        return self.audit_week()
    elif option == "3":
        return self.audit_datetime_range()
    else:
        print("INVALID OPTION. TRY AGAIN.\n")
        return self.audit()


def main():
    # scrape the slack channel for messages
    channel_id = "D08SS90DC3X"
    slack_client = slack.SlackClient()
    slack_messages = slack_client.get_conversation_history(channel_id)

    # turn the messages into tasks
    tasks = task_lib.convert_slack_messages_to_tasks(
        slack_messages, datetime.now()
    )

    # print the analysis
    analysis = task_lib.TaskAnalysis(tasks)
    print(analysis)


if __name__ == "__main__":
    # ignore annoying logs from other libraries
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    logging.getLogger("requests").setLevel(logging.ERROR)
    logging.getLogger("google").setLevel(logging.ERROR)

    logger = logging.getLogger()
    fhandler = logging.FileHandler(filename="audit.log", mode="w")
    format_str = (
        f"[%(asctime)s {socket.gethostname()}] "
        f"%(filename)s:%(funcName)s:%(lineno)s - %"
        f"(levelname)s: %(message)s"
    )
    formatter = logging.Formatter(format_str)
    fhandler.setFormatter(formatter)
    logger.addHandler(fhandler)
    logger.setLevel(logging.DEBUG)

    main()
