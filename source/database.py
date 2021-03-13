import sqlite3
from datetime import datetime

conn = sqlite3.connect('database.db')
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users (
  twitch_username TEXT    NOT NULL    PRIMARY KEY,
  src_id          TEXT,
  last_fetched    REAL
)''')
c.execute('''CREATE TABLE IF NOT EXISTS tracked_games (
  game_name       TEXT    NOT NULL    PRIMARY KEY,
  src_game_id     TEXT    NOT NULL    UNIQUE,
  discord_channel INTEGER NOT NULL
)''')
c.execute('''CREATE TABLE IF NOT EXISTS personal_bests (
  src_id          TEXT    NOT NULL    FOREIGN KEY users.src_id,
  src_game_id     TEXT    NOT NULL    FOREIGN KEY tracked_games.src_game_id,
  PRIMARY KEY (src_id, src_game_id)
)''')
conn.commit()


def add_user(twitch_username, src_id, fetch_time=datetime.now()):
  try:
    c.execute('INSERT INTO users VALUES (?, ?, ?)', (twitch_username.lower(), src_id, fetch_time.timestamp()))
    conn.commit()
  except sqlite3.IntegrityError:
    pass


def add_game(game_name, src_game_id, discord_channel):
  c.execute('INSERT INTO tracked_games VALUES (?, ?, ?)', (game_name, src_game_id, int(discord_channel)))
  conn.commit()


def add_personal_best(src_id, src_game_id):
  c.execute('INSERT INTO personal_bests VALUES (?, ?)', (src_id, src_game_id)))
  conn.commit()


def update_user_fetch_by_src(src_id):
  c.execute('UPDATE FROM users WHERE src_id=? SET last_fetched=?', (src_id, datetime.now().timestamp()))
  conn.commit()


def get_user(twitch_username):
  c.execute('SELECT * FROM users WHERE twitch_username=?', (twitch_username,))
  if data := c.fetchone():
    return {
      'twitch_username': data[0],
      'src_id': data[1],
      'fetch_time': data[2],
    }
  return None


def get_user_by_src(src_id):
  c.execute('SELECT * FROM users WHERE src_id=?', (src_id,))
  if data := c.fetchone():
    return {
      'twitch_username': data[0],
      'src_id': data[1],
      'fetch_time': data[2],
    }
  return None


def get_game(game_name):
  c.execute('SELECT * FROM tracked_games WHERE game_name LIKE ?', (game_name,))
  if data := c.fetchone():
    return {
      'game_name': data[0],
      'src_game_id': data[1],
      'discord_channel': data[2],
    }
  return None


def has_personal_best(src_id, src_game_id):
  c.execute('SELECT * FROM tracked_games WHERE src_id=? AND src_game_id=?', (src_id, src_game_id))
  return c.fetchone() != None
