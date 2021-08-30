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

# You should probably only use this for testing. Bots should not be in the habit of sending DMs.
def test_get_dm_channel(user):
  return make_request('POST', f'{api}/users/@me/channels', json={'recipient_id': user}, headers=get_headers())


def send_message(channel, content, embed=None):
  return send_message_ids(channel['id'], content, embed)


def send_message_ids(channel_id, content, embed=None):
  json = {'content': content}

  if embed:
    # See https://discordjs.guide/popular-topics/embeds.html#embed-preview
    json['embeds'] = [{
      'type': 'image',
      'color': embed.get('color', 0x6441A4),
      'title': embed.get('title'),
      'url': embed.get('title_link'),
      'image': {'url': embed.get('image')}
    }]
  return make_request('POST', f'{api}/channels/{channel_id}/messages', json=json, headers=get_headers())


def edit_message(message, content=None, embed=None):
  return edit_message_ids(message['channel_id'], message['id'], content=content, embed=embed)


def edit_message_ids(channel_id, message_id, content=None, embed=None):
  json = {}
  if content:
    json['content'] = content
  if embed:
    # See https://discordjs.guide/popular-topics/embeds.html#embed-preview
    json['embeds'] = [{
      'type': 'image',
      'color': embed.get('color', 0x6441A4),
      'title': embed.get('title'),
      'url': embed.get('title_link'),
      'image': {'url': embed.get('image')}
    }]
  return make_request('PATCH', f'{api}/channels/{channel_id}/messages/{message_id}', json=json, headers=get_headers())


def add_reaction(message, emoji):
  try:
    make_request('PUT', f'{api}/channels/{message["channel_id"]}/messages/{message["id"]}/reactions/{emoji}/@me', headers=get_headers())
  except ConnectionError: # Bot may or may not have permission to add reactions
    logging.exception('Error while attempting to add a reaction')
  return None


def remove_reaction(message, emoji):
  make_request('DELETE', f'{api}/channels/{message["channel_id"]}/messages/{message["id"]}/reactions/{emoji}/@me', headers=get_headers())
  return None
