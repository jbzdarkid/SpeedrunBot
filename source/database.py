import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

conn = sqlite3.connect(Path(__file__).with_name('database.db'))
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users (
  twitch_username  TEXT    NOT NULL    PRIMARY KEY,
  src_id           TEXT                UNIQUE,
  last_fetched     REAL
)''')
c.execute('''CREATE TABLE IF NOT EXISTS tracked_games (
  game_name        TEXT    NOT NULL    PRIMARY KEY,
  twitch_game_id   TEXT    NOT NULL    UNIQUE,
  src_game_id      TEXT    NOT NULL    UNIQUE,
  discord_channel  INTEGER NOT NULL
)''')
c.execute('''CREATE TABLE IF NOT EXISTS personal_bests (
  src_id           TEXT    NOT NULL,
  src_game_id      TEXT    NOT NULL,
  FOREIGN KEY (src_id)      REFERENCES users (src_id),
  FOREIGN KEY (src_game_id) REFERENCES tracked_games (src_game_id),
  PRIMARY KEY (src_id, src_game_id)
)''')
c.execute('''CREATE TABLE IF NOT EXISTS moderated_games (
  game_name        TEXT    NOT NULL    PRIMARY KEY,
  src_game_id      TEXT    NOT NULL    UNIQUE,
  discord_channel  INTEGER NOT NULL,
  last_update      REAL
)''')
c.execute('''CREATE TABLE IF NOT EXISTS categories (
  category_id      TEXT    NOT NULL    PRIMARY KEY,
  category_name    TEXT    NOT NULL,
  variables        TEXT
)''')
conn.commit()

def execute(sql, *args):
  try:
    c.execute(sql, args)
  except sqlite3.IntegrityError:
    logging.exception('SQL error')
    raise


def add_user(twitch_username, src_id, fetch_time=datetime.now().timestamp()):
  execute('INSERT OR REPLACE INTO users VALUES (?, ?, ?)', twitch_username.lower(), src_id, fetch_time)
  conn.commit()


def add_game(game_name, twitch_game_id, src_game_id, discord_channel):
  try:
    execute('INSERT INTO tracked_games VALUES (?, ?, ?, ?)', game_name, twitch_game_id, src_game_id, int(discord_channel))
  except sqlite3.IntegrityError:
    raise ValueError(f'Game `{game_name}` is already being tracked.')
  conn.commit()


def moderate_game(game_name, src_game_id, discord_channel):
  try:
    execute('INSERT INTO moderated_games VALUES (?, ?, ?, 0)', game_name, src_game_id, int(discord_channel))
  except sqlite3.IntegrityError:
    raise ValueError(f'Game `{game_name}` is already being moderated.')
  conn.commit()


def remove_game(game_name):
  _, src_game_id = get_game_ids(game_name)
  if not src_game_id:
    raise ValueError(f'Cannot remove `{game_name}` as it is not currently being tracked.')

  # Note: There is no need to delete users here -- users are cross-game.
  execute('DELETE FROM personal_bests WHERE src_game_id=?', src_game_id)
  execute('DELETE FROM tracked_games WHERE src_game_id=?', src_game_id)
  conn.commit()


def unmoderate_game(game_name):
  execute('DELETE FROM moderated_games WHERE game_name=?', game_name)
  conn.commit()


def add_personal_best(src_id, src_game_id):
  execute('INSERT INTO personal_bests VALUES (?, ?)', src_id, src_game_id)
  conn.commit()


def update_user_fetch_time(twitch_username, last_fetched=datetime.now().timestamp()):
  execute('UPDATE users SET last_fetched=? WHERE twitch_username=?', last_fetched, twitch_username.lower())
  conn.commit()


def update_game_moderation_time(game_name, last_update=datetime.now().timestamp()):
  execute('UPDATE moderated_games SET last_update=? WHERE game_name=?', last_update, game_name)
  conn.commit()


def get_user(twitch_username):
  execute('SELECT * FROM users WHERE twitch_username=?', twitch_username.lower())
  if data := c.fetchone():
    return {
      'twitch_username': data[0],
      'src_id': data[1],
      'fetch_time': data[2],
    }
  return None


def get_user_by_src(src_id):
  execute('SELECT * FROM users WHERE src_id=?', src_id)
  if data := c.fetchone():
    return {
      'twitch_username': data[0],
      'src_id': data[1],
      'fetch_time': data[2],
    }
  return None


def get_category_name(category_id):
  execute('SELECT category_name FROM categories WHERE category_id=?', category_id)
  data = c.fetchone()
  return data[0] if data else None


def set_category_name(category_id, category_name):
  execute('INSERT INTO categories VALUES (?, ?, ?)', category_id, category_name, None)
  conn.commit()


def get_category_variables(category_id):
  execute('SELECT variables FROM categories WHERE category_id=?', category_id)
  data = c.fetchone()
  if data and data[0]:
    return json.loads(data[0])
  return None


def set_category_variables(category_id, variables):
  execute('UPDATE categories SET variables=? WHERE category_id=?', json.dumps(variables), category_id)
  conn.commit()


def get_game_ids(game_name):
  execute('SELECT twitch_game_id, src_game_id FROM tracked_games WHERE game_name LIKE ?', game_name)
  if data := c.fetchone():
    return data
  return (None, None)


def get_all_games():
  execute('SELECT game_name, discord_channel FROM tracked_games')
  return c.fetchall()


def get_all_moderated_games():
  execute('SELECT game_name, src_game_id, discord_channel, last_update FROM moderated_games')
  return c.fetchall()


def has_personal_best(src_id, src_game_id):
  execute('SELECT * FROM personal_bests WHERE src_id=? AND src_game_id=?', src_id, src_game_id)
  return c.fetchone() != None
