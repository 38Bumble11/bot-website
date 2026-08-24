import os
import sqlite3
import threading
from discord.ext import commands
import discord
from flask import Flask, redirect, render_template, request, session, url_for
import requests

# ==================== DATABASE SETUP ====================
conn = sqlite3.connect("stats.db", check_same_thread=False)
cursor = conn.cursor()

# Create tables if they don't exist yet
cursor.execute(
    """CREATE TABLE IF NOT EXISTS messages (user_id TEXT, count INTEGER)"""
)
cursor.execute(
    """CREATE TABLE IF NOT EXISTS warns (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, moderator_id TEXT, reason TEXT, timestamp TEXT)"""
)
cursor.execute(
    """CREATE TABLE IF NOT EXISTS mutes (user_id TEXT, reason TEXT)"""
)
conn.commit()

# ==================== DISCORD BOT SETUP ====================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
  print(f"Logged in as {bot.user} (ID: {bot.user.id})")
  try:
    synced = await bot.tree.sync()
    print(f"Synced {len(synced)} slash commands.")
  except Exception as e:
    print(e)


# Example message tracker event for your database
@bot.event
async def on_message(message):
  if message.author.bot:
    return

  # Track message count in SQLite
  cursor.execute(
      "SELECT count FROM messages WHERE user_id = ?", (str(message.author.id),)
  )
  row = cursor.fetchone()
  if row:
    cursor.execute(
        "UPDATE messages SET count = count + 1 WHERE user_id = ?",
        (str(message.author.id),),
    )
  else:
    cursor.execute(
        "INSERT INTO messages (user_id, count) VALUES (?, 1)",
        (str(message.author.id),),
    )
  conn.commit()

  await bot.process_commands(message)


# Example Slash Command: /warn
@bot.tree.command(name="warn", description="Warn a user")
async def warn(
    interaction: discord.Interaction, member: discord.Member, reason: str
):
  cursor.execute(
      "INSERT INTO warns (user_id, moderator_id, reason, timestamp) VALUES"
      " (?, ?, ?, datetime('now'))",
      (str(member.id), str(interaction.user.id), reason),
  )
  conn.commit()
  await interaction.response.send_message(
      f"⚠️ Warned {member.mention} for: {reason}", ephemeral=True
  )


# ==================== FLASK WEBSITE SETUP ====================
app = Flask(__name__)
app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY", "super_secret_random_key_here"
)

# Discord OAuth2 Credentials (Replace these with your values from Discord Developer Portal)
CLIENT_ID = "1541430888494141450"
CLIENT_SECRET = "s2vuNcDpIU2QYCcRhTVZc3PoR3oGGwYF"
REDIRECT_URI = (
    "http://localhost:5000/callback"  # Update this when you host online
)


@app.route("/")
def admin_dashboard():
  if "user" not in session:
    return render_template("index.html")

  # Fetch statistics for cards
  cursor.execute("SELECT SUM(count) FROM messages")
  msg_row = cursor.fetchone()
  total_messages = msg_row[0] if msg_row and msg_row[0] else 0

  cursor.execute("SELECT COUNT(*) FROM warns")
  warn_row = cursor.fetchone()
  total_warns = warn_row[0] if warn_row else 0

  cursor.execute("SELECT COUNT(*) FROM mutes")
  mute_row = cursor.fetchone()
  total_mutes = mute_row[0] if mute_row else 0

  # Fetch all warning records for the admin table
  cursor.execute("SELECT id, user_id, moderator_id, reason, timestamp FROM warns")
  warning_list = cursor.fetchall()

  return render_template(
      "index.html",
      messages=total_messages,
      warns=total_warns,
      mutes=total_mutes,
      warning_list=warning_list,
  )


@app.route("/login")
def login():
  discord_login_url = (
      f"https://discord.com/api/oauth2/authorize?client_id={CLIENT_ID}"
      f"&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify+guilds"
  )
  return redirect(discord_login_url)


@app.route("/callback")
def callback():
  code = request.args.get("code")
  if not code:
    return redirect(url_for("admin_dashboard"))

  data = {
      "client_id": CLIENT_ID,
      "client_secret": CLIENT_SECRET,
      "grant_type": "authorization_code",
      "code": code,
      "redirect_uri": REDIRECT_URI,
  }
  headers = {"Content-Type": "application/x-www-form-urlencoded"}
  response = requests.post(
      "https://discord.com/api/oauth2/token", data=data, headers=headers
  )
  access_token = response.json().get("access_token")

  if not access_token:
    return "Failed to authenticate with Discord.", 400

  user_headers = {"Authorization": f"Bearer {access_token}"}
  user_info = requests.get(
      "https://discord.com/api/users/@me", headers=user_headers
  ).json()

  session["user"] = {
      "username": user_info.get("username"),
      "id": user_info.get("id"),
  }
  return redirect(url_for("admin_dashboard"))


@app.route("/logout")
def logout():
  session.pop("user", None)
  return redirect(url_for("admin_dashboard"))


@app.route("/delwarn/<int:warning_id>", methods=["POST"])
def web_delwarn(warning_id):
  if "user" not in session:
    return redirect(url_for("admin_dashboard"))

  cursor.execute("DELETE FROM warns WHERE id = ?", (warning_id,))
  conn.commit()
  return redirect(url_for("admin_dashboard"))


# ==================== RUN BOTH BOT & WEBSITE ====================
def run_flask():
  app.run(host="0.0.0.0", port=5000)


if __name__ == "__main__":
  # Run Flask in a separate background thread so the Discord bot can run simultaneously
  flask_thread = threading.Thread(target=run_flask)
  flask_thread.start()

  # Run your Discord bot using your bot token
  bot.run("YOUR_DISCORD_BOT_TOKEN")
