# standard library imports
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, MINYEAR
import re

# internal library imports
import slack
import utils

# external library imports
from dotenv import load_dotenv
import pytz


@dataclass
class Task:
    start: datetime
    end: datetime
    tags: list[str]

    def __lt__(self, other):
        return self.start < other.start

    def __le__(self, other):
        return self.start <= other.start

    def __gt__(self, other):
        return self.end > other.end

    def __ge__(self, other):
        return self.end >= other.end

    def __eq__(self, other):
        return self.start == other.start and self.end == other.end

    def __ne__(self, other):
        return not self.__eq__(other)

    def __str__(self):
        formatted_start = f"start: {self.start}"
        formatted_end = f"end: {self.end}"
        formatted_duration = f"duration: {self.duration}"
        formatted_tags = f"tags: {self.tags}"
        tab = "  "
        return (
            "Task:" + "\n" +
            tab + formatted_start + "\n" +
            tab + formatted_end + "\n" +
            tab + formatted_duration + "\n" +
            tab + formatted_tags
        )

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    def copy(self) -> 'Task':
        return Task(
            start=self.start,
            end=self.end,
            tags=deepcopy(self.tags)
        )


@dataclass
class TagTasks:
    tag: str
    tasks: list[Task]

    def add_task(self, new_task):
        self.tasks.append(new_task)

    @property
    def duration(self) -> timedelta:
        duration = timedelta(0)
        for task in self.tasks:
            duration += task.duration
        return duration

    @property
    def num_tasks(self) -> int:
        return len(self.tasks)

    def first_task(self) -> Task:
        self.tasks.sort()
        return self.tasks[0]

    def last_task(self) -> Task:
        self.tasks.sort()
        return self.tasks[-1]


class TaskAnalysis:
    def __init__(
        self,
        tasks: list[Task],
        first_tag_only: bool = True,
    ):
        self.tag_to_tasks: dict[str, TagTasks] = {}

        # helper function for addings tasks to the dictionary
        def add_entry(tag, task):
            if tag in self.tag_to_tasks:
                self.tag_to_tasks[tag].add_task(task.copy())
            else:
                self.tag_to_tasks[tag] = TagTasks(
                    tag=tag,
                    tasks=[task.copy()]
                )

        for task in tasks:
            if first_tag_only:
                add_entry(task.tags[0], task.copy())
            else:
                for tag in task.tags:
                    add_entry(tag, task.copy())

    def __max_duration_chars(self) -> int:
        durations = []
        for tag, tag_tasks in self.tag_to_tasks.items():
            durations.append(f"{tag_tasks.duration}")
        durations.append(f"{self.all_tasks_duration()}")
        return utils.max_string_length(durations)

    def __str__(self):
        result = ""

        # determine lengths of stuff for formatting
        max_tag_chars = utils.max_string_length(self.tags)
        max_duration_chars = self.__max_duration_chars()

        # format the title
        col1 = f"{'Tag':^{max_tag_chars}}"
        col2 = f"{'Duration':^{max_duration_chars}}"
        col3 = f"{'% of Total':^10}"
        title = f"| {col1} | {col2} | {col3} |"
        result += f"+{'-' * (len(title) - 2)}+\n"
        result += title + "\n"
        result += f"+{'-' * (len(title) - 2)}+" + "\n"

        # per task analysis
        analysis_duration_secs = self.analysis_duration.total_seconds()
        for tag, tag_tasks in self.tag_to_tasks.items():
            task_duration = f"{tag_tasks.duration}"

            # percent of total
            tag_tasks_duration_secs = tag_tasks.duration.total_seconds()
            decimal_of_total = tag_tasks_duration_secs / analysis_duration_secs
            percent_of_total = f"{round(decimal_of_total * 100, 2):.2f}"

            # formatting
            col1 = f"{tag:^{max_tag_chars}}"
            col2 = f"{task_duration:^{max_duration_chars}}"
            col3 = f"{percent_of_total:^10}"
            result += f"| {col1} | {col2} | {col3} |\n"
        result += f"+{'-' * (len(title) - 2)}+\n"

        # all tasks analysis
        all_tasks_duration = f"{self.all_tasks_duration()}"
        all_tasks_duration_secs = self.all_tasks_duration().total_seconds()
        decimal_of_total = all_tasks_duration_secs / analysis_duration_secs
        percent_of_total = f"{round(decimal_of_total * 100, 2):.2f}"
        col1 = f"{'Total':^{max_tag_chars}}"
        col2 = f"{all_tasks_duration:^{max_duration_chars}}"
        col3 = f"{percent_of_total:^10}"
        result += f"| {col1} | {col2} | {col3} |\n"
        result += f"+{'-' * (len(title) - 2)}+"

        return result

    @property
    def analysis_duration(self) -> timedelta:
        start = datetime.now(pytz.utc)
        end = datetime(MINYEAR, 1, 1, tzinfo=pytz.utc)
        for _, tag_tasks in self.tag_to_tasks.items():
            start = min(start, tag_tasks.first_task().start)
            end = max(end, tag_tasks.last_task().end)
        return end - start

    @property
    def tags(self) -> list[str]:
        tags = []
        for tag in self.tag_to_tasks.keys():
            tags.append(tag)
        return tags

    def max_tasks_for_a_tag(self) -> int:
        max_tasks = 0
        for _, task in self.tag_to_tasks.items():
            max_tasks = max(max_tasks, task.num_tasks)
        return max_tasks

    def all_tasks_duration(self) -> timedelta:
        all_tasks_duration = timedelta(0)
        for _, tag_tasks in self.tag_to_tasks.items():
            all_tasks_duration += tag_tasks.duration
        return all_tasks_duration


