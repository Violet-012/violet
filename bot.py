import asyncio
import os
import re
import tempfile

import discord
from discord.ext import commands
import edge_tts

import config


# =========================================================
# OPUS
# =========================================================

OPUS_PATH = "/opt/homebrew/lib/libopus.dylib"

try:
    if not discord.opus.is_loaded():
        discord.opus.load_opus(OPUS_PATH)

    print(f"Opus loaded: {discord.opus.is_loaded()}")

except Exception as error:
    print(f"OPUS ERROR: {repr(error)}")


# =========================================================
# BOT SETUP
# =========================================================

intents = discord.Intents.all()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================================================
# TTS SETTINGS
# =========================================================

tts_enabled = {}

tts_queue = asyncio.Queue()

tts_worker_task = None

FFMPEG_PATH = "/opt/homebrew/bin/ffmpeg"


# =========================================================
# VOICES
# =========================================================

# Main Violet voice
ENGLISH_VOICE = "en-US-AvaNeural"

# Hindi voice
HINDI_VOICE = "hi-IN-SwaraNeural"


# =========================================================
# VOICE STYLE
# =========================================================

TTS_RATE = "-5%"
TTS_PITCH = "+2Hz"
TTS_VOLUME = "+0%"


# =========================================================
# SPEAKER TRACKING
# =========================================================

# Stores the last speaker for each Discord server.
#
# Example:
#
# Server A -> Aarav
# Server B -> Rahul

last_speaker = {}


# =========================================================
# LANGUAGE DETECTION
# =========================================================

def detect_language(text: str):

    # Detect Hindi / Devanagari characters
    if re.search(r"[\u0900-\u097F]", text):
        return "hi"

    return "en"


# =========================================================
# GET VOICE
# =========================================================

def get_voice(text: str):

    language = detect_language(text)

    if language == "hi":
        return HINDI_VOICE

    return ENGLISH_VOICE


# =========================================================
# GENERATE TTS
# =========================================================

async def generate_tts(text, filename):

    voice = get_voice(text)

    print(f"TTS voice: {voice}")

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=TTS_RATE,
        pitch=TTS_PITCH,
        volume=TTS_VOLUME
    )

    await communicate.save(filename)


# =========================================================
# TTS WORKER
# =========================================================

async def tts_worker():

    while True:

        text, guild_id = await tts_queue.get()

        audio_file = None

        try:

            guild = bot.get_guild(guild_id)

            if guild is None:
                continue

            voice_client = guild.voice_client

            if voice_client is None:
                continue

            if not voice_client.is_connected():
                continue

            # Wait for current audio
            while voice_client.is_playing():

                await asyncio.sleep(0.2)

            print("--------------------------------")
            print(f"TTS: {text}")

            # -------------------------------------------------
            # CREATE TEMPORARY MP3
            # -------------------------------------------------

            with tempfile.NamedTemporaryFile(
                suffix=".mp3",
                delete=False
            ) as temp:

                audio_file = temp.name

            print(
                f"Creating audio file: {audio_file}"
            )

            # -------------------------------------------------
            # GENERATE TTS
            # -------------------------------------------------

            await generate_tts(
                text,
                audio_file
            )

            # -------------------------------------------------
            # CHECK FILE
            # -------------------------------------------------

            if not os.path.exists(audio_file):

                print(
                    "TTS ERROR: Audio file was not created."
                )

                continue

            file_size = os.path.getsize(
                audio_file
            )

            print(
                f"Audio file created: {file_size} bytes"
            )

            if file_size == 0:

                print(
                    "TTS ERROR: Audio file is empty."
                )

                continue

            # -------------------------------------------------
            # CHECK OPUS
            # -------------------------------------------------

            if not discord.opus.is_loaded():

                print(
                    "TTS ERROR: Opus is not loaded."
                )

                continue

            # -------------------------------------------------
            # CHECK CONNECTION
            # -------------------------------------------------

            voice_client = guild.voice_client

            if voice_client is None:
                continue

            if not voice_client.is_connected():
                continue

            # -------------------------------------------------
            # PLAYBACK EVENT
            # -------------------------------------------------

            finished = asyncio.Event()

            def after_play(error):

                if error:

                    print(
                        f"Playback error: {repr(error)}"
                    )

                bot.loop.call_soon_threadsafe(
                    finished.set
                )

            # -------------------------------------------------
            # FFMPEG
            # -------------------------------------------------

            source = discord.FFmpegPCMAudio(
                audio_file,
                executable=FFMPEG_PATH
            )

            print(
                "Playing TTS audio..."
            )

            voice_client.play(
                source,
                after=after_play
            )

            # Wait until audio finishes
            await finished.wait()

            print(
                "TTS playback finished."
            )

        except Exception as error:

            print(
                f"TTS ERROR: {repr(error)}"
            )

        finally:

            # -------------------------------------------------
            # DELETE TEMPORARY FILE
            # -------------------------------------------------

            if (
                audio_file
                and os.path.exists(audio_file)
            ):

                try:

                    os.remove(audio_file)

                    print(
                        "Temporary audio file removed."
                    )

                except Exception as error:

                    print(
                        "Could not remove temporary "
                        f"file: {repr(error)}"
                    )

            tts_queue.task_done()


