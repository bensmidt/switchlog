# SwitchLog

SwitchLog Documentation

## 1. Installation, Auth, Networking

The app is not yet scoped for multiple users. You will have to mess around with it yourself.

**Installation:** Go to Slack API. On the Miru workspace, you should see "Switchlog" already installed as an app. 

**Auth:** Figure out how you can use it separately from me (also a user of the app in the same workspace). We might be using the same Slack bot token/Slack signing secret, so I can send it to you if needed. Otherwise, another option is to just create another Slackbot, similarly named. 

**Networking:** Using ngrok right now. I've scoped it to port 3000.

For your reference, here are the required `.env` keys:
```
SLACK_BOT_TOKEN=
SLACK_SIGNING_SECRET=
GOOGLE_SHARE_EMAIL=
```

## 2. Usage

1. Create a private channel
2. Invite Switchlog to your channel by doing `/invite @SwitchLog`
   - Note: You will have to use this command with my implementation. I haven't figured out how to do this with the Slack UI.
3. Now start messaging the Slack bot. It will create and share a new folder and Google Sheet with you to your email. From there it will dump in all the task switching logs.

## 3. Format

Please use the format:
```
ts: task description (category)
```
Example: `ts: implemented error handling (coding)`

Invalid formats will be thrown as an error and not be logged.

## Development
- Port: The app runs on port 3000 by default
- Logging: Use `LOG_LEVEL`