import logging
import sqlite3
from pathlib import Path
from threading import Lock

from . import exceptions
from .utils import seconds_since_epoch

conn = sqlite3.connect(
  database = Path(__file__).with_name('database.db'),
  isolation_level = None, # Automatically commit after making a statement
  check_same_thread = False,
)
lock = Lock()
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
c.execute('''CREATE TABLE IF NOT EXISTS src_game_series (
  src_game_id      TEXT    NOT NULL    PRIMARY KEY,
  src_series_id    TEXT    NOT NULL,
  last_fetched     REAL
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
c.execute('''CREATE TABLE IF NOT EXISTS announced_streams (
  name             TEXT    NOT NULL,
  game             TEXT    NOT NULL,
  title            TEXT    NOT NULL,
  url              TEXT    NOT NULL,
  preview          TEXT    NOT NULL,
  channel_id       INTEGER NOT NULL,
  message_id       INTEGER NOT NULL,
  start            REAL    NOT NULL,
  preview_expires  REAL    NOT NULL,
  PRIMARY KEY (name, game)
)''')
c.execute('''CREATE TABLE IF NOT EXISTS unverified_runs (
  run_id           TEXT    NOT NULL     PRIMARY KEY,
  src_game_id      TEXT    NOT NULL,
  submitted        REAL    NOT NULL,
  channel_id       INTEGER NOT NULL,
  message_id       INTEGER NOT NULL
)''')


# Simple helper to pack *args (because SQL wants it like that)
def execute(sql, *args):
  with lock:
    return c.execute(sql, args)


def fetchone():
  with lock:
    return c.fetchone()


def fetchall():
  with lock:
    return c.fetchall()


# Commands related to users
def add_user(twitch_username, src_id, fetch_time=None):
  if fetch_time is None:
    fetch_time = seconds_since_epoch()
  execute('INSERT OR REPLACE INTO users VALUES (?, ?, ?)', twitch_username.lower(), src_id, fetch_time)


def get_user(twitch_username):
  execute('SELECT * FROM users WHERE twitch_username=?', twitch_username.lower())
  if data := fetchone():
    return {
      'twitch_username': data[0],
      'src_id': data[1],
      'fetch_time': data[2],
    }
  return None


def remove_user(twitch_username):
  src_id = get_user(twitch_username)['src_id']
  execute('DELETE FROM personal_bests WHERE src_id=?', src_id)
  execute('DELETE FROM users WHERE twitch_username=?', twitch_username)


def update_user_fetch_time(twitch_username, last_fetched=None):
  if not last_fetched:
    last_fetched = seconds_since_epoch()
  execute('UPDATE users SET last_fetched=? WHERE twitch_username=?', last_fetched, twitch_username.lower())
  conn.commit()


# Commands related to tracked_games
def add_game(game_name, twitch_game_id, src_game_id, discord_channel):
  try:
    execute('INSERT INTO tracked_games VALUES (?, ?, ?, ?)', game_name, twitch_game_id, src_game_id, int(discord_channel))
  except sqlite3.IntegrityError:
    logging.exception('SQL error')
    raise exceptions.CommandError(f'Game `{game_name}` is already being tracked.')


def get_all_games():
  execute('SELECT game_name, twitch_game_id, src_game_id FROM tracked_games')
  return fetchall()


def get_channel_for_game(twitch_game_id):
  execute('SELECT discord_channel FROM tracked_games WHERE twitch_game_id=?', twitch_game_id)
  if data := fetchone():
    return data[0]
  return None


def get_games_for_channel(channel_id):
  execute('SELECT game_name, src_game_id, twitch_game_id FROM tracked_games WHERE discord_channel=?', channel_id)
  return [{
    'game_name': d[0],
    'src_game_id': d[1],
    'twitch_game_id': d[2],
  } for d in fetchall()]


def remove_game(game_name):
  execute('SELECT src_game_id FROM tracked_games WHERE game_name=?', game_name)
  src_game_id = fetchone()
  if src_game_id is None:
    raise exceptions.CommandError(f'Cannot remove `{game_name}` as it is not currently being tracked.')

  # Note: There is no need to delete users here -- users are cross-game.
  execute('DELETE FROM personal_bests WHERE src_game_id=?', src_game_id[0])
  execute('DELETE FROM tracked_games WHERE src_game_id=?', src_game_id[0])


# Commands related to src_game_series
def set_game_series(src_game_id, series_id):
  fetch_time = seconds_since_epoch()
  execute('INSERT OR REPLACE INTO src_game_series VALUES (?, ?, ?)', src_game_id, series_id, fetch_time)


def get_game_series(src_game_id):
  execute('SELECT src_series_id, last_fetched FROM src_game_series WHERE src_game_id=?', src_game_id)
  if data := fetchone():
    return data
  return None, None


def get_games_in_series(src_series_id):
  execute('SELECT src_game_id FROM src_game_series WHERE src_series_id=?', src_series_id)
  return [d[0] for d in fetchall()]


# Commands related to personal_bests
def add_personal_best(src_id, src_game_id):
  try:
    execute('INSERT INTO personal_bests VALUES (?, ?)', src_id, src_game_id)
  except sqlite3.IntegrityError:
    logging.exception('SQL error')
    logging.info(f'Speedrun.com user `{src_id}` already had a PB in game ID `{src_game_id}`.')
    # But this isn't actually a problem, so we return without throwing an exception


def has_personal_best(src_id, src_game_id):
  execute('SELECT * FROM personal_bests WHERE src_id=? AND src_game_id=?', src_id, src_game_id)
  return fetchone() != None


# Commands related to moderated_games
def moderate_game(game_name, src_game_id, discord_channel):
  try:
    execute('INSERT INTO moderated_games VALUES (?, ?, ?, 0)', game_name, src_game_id, int(discord_channel))
  except sqlite3.IntegrityError:
    logging.exception('SQL error')
    raise exceptions.CommandError(f'Game `{game_name}` is already being moderated.')


def get_all_moderated_games():
  execute('SELECT game_name, src_game_id, discord_channel FROM moderated_games')
  return fetchall()


def unmoderate_game(game_name):
  execute('SELECT src_game_id FROM moderated_games WHERE game_name=?', game_name)
  src_game_id = fetchone()[0]
  print(src_game_id)
  execute('DELETE FROM unverified_runs WHERE src_game_id=?', src_game_id)
  execute('DELETE FROM moderated_games WHERE src_game_id=?', src_game_id)


# Commands related to announced_streams
def add_announced_stream(**announced_stream):
  announced_stream['start'] = seconds_since_epoch()

  execute('INSERT INTO announced_streams VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
    announced_stream['name'],
    announced_stream['game'],
    announced_stream['title'],
    announced_stream['url'],
    announced_stream['preview'],
    announced_stream['channel_id'],
    announced_stream['message_id'],
    announced_stream['start'],
    announced_stream['preview_expires'],
  )


def update_announced_stream(announced_stream):
  execute('''
      UPDATE announced_streams
      SET title=?, preview_expires=?
      WHERE name=? AND game=?''',
    announced_stream['title'],
    announced_stream['preview_expires'],
    announced_stream['name'],
    announced_stream['game'],
  )


def get_announced_streams():
  execute('SELECT * FROM announced_streams')
  for data in fetchall():
    yield {
      'name': data[0],
      'game': data[1],
      'title': data[2],
      'url': data[3],
      'preview': data[4],
      'channel_id': data[5],
      'message_id': data[6],
      'start': data[7],
      'preview_expires': data[8],
    }


def get_announced_stream(name, game):
  execute('SELECT * FROM announced_streams WHERE name=? AND game=?', name, game)
  if data := fetchone():
    return {
      'name': data[0],
      'game': data[1],
      'title': data[2],
      'url': data[3],
      'preview': data[4],
      'channel_id': data[5],
      'message_id': data[6],
      'start': data[7],
      'preview_expires': data[8],
    }
  return None


def delete_announced_stream(announced_stream):
  execute('DELETE FROM announced_streams WHERE name=? AND game=?', announced_stream['name'], announced_stream['game'])


# Commands related to unverified_runs
def get_unverified_runs(src_game_id):
  execute('SELECT * FROM unverified_runs WHERE src_game_id=?', src_game_id)
  return {d[0]: {
    'run_id': d[0],
    'src_game_id': d[1],
    'submitted': d[2],
    'channel_id': d[3],
    'message_id': d[4],
  } for d in fetchall()}


def add_unverified_run(**unverified_run):
  execute('INSERT INTO unverified_runs VALUES (?, ?, ?, ?, ?)',
    unverified_run['run_id'],
    unverified_run['src_game_id'],
    unverified_run['submitted'],
    unverified_run['channel_id'],
    unverified_run['message_id'],
  )


def delete_unverified_run(run_id):
  execute('DELETE FROM unverified_runs WHERE run_id=?', run_id)

