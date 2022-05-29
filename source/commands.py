import logging

from . import discord_apis

register_global_slash_command(
    'track_game', 'Announce speedrunners of a game when they go live',
    args={
      'channel': 'The channel to announce runners in',
      'game_name': 'The exact name of the game to announce',
    })

client.callbacks['track_game'] = track_game
def track_game(channel, game_name):
    generics.track_game(game_name, channel['id'])
    return f'Will now announce runners of {game_name} in channel <#{channel["id"]}>.'






"""
  admin_commands = {
    '!track_game': lambda: track_game(get_channel(), ' '.join(args[1:])),
    '!untrack_game': lambda: untrack_game(get_channel(), ' '.join(args[1:])),
    '!moderate_game': lambda: moderate_game(get_channel(), ' '.join(args[1:])),
    '!unmoderate_game': lambda: unmoderate_game(get_channel(), ' '.join(args[1:])),
    '!restart': lambda: restart(*args[1:2]),
    '!git_update': lambda: git_update(),
    '!send_last_lines': lambda: send_last_lines(),
  }
  commands = {
    '!announce_me': lambda: announce(get_channel(), *args[1:3]),
    '!about': lambda: about(),
    '!help': lambda: help(),
  }
"""
