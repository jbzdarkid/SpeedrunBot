import logging
import re
from pathlib import Path

from .make_request import make_request
from . import exceptions

api = 'https://discord.com/api/v9'

cached_headers = None
def get_headers():
  global cached_headers
  if not cached_headers:
    with Path(__file__).with_name('discord_token.txt').open() as f:
      token = f.read().strip()

    cached_headers = {
      'Authorization': f'Bot {token}',
      'Content-Type': 'application/json',
      'User-Agent': 'SpeedrunBot (https://github.com/jbzdarkid/SpeedrunBot, 1.0)',
    }
  return cached_headers


def escape_markdown(text):
  orig_text = text
  special_characters = '_*`>\\'
  for ch in special_characters:
    if ch in text:
      text = text.replace(ch, '\\' + ch)
  if text != orig_text:
    logging.info(f'Before: "{text}" After: "{orig_text}"')
  return text


def send_message(channel, content, embed=None):
  return send_message_ids(channel['id'], content, embed)


"""
Embed structure. See https://discordjs.guide/popular-topics/embeds.html#embed-preview
{
  'type': str('image'),
  'color': int, # Hexadecimal, e.g. 0xFFFFFF
  'title': str,
  'url': str, # Link when clicking on the title
  'image': {'url': str} # Direct url which holds the embed image
}
"""
def send_message_ids(channel_id, content, embed=None):
  json = {'content': content}
  if embed:
    json['embeds'] = [embed]
  return make_request('POST', f'{api}/channels/{channel_id}/messages', json=json, get_headers=get_headers)


def edit_message(message, content=None, embed=None):
  return edit_message_ids(message['channel_id'], message['id'], content=content, embed=embed)


def edit_message_ids(channel_id, message_id, content=None, embed=None):
  json = {}
  if content:
    json['content'] = content
  if embed == []: # Signal value to remove embed
    json['embeds'] = []
  elif embed:
    json['embeds'] = [embed]

  j = make_request('PATCH', f'{api}/channels/{channel_id}/messages/{message_id}', allow_4xx=True, json=json, get_headers=get_headers)
  if j.get('id', None) == str(message_id):
    return True # Successful update returns the new message object

  # {'message': 'Unknown Message', 'code': 10008}
  if j.get('code', None) == 10008: # Unknown Message
    logging.error(f'Message {message_id} in {channel_id} was deleted')
    return False

  raise exceptions.NetworkError(f'Failed to edit message {message_id} in {channel_id}: {j}')


def add_reaction(message, emoji):
  try:
    make_request('PUT', f'{api}/channels/{message["channel_id"]}/messages/{message["id"]}/reactions/{emoji}/@me', get_headers=get_headers)
  except exceptions.NetworkError: # Bot may or may not have permission to add reactions
    logging.exception('Error while attempting to add a reaction')


def remove_reaction(message, emoji):
  try:
    make_request('DELETE', f'{api}/channels/{message["channel_id"]}/messages/{message["id"]}/reactions/{emoji}/@me', get_headers=get_headers)
  except exceptions.NetworkError: # Bot may or may not have permission to add reactions
    logging.exception('Error while attempting to add a reaction')


def get_owner():
  j = make_request('GET', f'{api}/oauth2/applications/@me', get_headers=get_headers)
  return j['owner']


def register_slash_command(name, desc, args=None, *, guild=None):
  options = []
  if args:
    for arg_name, arg_desc in args.items():
      option_type = {'channel': 7}.get(arg_name, 3)

      options.append({
        'name': arg_name,
        'description': arg_desc,
        'type': option_type,
        'required': True,
      })

  body = {
    'type': 1, # CHAT_INPUT
    'name': name,
    'description': desc,
    'options': options
  }

  if not guild:
    url = f'{api}/{app_id}/commands'
  else:
    url += f'{api}/{app_id}/guilds/{guild}/commands'

  make_request('POST', url, json=body, get_headers=get_headers)


