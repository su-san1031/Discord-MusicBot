# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
import random
import json
import os
import logging
import pygame
from playwright.async_api import async_playwright
from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials
from collections import deque

# Spotify APIのクライアントIDとクライアントシークレット
SPOTIFY_CLIENT_ID = "クライアントID"
SPOTIFY_CLIENT_SECRET = "クライアントシークレット"

# Spotifyクライアントの設定
spotify = Spotify(auth_manager=SpotifyClientCredentials(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET
))

# グローバル変数
queue = deque()
current_song = {"title": None, "url": None}
loop_mode = False

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot_error.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# Botの設定
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

# 定数
YDL_OPTIONS = {
    'format': 'bestaudio[ext=opus]/bestaudio/best',
    'noplaylist': 'True',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'opus',
        'preferredquality': '192',
    }],
    'concurrent-fragments': 5,  # フラグメントの並列ダウンロード数
    'throttled-rate': None,  # 帯域幅制限を解除
    'retries': 10,  # リトライ回数を増加
    'cookiefile': 'youtube_cookies.txt',  # Cookieの利用
}
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -af "volume=0.02, bass=g=0, treble=g=1, aresample=48000"',
    'options': '-vn',  # 映像を無効化
}

async def get_youtube_music_cookies():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        await page.goto("https://music.youtube.com")
        print("ログインが完了したらEnterを押してください")
        input()
        cookies = await context.cookies()
        await browser.close()

        # Netscape形式のヘッダー
        cookie_str = "# Netscape HTTP Cookie File\n"
        for c in cookies:
            domain = c['domain']
            flag = "TRUE" if domain.startswith('.') else "FALSE"
            path = c['path']
            secure = "TRUE" if c.get('secure', False) else "FALSE"
            expiry = int(c['expires']) if c.get('expires') else 0
            name = c['name']
            value = c['value']
            cookie_str += f"{domain}\t{flag}\t{path}\t{secure}\t{expiry}\t{name}\t{value}\n"

        with open("youtube_cookies.txt", "w", encoding="utf-8") as f:
            f.write(cookie_str)

# キューの保存と復元
QUEUE_FILE = "queue.json"

def save_queue():
    with open(QUEUE_FILE, "w") as f:
        json.dump(list(queue), f)

def load_queue():
    global queue
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, "r") as f:
            queue = deque(json.load(f))

# Bot起動時のイベント
@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user.name}')
    print(f'Logged in as {bot.user.name}')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s).")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

# ボイスチャンネル内のユーザーがいなくなったら自動退出
@bot.event
async def on_voice_state_update(member, before, after):
    # ボイスチャンネルの状態が変化したときに呼び出される
    voice_client = discord.utils.get(bot.voice_clients, guild=member.guild)
    if voice_client and voice_client.channel:  # ボットがボイスチャンネルに接続している場合
        # ボイスチャンネル内のメンバーを取得
        channel_members = voice_client.channel.members
        # ボット以外のメンバーがいない場合
        if len([m for m in channel_members if not m.bot]) == 0:
            await voice_client.disconnect()
            logging.info(f"ボイスチャンネル {voice_client.channel.name} から退出しました（メンバーがいなくなったため）。")

     
# Slash Command: ボイスチャンネルに参加
@bot.tree.command(name="join", description="ボイスチャンネルに参加します。")
async def join(interaction: discord.Interaction):
    if interaction.user.voice:
        channel = interaction.user.voice.channel
        voice_client = await channel.connect()  # ここで voice_client を取得
        await interaction.response.send_message("✅ にゃーん！こころ、ボイスチャンネルにおじゃましま〜すっ！")

        # 音源を再生
        audio_source = discord.FFmpegPCMAudio("join_sound.mp3")
        if not voice_client.is_playing():
            voice_client.play(audio_source)
    else:
        await interaction.response.send_message("❌ ボイスチャンネルに参加してからコマンドを使ってください。", ephemeral=True)

