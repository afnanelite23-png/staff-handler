import base64

# These custom icons will be stored on the bot application.
APP_EMOJI_ASSETS = {
    "squarecheck": "https://cdn3.emoji.gg/emojis/3004-square-checkmark.png",
    "xmark": "https://cdn3.emoji.gg/emojis/8118-xmark.png",
    "roleowner": "https://cdn3.emoji.gg/emojis/221415-holographicownerroleicon.png",
    "roleadmin": "https://cdn3.emoji.gg/emojis/958314-adminroleicon.png",
    "rolebot": "https://cdn3.emoji.gg/emojis/990565-botroleicon.png",
    "redadmin": "https://cdn3.emoji.gg/emojis/14489-redheadadminroleicon.png",
    "greenadmin": "https://cdn3.emoji.gg/emojis/357319-greenheadadminroleicon.png",
    "rolestaff": "https://cdn3.emoji.gg/emojis/845855-staffroleicon.png",
    "redmod": "https://cdn3.emoji.gg/emojis/694231-redmodroleicon.png",
    "adminicon2": "https://cdn3.emoji.gg/emojis/361076-adminroleicon.png",
    "adminicon3": "https://cdn3.emoji.gg/emojis/114992-adminroleicon.png",
}

ICON_NAMES = {
    "check": "squarecheck",
    "cross": "xmark",
    "owner": "roleowner",
    "admin": "redadmin",
    "bot": "rolebot",
    "staff": "rolestaff",
    "mod": "redmod",
    "info": "roleadmin",
    "notice": "adminicon2",
    "shield": "greenadmin",
}

APP_EMOJI_TAGS = {}


def get_emoji(guild, key, fallback="›"):
    # Application emojis work across this app's servers.
    name = ICON_NAMES.get(key, key)
    return APP_EMOJI_TAGS.get(name, fallback)


async def install_application_emojis():
    if not bot.user or not TOKEN:
        return

    api_url = f"https://discord.com/api/v10/applications/{bot.user.id}/emojis"
    headers = {"Authorization": f"Bot {TOKEN}"}

    async with aiohttp.ClientSession() as session:
        # Load the emojis already saved to the application.
        async with session.get(api_url, headers=headers) as response:
            if response.status != 200:
                logging.error("Could not list application emojis: %s", await response.text())
                return
            data = await response.json()

        for item in data.get("items", []):
            APP_EMOJI_TAGS[item["name"]] = f"<:{item['name']}:{item['id']}>"

        # Upload any missing icon images to the application.
        for name, image_url in APP_EMOJI_ASSETS.items():
            if name in APP_EMOJI_TAGS:
                continue

            try:
                async with session.get(
                    image_url,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as image_response:
                    if image_response.status != 200:
                        logging.warning("Could not download emoji %s", name)
                        continue
                    image_data = await image_response.read()

                encoded_image = base64.b64encode(image_data).decode("ascii")
                payload = {
                    "name": name,
                    "image": f"data:image/png;base64,{encoded_image}",
                }

                async with session.post(
                    api_url,
                    headers=headers,
                    json=payload,
                ) as upload_response:
                    if upload_response.status not in (200, 201):
                        logging.warning(
                            "Could not save application emoji %s: %s",
                            name,
                            await upload_response.text(),
                        )
                        continue

                    emoji = await upload_response.json()
                    APP_EMOJI_TAGS[name] = f"<:{emoji['name']}:{emoji['id']}>"
                    logging.info("Saved application emoji: %s", name)

                await asyncio.sleep(1)

            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                logging.warning("Emoji upload failed for %s: %s", name, exc)
