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


# https://github.com/Rapptz/discord.py/blob/master/discord/utils.py#L819
_MARKDOWN_ESCAPE_SUBREGEX = '|'.join(r'\{0}(?=([\s\S]*((?<!\{0})\{0})))'.format(c) for c in ('*', '`', '_', '~', '|'))
_MARKDOWN_ESCAPE_COMMON = r'^>(?:>>)?\s|\[.+\]\(.+\)'
_MARKDOWN_ESCAPE_REGEX = re.compile(fr'(?P<markdown>{_MARKDOWN_ESCAPE_SUBREGEX}|{_MARKDOWN_ESCAPE_COMMON})', re.MULTILINE)
_URL_REGEX = r'(?P<url><[^: >]+:\/[^ >]+>|(?:https?|steam):\/\/[^\s<]+[^<.,:;\"\'\]\s])'
_MARKDOWN_STOCK_REGEX = fr'(?P<markdown>[_\\~|\*`]|{_MARKDOWN_ESCAPE_COMMON})'

# https://github.com/Rapptz/discord.py/blob/master/discord/utils.py#L864
def escape_markdown(text, *, as_needed=False, ignore_links=True):
  if not as_needed:

    def replacement(match):
      groupdict = match.groupdict()
      is_url = groupdict.get('url')
      if is_url:
        return is_url
      return '\\' + groupdict['markdown']

    regex = _MARKDOWN_STOCK_REGEX
    if ignore_links:
      regex = f'(?:{_URL_REGEX}|{regex})'
    return re.sub(regex, replacement, text, 0, re.MULTILINE)
  else:
    text = re.sub(r'\\', r'\\\\', text)
    return _MARKDOWN_ESCAPE_REGEX.sub(r'\\\1', text)


# You should probably only use this for testing. Bots should not be in the habit of sending DMs.
def test_get_dm_channel(user):
  return make_request('POST', f'{api}/users/@me/channels', json={'recipient_id': user}, get_headers=get_headers)


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
  return make_request('PATCH', f'{api}/channels/{channel_id}/messages/{message_id}', json=json, get_headers=get_headers)


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


