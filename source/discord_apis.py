import logging
from pathlib import Path

from .make_request import make_request

api = 'https://discord.com/api/v9'

cached_headers = None
def get_headers():
  global cached_headers
  if not cached_headers:
    with Path(__file__).parent.with_name('discord_token.txt').open() as f:
      token = f.read().strip()

    cached_headers = {
      'Authorization': f'Bot {token}',
      'Content-Type': 'application/json',
      'User-Agent': 'SpeedrunBot (https://github.com/jbzdarkid/SpeedrunBot, 1.0)',
    }
  return cached_headers


def send_message(channel, content, embed=None):
  json = {'content': content}
  return make_request('POST', f'{api}/channels/{channel["id"]}/messages', json=json, headers=get_headers())


def edit_message(message, content, embed=None):
  json = {'content': content}
  return make_request('PATCH', f'{api}/channels/{message["channel_id"]}/messages/{message["id"]}', json=json, headers=get_headers())


def add_reaction(message, emoji):
  make_request('PUT', f'{api}/channels/{message["channel_id"]}/messages/{message["id"]}/reactions/{emoji}/@me', headers=get_headers())
  return None


def remove_reaction(message, emoji):
  make_request('DELETE', f'{api}/channels/{message["channel_id"]}/messages/{message["id"]}/reactions/{emoji}/@me', headers=get_headers())
  return None
