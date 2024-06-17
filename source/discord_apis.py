import logging
import re
from pathlib import Path

from .make_request import make_request
from . import exceptions

api = 'https://discord.com/api/v10'

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


# Adapted (and simplified) from escape_markdown in https://github.com/Rapptz/discord.py/blob/master/discord/utils.py
FIND = re.compile(r'''
(                   # Open capture group
  <                   # Start of an explicit link
  [^: >]+:            # Scheme
  /                   # (start of path)
  [^ >]+              # At least one non-space character (and not the end of the explicit scheme)
  >                   # End of explicit link
|                   # -OR-
  (http|https|steam): # Implicit links (discord only recognizes these schemes)
  //                  # (start of path)
  [^\s<]+             # At least one non-space and non-explicit url characters
  [^<.,:;"'\]\)\s]    # The final character (which is not a separator), e.g. if you write (http://google.com), discord will not include the )
|                   # -OR-
  [_*`>\\]            # Any of the characters that actually need escaping
)                   # Close capture group
''', re.VERBOSE)
def REPL(match):
  matched_text = match[0]
  if len(matched_text) == 1: # A character which needs escaping
    return '\\' + matched_text
  else: # Anything else (URL) which doesn't need escaping
    return matched_text

def escape_markdown(orig_text):
  text = FIND.sub(REPL, orig_text)
  if text != orig_text:
    logging.info(f'Escaped markdown "{orig_text.encode("utf-8")}" to "{text.encode("utf-8")}"')
  return text


def send_message(channel, content, embed=None):
  return send_message_ids(channel['id'], content, embed)


def send_message_ids(channel_id, content, embed=None):
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

  # https://discord.com/developers/docs/topics/opcodes-and-status-codes
  code = j.get('code', 0)
  if code == 10008: # Unknown Message
    logging.error(f'Message {message_id} in {channel_id} was deleted')
    return False
  elif code == 30046: # Edit old message throttled
    logging.error(f'Message {message_id} in {channel_id} was >1h and so temporarily could not be edited.')
    return False

  raise exceptions.NetworkError(f'Failed to edit message {message_id} in {channel_id}: {j}')


def add_reaction(message, emoji):
  add_reaction_ids(message['channel_id'], message['id'], emoji)


def add_reaction_ids(channel_id, message_id, emoji):
  try:
    make_request('PUT', f'{api}/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/@me', get_headers=get_headers)
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


def get_servers():
  j = make_request('GET', f'{api}/users/@me/guilds', get_headers=get_headers)
  return j


def register_all_commands(commands):
  j = make_request('GET', f'{api}/oauth2/applications/@me', get_headers=get_headers)
  url = f'{api}/applications/{j["id"]}/commands'

  # Ensure that all the commands are up to date by comparing the version from commands.py against the server's copy.
  # - This helps to avoid the global rate limit of 200 creates/day
  # - This helps to avoid command downtime when the bot restarts (commands take ~5 minutes to update clientside)
  # - This helps to avoid stale commands lingering forever

  existing = make_request('GET', url, get_headers=get_headers)
  for old in existing:
    name = old['name']
    new = commands.get(name, None)
    if not new:
      logging.info(f'Command "{name}" does not exist any more, deleting')
      make_request('DELETE', url + '/' + old['id'], get_headers=get_headers)
      continue

    for k, v in new.items():
      if old[k] != v:
        logging.info(f'Command "{name}" is out of date; key "{k}" has been updated from "{old[k]}" to "{v}", updating')
        make_request('POST', url, json=new, get_headers=get_headers)
        break
    else:
      logging.info(f'Command "{name}" is up to date')

    del commands[name] # Delete so that we know it's handled

  for new in commands:
    logging.info(f'Command "{name}" does not exist, creating')
    make_request('POST', url, json=new, get_headers=get_headers)


def acknowledge_interaction(interaction_id, token):
  json = {'type': 5} # DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE
  j = make_request('POST', f'{api}/interactions/{interaction_id}/{token}/callback', allow_4xx=True, json=json, get_headers=get_headers)
  if not j:
    return

  # https://discord.com/developers/docs/topics/opcodes-and-status-codes#json-json-error-codes
  code = j.get('code', 0)
  if code == 40060: # Interaction has already been acknowledged.
    logging.error(f'Interaction {interaction_id} was double-acknowledged')
    return

  raise exceptions.NetworkError(f'Failed to acknowledge interaction {interaction_id}: {j}')

def reply_to_interaction(interaction_id, token, message):
  json = {
    'type': 4, # CHANNEL_MESSAGE_WITH_SOURCE
    'data': {
      'content': message,
    }
  }

  return make_request('POST', f'{api}/interactions/{interaction_id}/{token}/callback', json=json, get_headers=get_headers)