# =========================================================
# BOT READY
# =========================================================

@bot.event
async def on_ready():

    global tts_worker_task

    await bot.tree.sync()

    # Start TTS worker once
    if (
        tts_worker_task is None
        or tts_worker_task.done()
    ):

        tts_worker_task = asyncio.create_task(
            tts_worker()
        )

    print("--------------------------------")
    print(f"Logged in as: {bot.user}")
    print("Bot is ready.")
    print("Slash commands synced.")
    print("--------------------------------")


# =========================================================
# MESSAGE LISTENER
# =========================================================

@bot.event
async def on_message(
    message: discord.Message
):

    # Ignore bots
    if message.author.bot:
        return

    # Keep commands working
    await bot.process_commands(message)

    # Ignore DMs
    if message.guild is None:
        return

    guild_id = message.guild.id

    # Check TTS
    if not tts_enabled.get(guild_id, False):
        return

    # Check voice connection
    voice_client = message.guild.voice_client

    if voice_client is None:
        return

    if not voice_client.is_connected():
        return

    # Get message text
    message_text = message.content.strip()

    if not message_text:
        return

    # Don't speak commands
    if message_text.startswith(("!", "/")):
        return

    # Limit extremely long messages
    if len(message_text) > 500:

        message_text = (
            message_text[:500]
            + "..."
        )

    # Get display name
    username = message.author.display_name

    # Remove @ from name
    username = username.replace(
        "@",
        ""
    )

    # -------------------------------------------------------
    # SMART SPEAKER SYSTEM
    # -------------------------------------------------------

    previous_speaker = last_speaker.get(
        guild_id
    )

    current_speaker = message.author.id

    # Same person continues talking
    if previous_speaker == current_speaker:

        spoken_text = message_text

    # New person starts talking
    else:

        spoken_text = (
            f"{username} said, "
            f"{message_text}"
        )

        last_speaker[guild_id] = current_speaker

    # -------------------------------------------------------
    # LOG
    # -------------------------------------------------------

    print(
        f"Message from {username}: "
        f"{message_text}"
    )

    print(
        f"Speaking: {spoken_text}"
    )

    # Add to TTS queue
    await tts_queue.put(
        (
            spoken_text,
            guild_id
        )
    )


# =========================================================
# /PING
# =========================================================

@bot.tree.command(
    name="ping",
    description="Check Violet's latency."
)
async def ping(
    interaction: discord.Interaction
):

    latency = round(
        bot.latency * 1000
    )

    await interaction.response.send_message(
        f"🏓 Pong! `{latency}ms`"
    )


# =========================================================
# /HELLO
# =========================================================

@bot.tree.command(
    name="hello",
    description="Say hello to Violet."
)
async def hello(
    interaction: discord.Interaction
):

    await interaction.response.send_message(
        "Hey! 👋"
    )


