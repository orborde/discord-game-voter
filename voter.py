#! /usr/bin/env python3

# Discord app to collect suggestions and reaction votes for games to play.

# TODO: incorporate logging of the last assignment people accepted so that we can assign players together with
#       others they haven't played with lately.

import itertools
import discord
import asyncio
import os
from typing import *

# Get the bot token from the environment
TOKEN = os.environ['DISCORD_TOKEN']

# Create the client
client = discord.Client()

# The channel to send the message to
channel_id = 123456789012345678

suggestions_and_upvotes: Dict[str, Set[str]] = {}


@client.event
async def on_message(message):
    # Respond to the /suggest command
    if message.content.startswith('/suggest'):
        # Get the suggestion text
        suggestion = message.content[9:]
        # Add the suggestion to the list
        if suggestion in suggestions_and_upvotes:
            # Duplicate suggestion. Print a message and return.
            await message.channel.send(f'Duplicate suggestion {suggestion}. Please try again.')
            return

        # Add the suggestion to the list
        suggestions_and_upvotes[suggestion] = set()

        # Send the message to the channel
        channel = client.get_channel(channel_id)
        msg = await channel.send(f'Suggestion: {suggestion}')
        # Add the upvote/downvote reactions
        await msg.add_reaction('👍')
        await msg.add_reaction('👎')


@client.event
async def on_reaction_add(reaction, user):
    # Ignore reactions from the bot
    if user == client.user:
        return

    # Get the suggestion text
    suggestion = reaction.message.content[12:]
    # Add the user to the list of upvotes if positive
    # TODO: handle the case where the user has already voted
    if reaction.emoji == '👍':
        suggestions_and_upvotes[suggestion].add(user.name)
    if reaction.emoji == '👎':
        suggestions_and_upvotes[suggestion].discard(user.name)

# Process reaction deletions


@client.event
async def on_reaction_remove(reaction, user):
    assert user != client.user
    suggestion = reaction.message.content[12:]
    if reaction.emoji == '👍':
        suggestions_and_upvotes[suggestion].discard(user.name)


async def check_and_report_consensus(client):
    games = find_consensus()
    if games is None:
        return
    channel = client.get_channel(channel_id)
    await channel.send("Consensus reached! Here's the list of games to play:")
    for game in games:
        await channel.send(f' - {game}: {suggestions_and_upvotes[game]}')


def find_consensus():
    all_voters = set()
    for voters in suggestions_and_upvotes.values():
        all_voters.update(voters)

    # Check whether there's a covering set of voter-sets for progressively larger candidate covering set sizes.
    # (Divide by two because the smallest usable voter-set is size 2)
    for num_partitions in range(1, len(all_voters)/2 + 1):
        for candidate_games in itertools.combinations(suggestions_and_upvotes.keys(), num_partitions):
            candidate_voters = set()
            for game in candidate_games:
                candidate_voters.update(suggestions_and_upvotes[game])
            if candidate_voters == all_voters:
                # We have a consensus!
                return candidate_games