def extract_tags_from_string(s: str) -> list[str]:
    # regex the description
    pattern = r"\[(.*?)\]"
    matches = re.findall(pattern, s)

    tags: list[str] = []
    if len(matches) == 0:
        return tags
    for match in matches[0].split(","):
        tags.append(match.strip())
    return tags


def convert_slack_messages_to_tasks(
    slack_messages: list[slack.SlackMessage],
    start: datetime,
    end: datetime,
) -> list[Task]:
    slack_messages.sort()

    tasks = []
    n_msgs = len(slack_messages)
    for i in range(n_msgs):
        msg = slack_messages[i]
        if i == 0:
            cur_start = start
        else:
            cur_start = msg.timestamp
        if i < n_msgs - 1:
            cur_end = slack_messages[i+1].timestamp
        else:
            cur_end = end
        tags = extract_tags_from_string(msg.text)
        if len(tags) == 0:
            continue
        task = Task(
            start=cur_start,
            end=cur_end,
            tags=tags,
        )
        tasks.append(task)
    return tasks


def audit_slack(
    slack_client: slack.SlackClient,
    channel_id: str,
    start: datetime,
    end: datetime,
) -> TaskAnalysis:

    # scrape the slack channel for messages
    slack_messages = slack_client.get_conversation_history(
        channel_id,
        latest=end,
        oldest=start,
        preceeding_older_count=1
    )

    # turn the messages into tasks
    tasks = convert_slack_messages_to_tasks(
        slack_messages=slack_messages,
        start=start,
        end=end,
    )

    return TaskAnalysis(tasks)


def main():
    # load the environment variables
    load_dotenv()

    # scrape the slack channel for messages
    channel_id = "D08TTLFB7RN"
    slack_client = slack.SlackClient()
    start = datetime(2025, 5, 20, pytz.utc)
    end = datetime(2025, 5, 21, pytz.utc)

    print(audit_slack(
        slack_client=slack_client,
        start=start,
        end=end,
        channel_id=channel_id,
    ))


if __name__ == "__main__":
    main()
