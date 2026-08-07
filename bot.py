import asyncio
import os
import re
import tempfile

import discord
from discord.ext import commands
from gtts import gTTS

import config


# ==========================================
# LOAD OPUS
# ==========================================

OPUS_PATH = "/opt/homebrew/lib/libopus.dylib"

try:
    if not discord.opus.is_loaded():
        discord.opus.load_opus(OPUS_PATH)

    print(f"Opus loaded: {discord.opus.is_loaded()}")

except Exception as error:
    print(f"OPUS ERROR: {repr(error)}")


# ==========================================
# BOT SETUP
# ==========================================

intents = discord.Intents.all()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# ==========================================
# TTS SETTINGS
# ==========================================

tts_enabled = False
tts_queue = asyncio.Queue()
tts_worker_task = None

FFMPEG_PATH = "/opt/homebrew/bin/ffmpeg"


# ==========================================
# LANGUAGE DETECTION
# ==========================================

def detect_language(text: str) -> str:

    # Hindi / Devanagari
    if re.search(r"[\u0900-\u097F]", text):
        return "hi"

    # Default to English
    return "en"


# ==========================================
# TTS WORKER
# ==========================================

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

            # Wait for currently playing audio
            while voice_client.is_playing():
                await asyncio.sleep(0.2)

            language = detect_language(text)

            print("--------------------------------")
            print(f"TTS: [{language}] {text}")

            # Create temporary MP3 file
            with tempfile.NamedTemporaryFile(
                suffix=".mp3",
                delete=False
            ) as temp:

                audio_file = temp.name

            print(
                f"Creating audio file: {audio_file}"
            )

            # Generate speech
            tts = gTTS(
                text=text,
                lang=language,
                slow=False
            )

            await asyncio.to_thread(
                tts.save,
                audio_file
            )

            # Check file
            if not os.path.exists(audio_file):

                print(
                    "TTS ERROR: MP3 file was not created."
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
                    "TTS ERROR: MP3 file is empty."
                )

                continue

            # Check Opus
            if not discord.opus.is_loaded():

                print(
                    "TTS ERROR: Opus is not loaded."
                )

                continue

            # Check voice connection again
            voice_client = guild.voice_client

            if voice_client is None:
                continue

            if not voice_client.is_connected():
                continue

            # Event for playback completion
            finished = asyncio.Event()

            def after_play(error):

                if error:
                    print(
                        f"Playback error: {repr(error)}"
                    )

                bot.loop.call_soon_threadsafe(
                    finished.set
                )

            # Create FFmpeg source
            source = discord.FFmpegPCMAudio(
                audio_file,
                executable=FFMPEG_PATH
            )

            print(
                "Playing TTS audio..."
            )

            # Play audio
            voice_client.play(
                source,
                after=after_play
            )

            await finished.wait()

            print(
                "TTS playback finished."
            )

        except Exception as error:

            print(
                f"TTS ERROR: {repr(error)}"
            )

        finally:

            # Remove temporary file
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
                        f"Could not remove temporary "
                        f"file: {repr(error)}"
                    )

            tts_queue.task_done()


# ==========================================
# BOT READY
# ==========================================

@bot.event
async def on_ready():

    global tts_worker_task

    await bot.tree.sync()

    # Start TTS worker
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


# ==========================================
# MESSAGE LISTENER
# ==========================================

@bot.event
async def on_message(
    message: discord.Message
):

    # Ignore bots
    if message.author.bot:
        return

    # Keep normal commands working
    await bot.process_commands(message)

    # TTS disabled
    if not tts_enabled:
        return

    # Ignore DMs
    if message.guild is None:
        return

    # Get voice client
    voice_client = message.guild.voice_client

    if voice_client is None:
        return

    if not voice_client.is_connected():
        return

    # Get message
    text = message.content.strip()

    if not text:
        return

    # Don't speak commands
    if text.startswith(("!", "/")):
        return

    # Prevent extremely long messages
    if len(text) > 500:
        text = text[:500] + "..."

    print(
        f"Message from {message.author}: {text}"
    )

    await tts_queue.put(
        (
            text,
            message.guild.id
        )
    )


# ==========================================
# /PING
# ==========================================

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


# ==========================================
# /HELLO
# ==========================================

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


# ==========================================
# /VIOLETJOIN
# ==========================================

@bot.tree.command(
    name="violetjoin",
    description="Join your current voice channel."
)
async def violetjoin(
    interaction: discord.Interaction
):

    global tts_enabled

    print("================================")
    print("VIOLETJOIN RECEIVED")
    print(f"User: {interaction.user}")
    print(f"Guild: {interaction.guild}")

    # User must be in voice
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

            print(
                "Violet is already connected."
            )

            # Move to user's channel
            if voice_client.channel != channel:

                print(
                    f"Moving Violet to: "
                    f"{channel.name}"
                )

                await voice_client.move_to(
                    channel
                )

        # Not connected
        else:

            print(
                f"Connecting Violet to: "
                f"{channel.name}"
            )

            voice_client = await channel.connect()

        # Enable TTS
        tts_enabled = True

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


# ==========================================
# /LEAVE
# ==========================================

@bot.tree.command(
    name="leave",
    description="Leave the voice channel."
)
async def leave(
    interaction: discord.Interaction
):

    global tts_enabled

    voice_client = interaction.guild.voice_client

    if voice_client is None:

        await interaction.response.send_message(
            "❌ Violet isn't in a voice channel.",
            ephemeral=True
        )

        return

    try:

        # Disable TTS
        tts_enabled = False

        # Stop audio
        if voice_client.is_playing():

            voice_client.stop()

        # Clear TTS queue
        while not tts_queue.empty():

            try:

                tts_queue.get_nowait()
                tts_queue.task_done()

            except asyncio.QueueEmpty:

                break

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


# ==========================================
# /TTS
# ==========================================

@bot.tree.command(
    name="tts",
    description="Enable or disable TTS."
)
async def tts(
    interaction: discord.Interaction,
    enabled: bool
):

    global tts_enabled

    voice_client = interaction.guild.voice_client

    if enabled:

        if voice_client is None:

            await interaction.response.send_message(
                "❌ Violet isn't in a voice channel.\n"
                "Use `/violetjoin` first.",
                ephemeral=True
            )

            return

        tts_enabled = True

        await interaction.response.send_message(
            "🔊 TTS enabled."
        )

        print(
            "TTS enabled."
        )

    else:

        tts_enabled = False

        if voice_client:

            if voice_client.is_playing():

                voice_client.stop()

        # Clear queue
        while not tts_queue.empty():

            try:

                tts_queue.get_nowait()
                tts_queue.task_done()

            except asyncio.QueueEmpty:

                break

        await interaction.response.send_message(
            "🔇 TTS disabled."
        )

        print(
            "TTS disabled."
        )


# ==========================================
# START BOT
# ==========================================

bot.run(config.DISCORD_TOKEN)