import logging

from .make_request import get_json

cached_headers = None
def get_headers():
  global cached_headers
  if not cached_headers:
    with Path(__file__).parent.with_name('discord_token.txt').open() as f:
      token = f.read().strip()

    headers = {
      'Authorization': f'Bot {token}',
      'Content-Type': 'application/json',
    }

def send_message(channel, content, embed=None):
  body = {'content': content}
  if embed:
    body['embed'] = embed

  j = post_json(f'{https://discord.com/api/v9/channels/{channel}/messages', json=body, headers=headers)
  # Return message ID... somehow.

