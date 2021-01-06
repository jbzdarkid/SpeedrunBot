# Discord announcement bot for speedrunners.
This bot uses the speedrun.com api to search for speedrunners who are actively speedrunning a given game. It polls every minute, and sends announcements when new streams come online.

To get a discord token, follow these steps. The bot only needs the "Send Messages" permission (2048)
https://github.com/reactiflux/discord-irc/wiki/Creating-a-discord-bot-&-getting-a-token
Save this into a file called `discord_token.txt` at the root of the repo.

You also need a twitch token to hit certain endpoints (to determine which stream are live). To do that, you need to create a twitch app, then generate a new client secret (on the page for that app).
https://dev.twitch.tv/console/apps
Save your client ID into a file called `twitch_client.txt` at the root of the repo.
Save your client secret into a file called `twitch_token.txt` at the root of the repo.