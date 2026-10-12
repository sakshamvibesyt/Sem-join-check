# Saksham JoinGate

A Telegram group membership gate with a professional verification page.

## How it works
1. A new group member is temporarily restricted.
2. The bot posts a private verification deep link in the group.
3. The member opens the bot in Telegram and launches the secure Web App.
4. The page links the required Telegram channel and the YouTube channel.
5. The backend validates Telegram Web App `initData` and checks membership in `@aboutsaksham`.
6. If membership is confirmed, the bot removes the restriction in the group.

YouTube is currently a promotional link, not a required subscription check.

## Requirements / permissions
- Add the bot as an administrator in the target group with **Restrict Members** permission.
- Add the bot as an administrator in `@aboutsaksham` so Telegram membership checks work reliably.
- Use the new bot token from BotFather.
- Set `OWNER_ID` to your numeric Telegram user ID. Send `/id` to the bot to see your ID.
- Keep the Render service on a persistent disk if you want the SQLite database to survive redeploys/restarts. Set `DB_PATH` to a path on that disk, e.g. `/var/data/joingate.db`, and mount the disk at `/var/data`.
- Configure `WEB_BASE_URL` to the actual HTTPS URL of the deployed Render service, without a trailing slash.

## Render deployment
1. Push this folder to a new GitHub repository.
2. In Render, create a Web Service from that repository and choose Docker.
3. Add Environment Variables:
   - `BOT_TOKEN`: token for your new bot
   - `OWNER_ID`: numeric Telegram user ID
   - `WEB_BASE_URL`: `https://your-service-name.onrender.com`
   - `GROUP_URL`: your group invite link
   - `CHANNEL_USERNAME`: `@aboutsaksham`
   - `YOUTUBE_URL`: your YouTube channel URL
   - `DB_PATH`: `/var/data/joingate.db` if you have mounted a persistent disk; otherwise use `joingate.db` (database may reset on redeploy)
4. If using persistent storage, add a Render disk mounted at `/var/data`.
5. Deploy and open `https://your-service-name.onrender.com/health`; it should return `{"ok":true,"service":"Saksham JoinGate"}`.
6. Copy the exact service HTTPS URL into `WEB_BASE_URL` and redeploy if needed.

## Owner ID
Send `/id` to the bot in a private chat. Put the numeric ID in Render's `OWNER_ID` variable. Never put the bot token in GitHub.

## Notes
- The Web App must be opened from the bot's private chat. The backend validates Telegram's signed `initData`; a normal browser session is not accepted for verification.
- This starter is designed for one target group and one required channel. Test with a second account before inviting members.
- Render free services may sleep, and a bot's long-polling process may be interrupted when the service sleeps.
