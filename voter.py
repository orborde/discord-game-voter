#! /usr/bin/env python3

# Discord app to collect suggestions and reaction votes for games to play.

# TODO: incorporate logging of the last assignment people accepted so that we can assign players together with
#       others they haven't played with lately.

import collections
import itertools
import discord
import asyncio
from typing import *

TOKEN = open('token.txt').read().strip()

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

    # Check all reactions on the message
    upvoters = set()
    downvoters = set()
    for reaction in reaction.message.reactions:
        if reaction.emoji == '👍':
            upvoters = await reaction.users().flatten()
        elif reaction.emoji == '👎':
            downvoters = await reaction.users().flatten()
    actual_upvoters = upvoters - downvoters - {client.user}
    suggestions_and_upvotes[suggestion] = actual_upvoters

    await check_and_report_consensus(client)


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

    # Check whether there's a non-overlapping covering set of voter-sets for progressively larger candidate covering set sizes.
    # (Divide by two because the smallest usable voter-set is size 2)
    for num_partitions in range(1, len(all_voters)/2 + 1):
        for candidate_games in itertools.combinations(suggestions_and_upvotes.keys(), num_partitions):
            candidate_voters = collections.Counter()
            for game in candidate_games:
                for voter in suggestions_and_upvotes[game]:
                    candidate_voters[voter] += 1

            if any(votes > 1 for votes in candidate_voters.values()):
                # Can't have overlap between sets (which would mean that some players are assigned to multiple games)
                continue

            if set(candidate_voters.keys()) == all_voters:
                # Found a consensus!
                return candidate_games
    return None


if __name__ == '__main__':
    client.run(TOKEN)
