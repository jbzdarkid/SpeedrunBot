# Discord announcement bot for speedrunners
This bot uses the twitch.tv and speedrun.com apis to search for speedrunners who are actively speedrunning a given game. It polls every minute, and sends announcements when new streams come online.

# Usage
Currently, this is my bot and can only be used with my permission. Please let me know if you'd like to use it -- or, you can clone this repo and set up your own bot by following the setup steps below.

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

## Setting up the bot
In order for the bot to post messages, it needs the "send_messages" permission.
Please use this link in to grant the permissions to a server you administrate.
(This is my bot's client ID. You'll need to change it to your bot's if you forked this repo.)
https://discord.com/oauth2/authorize?scope=bot&permissions=2048&client_id=683472204280889511