# =========================================================
# /VIOLETJOIN
# =========================================================

@bot.tree.command(
    name="violetjoin",
    description="Join your current voice channel."
)
async def violetjoin(
    interaction: discord.Interaction
):

    guild_id = interaction.guild.id

    print("================================")
    print("VIOLETJOIN RECEIVED")
    print(f"User: {interaction.user}")
    print(f"Guild: {interaction.guild}")

    # Check user voice
    if interaction.user.voice is None:

        await interaction.response.send_message(
            "❌ You must join a voice channel first.",
            ephemeral=True
        )

        print(
            "User is not in a voice channel."
        )

        return

    channel = interaction.user.voice.channel

    print(
        f"User is in: {channel.name}"
    )

    try:

        voice_client = interaction.guild.voice_client

        # Already connected
        if voice_client is not None:

            if voice_client.channel != channel:

                print(
                    f"Moving Violet to: "
                    f"{channel.name}"
                )

                await voice_client.move_to(
                    channel
                )

        # Connect
        else:

            print(
                f"Connecting Violet to: "
                f"{channel.name}"
            )

            voice_client = await channel.connect()

        # Enable TTS
        tts_enabled[guild_id] = True

        # Reset speaker when Violet joins
        last_speaker.pop(
            guild_id,
            None
        )

        print(
            "Successfully connected to voice."
        )

        await interaction.response.send_message(
            f"🔊 Joined **{channel.name}**!\n"
            f"🗣️ TTS is now enabled."
        )

    except Exception as error:

        print(
            f"VOICE ERROR: {repr(error)}"
        )

        if not interaction.response.is_done():

            await interaction.response.send_message(
                f"❌ Couldn't join the voice channel.\n"
                f"Error: `{error}`",
                ephemeral=True
            )


# =========================================================
# /LEAVE
# =========================================================

@bot.tree.command(
    name="leave",
    description="Leave the voice channel."
)
async def leave(
    interaction: discord.Interaction
):

    guild_id = interaction.guild.id

    voice_client = interaction.guild.voice_client

    if voice_client is None:

        await interaction.response.send_message(
            "❌ Violet isn't in a voice channel.",
            ephemeral=True
        )

        return

    try:

        # Disable TTS
        tts_enabled[guild_id] = False

        # Reset speaker
        last_speaker.pop(
            guild_id,
            None
        )

        # Stop audio
        if voice_client.is_playing():

            voice_client.stop()

        # Disconnect
        await voice_client.disconnect()

        await interaction.response.send_message(
            "👋 Left the voice channel.\n"
            "🔇 TTS disabled."
        )

        print(
            "Violet left the voice channel."
        )

    except Exception as error:

        print(
            f"LEAVE ERROR: {repr(error)}"
        )

        await interaction.response.send_message(
            f"❌ Error: `{error}`",
            ephemeral=True
        )


# =========================================================
# /TTS
# =========================================================

@bot.tree.command(
    name="tts",
    description="Enable or disable TTS."
)
async def tts(
    interaction: discord.Interaction,
    enabled: bool
):

    guild_id = interaction.guild.id

    voice_client = interaction.guild.voice_client

    # Enable
    if enabled:

        if voice_client is None:

            await interaction.response.send_message(
                "❌ Violet isn't in a voice channel.\n"
                "Use `/violetjoin` first.",
                ephemeral=True
            )

            return

        tts_enabled[guild_id] = True

        await interaction.response.send_message(
            "🔊 TTS enabled."
        )

        print(
            f"TTS enabled in "
            f"{interaction.guild.name}."
        )

    # Disable
    else:

        tts_enabled[guild_id] = False

        # Reset speaker
        last_speaker.pop(
            guild_id,
            None
        )

        # Stop current audio
        if voice_client:

            if voice_client.is_playing():

                voice_client.stop()

        await interaction.response.send_message(
            "🔇 TTS disabled."
        )

        print(
            f"TTS disabled in "
            f"{interaction.guild.name}."
        )


# =========================================================
# START BOT
# =========================================================

bot.run(
    config.DISCORD_TOKEN
)