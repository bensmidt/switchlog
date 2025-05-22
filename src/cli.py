# standard library imports
from datetime import datetime, timedelta
import logging
import socket

# internal librar imports
import slack
import tasks as task_lib

# external library imports
from dotenv import load_dotenv


# =========================== INPUT DATETIME RANGE ======================== #
def input_day() -> tuple[datetime, datetime]:
    date = input("Enter the day (YYYY-MM-DD). Press Enter for today:\n")
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    start_datetime = date + "T00:00:00-07:00"
    end_datetime = date + "T23:59:59-07:00"
    return (
        datetime.fromisoformat(start_datetime),
        datetime.fromisoformat(end_datetime)
    )


def input_week() -> tuple[datetime, datetime]:
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


def input_datetime_range() -> tuple[datetime, datetime]:
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


def main():
    print("Select from one of the following audit options:")
    options = ["day", "week", "datetime range"]
    count = 1
    for option in options:
        print(f"{count}. {option}")
        count += 1
    option = input(f"Select a number 1-{len(options)}: ")

    slack_client = slack.SlackClient()
    channel_id = "D08TTLFB7RN"

    if option == "1":
        start, end = input_day()
        print(start, end)
        analysis = task_lib.audit_slack(
            slack_client=slack_client,
            channel_id=channel_id,
            start=start,
            end=end
        )
        print(analysis)

    elif option == "2":
        # audit week
        start, end = input_week()
        analysis = task_lib.audit_slack(
            slack_client=slack_client,
            channel_id=channel_id,
            start=start,
            end=end,
        )
        print(analysis)

        # audit each day of the week
        cur = start
        while cur <= end:
            analysis = task_lib.audit_slack(
                slack_client=slack_client,
                channel_id=channel_id,
                start=cur,
                end=cur + timedelta(days=1)
            )
            print(analysis)
            cur += timedelta(days=1)

    elif option == "3":
        start, end = input_datetime_range()
        analysis = task_lib.audit_slack(start, end)
        print(analysis)

    else:
        print("INVALID OPTION. TRY AGAIN.\n")


if __name__ == "__main__":
    # load the environment variable
    load_dotenv()

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