# Slash Command: ボイスチャンネルから退出
@bot.tree.command(name="leave", description="ボイスチャンネルから退出します。")
async def leave(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
        queue.clear()
        save_queue()
        await interaction.response.send_message("✅ ふにゃ〜、ちょっと抜けるね！またあとでにゃ！")
    else:
        await interaction.response.send_message("❌ むむっ？ボイスチャンネルに入ってないみたいにゃ〜", ephemeral=True)

# Slash Command: 曲を再生
@bot.tree.command(name="play", description="曲を再生します。")
@app_commands.describe(url="再生する曲のURL")
async def play(interaction: discord.Interaction, url: str):
    try:
        if not interaction.guild.voice_client:
            if interaction.user.voice:
                await interaction.user.voice.channel.connect()
            else:
                await interaction.response.send_message("❌ ボイスチャンネルに入ってきてにゃ〜！みんなでわいわいしよっ！", ephemeral=True)
                return

        await interaction.response.defer()  # 応答を遅延

        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(url, download=False)

            # 再生リストが検出された場合
            if 'entries' in info:
                await interaction.followup.send("❌ 再生リストはサポートされていません。単一の動画URLを指定してください。", ephemeral=True)
                return

            # 単一動画の場合
            video_url = info['url']
            queue.append(video_url)
            await interaction.followup.send(f"🎶 曲をキューに追加しました: **{info.get('title', 'Unknown Title')}**")

        # 再生中でない場合は次の曲を再生
        if not interaction.guild.voice_client.is_playing():
            await play_next(interaction.guild.voice_client)
    except Exception as e:
        await interaction.followup.send(f"⚠️ エラーが発生しました: {str(e)}", ephemeral=True)


        # Spotifyリンクの処理
        if "open.spotify.com" in url:
            try:
                track_info = spotify.track(url)
                track_name = track_info["name"]
                artist_name = track_info["artists"][0]["name"]
                search_query = f"{track_name} {artist_name}"
                await interaction.followup.send(f"🔍 Spotifyの曲を検索中: **{search_query}**")
                
                # YouTubeで検索して再生
                with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                    info = ydl.extract_info(f"ytsearch:{search_query}", download=False)['entries'][0]
                    url = info['url']
                    title = info['title']
                    queue.append(url)
                    await interaction.followup.send(f"🎶 見つけたよ！再生する曲: **{title}**")
            except Exception as e:
                await interaction.followup.send(f"⚠️ Spotifyの曲情報を取得できませんでした: {str(e)}", ephemeral=True)
                return

        if interaction.guild.voice_client.is_playing():
            queue.append(url)
            await interaction.followup.send("📥 おっけーにゃ！曲をキューに追加したよ〜♪")
        else:
            queue.append(url)
            await play_next(interaction.guild.voice_client)
            await interaction.followup.send("🎶 よーし、音楽スタートにゃ！いっしょに楽しも〜！")
    except Exception as e:
        # エラーが発生した場合も followup を使用
        await interaction.followup.send(f"⚠️ にゃにゃ！？エラーが出ちゃったのだ……ちょっと待っててにゃ！: {str(e)}", ephemeral=True)

async def play_next(voice_client):
    global current_song
    if queue:
        url = queue.popleft()
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(url, download=False)
            current_song["title"] = info.get("title", "Unknown Title")
            current_song["url"] = url
            audio_source = discord.FFmpegPCMAudio(info["url"], **FFMPEG_OPTIONS)
            # PCMVolumeTransformer を使用
            voice_client.play(discord.PCMVolumeTransformer(audio_source, volume=0.08),  
                              after=lambda e: asyncio.run_coroutine_threadsafe(play_next(voice_client), bot.loop))
        save_queue()
    elif loop_mode and current_song["url"]:
        # ループモードが有効で、現在の曲が存在する場合
        url = current_song["url"]
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(url, download=False)
            audio_source = discord.FFmpegPCMAudio(info["url"], **FFMPEG_OPTIONS)
            voice_client.play(discord.PCMVolumeTransformer(audio_source, volume=0.08),  # 初期音量50%
                              after=lambda e: asyncio.run_coroutine_threadsafe(play_next(voice_client), bot.loop))
    else:
        # キューが空の場合、現在の曲情報をリセット
        current_song = {"title": None, "url": None}
        logging.info("キューはぜ〜んぶ再生し終わったよっ！でもこころは、まだボイスチャンネルにいるからねっ、いつでもお相手するにゃ〜♪")

# Slash Command: 曲をスキップ
@bot.tree.command(name="skip", description="現在再生中の曲をスキップします。")
async def skip(interaction: discord.Interaction):
    if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("⏭️ にゃっ！次の曲にスキップしちゃうよ〜♪ わくわく〜！")
    else:
        await interaction.response.send_message("えっ？今は何も再生してないみたいにゃ〜…しょんぼり……", ephemeral=True)

# Slash Command: 再生を停止
@bot.tree.command(name="stop", description="再生を停止し、キューをクリアします。")
async def stop(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        interaction.guild.voice_client.stop()
        queue.clear()
        save_queue()
        await interaction.response.send_message("⏹️ ストップにゃ！曲もキューも全部お片付けしちゃったよ〜！")
    else:
        await interaction.response.send_message("今は流れてる曲がないみたいにゃ〜、ちょっぴり静かだねっ", ephemeral=True)

# Slash Command: 再生キューを表示
@bot.tree.command(name="queue_list", description="再生キューを表示します。")
async def queue_list(interaction: discord.Interaction):
    if queue:
        msg = '\n'.join([f"{i+1}. {url}" for i, url in enumerate(queue)])
        await interaction.response.send_message(f"🎵 **再生キュー：**\n{msg}")
    else:
        await interaction.response.send_message("📭 キューがすっからかんにゃ！なにか追加してほしいのだ〜！")

# Slash Command: 現在再生中の曲を表示
@bot.tree.command(name="now_playing", description="現在再生中の曲を表示します。")
async def now_playing(interaction: discord.Interaction):
    if current_song["title"]:
        await interaction.response.send_message(f"🎶 現在再生中: **{current_song['title']}**\n🔗 URL: {current_song['url']}")
    else:
        await interaction.response.send_message("今は音楽流れてないにゃ〜。お耳がさみしいよぉ…！。")

# Slash Command: キューをシャッフル
@bot.tree.command(name="shuffle", description="再生キューをシャッフルします。")
async def shuffle(interaction: discord.Interaction):
    random.shuffle(queue)
    save_queue()
    await interaction.response.send_message("🔀 曲をシャッフルしちゃったにゃっ♪どれがくるかな〜？どきどきっ！")

@bot.tree.command(name="volume", description="音量を調整します。")
@app_commands.describe(volume="音量の値 (0-100)")
async def volume(interaction: discord.Interaction, volume: int):
    if interaction.guild.voice_client and isinstance(interaction.guild.voice_client.source, discord.PCMVolumeTransformer):
        # 音量を設定
        interaction.guild.voice_client.source.volume = volume / 100
        await interaction.response.send_message(f"🔊 音量を {volume}% に設定しました。")
    else:
        await interaction.response.send_message("現在再生中の曲がありません。", ephemeral=True)

# Slash Command: 曲を検索して再生
@bot.tree.command(name="search", description="曲を検索して再生します。")
@app_commands.describe(query="検索する曲のキーワード")
async def search(interaction: discord.Interaction, query: str):
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        try:
            info = ydl.extract_info(f"ytsearch:{query}", download=False)['entries'][0]
            url = info['url']
            title = info['title']
            queue.append(url)
            await interaction.response.send_message(f"🔍 検索結果: **{title}** をキューに追加しました。")
            if not interaction.guild.voice_client.is_playing():
                await play_next(interaction.guild.voice_client)
        except Exception as e:
            await interaction.response.send_message(f"⚠️ 検索中にエラーが発生しました: {str(e)}", ephemeral=True)

# Slash Command: ループ再生を切り替え
@bot.tree.command(name="loop", description="ループ再生を切り替えます。")
async def loop(interaction: discord.Interaction):
    global loop_mode
    loop_mode = not loop_mode
    status = "有効" if loop_mode else "無効"
    await interaction.response.send_message(f"🔁 ループ再生を {status} に設定しました。")

# Slash Command: タイマー機能
@bot.tree.command(name="timer", description="再生を停止するタイマーを設定します。")
@app_commands.describe(minutes="タイマーの時間 (分)")
async def timer(interaction: discord.Interaction, minutes: int):
    await interaction.response.send_message(f"⏱️ {minutes}分後に再生を停止します。")
    await asyncio.sleep(minutes * 60)
    if interaction.guild.voice_client:
        interaction.guild.voice_client.stop()
        queue.clear()
        save_queue()
        await interaction.followup.send("⏹️ タイマーが終了しました。再生を停止しました。")

# Slash Command: ヘルプコマンド
@bot.tree.command(name="amyahelp", description="音楽ボットのコマンド一覧を表示します。")
async def amyahelp(interaction: discord.Interaction):
    commands = """
    🎵 **音楽ボットコマンド一覧**:
    - `/join`: ボイスチャンネルに参加
    - `/leave`: ボイスチャンネルから退出
    - `/play <URL>`: 曲を再生
    - `/skip`: 曲をスキップ
    - `/stop`: 再生を停止
    - `/queue_list`: 再生キューを表示
    - `/now_playing`: 現在再生中の曲を表示
    - `/shuffle`: キューをシャッフル
    - `/volume <数値>`: 音量を調整
    - `/loop`: ループ再生を切り替え
    - `/timer <分>`: 再生を停止するタイマーを設定
    """
    await interaction.response.send_message(commands)

# Botを起動
import asyncio

# トークンを直接指定
token = "トークン"

if not token:
    raise ValueError("トークンが設定されていません。")

async def main():
    try:
        await bot.start(token)
    except KeyboardInterrupt:
        await bot.close()

asyncio.run(main())
