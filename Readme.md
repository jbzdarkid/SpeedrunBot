# Discord announcement bot for speedrunners
This bot uses the twitch.tv and speedrun.com apis to search for speedrunners who are actively speedrunning a given game. It polls every minute, and sends announcements when new streams come online.

## Setting up the repo
- Install python 3.9 (or later)
- Create a virtual environment
- Install the requirements from `requirements.txt`
- Get a discord token by following [these steps](https://github.com/reactiflux/discord-irc/wiki/Creating-a-discord-bot-&-getting-a-token)  
  The bot only needs the "Send Messages" permission (2048)  
  Save the token into a file called `discord_token.txt` inside the `source` folder
- Connect to the twitch APIs
  - Go to https://dev.twitch.tv/console/apps
  - Register a new application, and save the client ID into a file called `twitch_client.txt` inside the `source` folder
  - Generate a client secret (on the page for that app) and save it into a file called `twitch_token.txt` inside the `source` folder
