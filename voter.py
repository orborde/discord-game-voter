#! /usr/bin/env python3

# Discord app to collect suggestions and reaction votes for games to play.

# TODO: incorporate logging of the last assignment people accepted so that we can assign players together with
#       others they haven't played with lately.

import collections
import itertools
import discord
from typing import *

TOKEN = open('token.txt').read().strip()

# Create the client
# TODO: restrict to only the intents we need
intents = discord.Intents(
    messages=True, message_content=True, reactions=True)
client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)

# The channel to send the message to
channel_id = 1061770027860230265
# TODO: figure out why get_channel doesn't work
channel: Optional[discord.TextChannel] = None

suggestions_and_upvotes: Dict[str, Set[str]] = {}


@tree.command(name='suggest')
async def suggest_command(interaction: discord.interactions.Interaction, suggestion: str):
    print(f'{type(interaction)}')
    source_channel = interaction.channel
    if suggestion in suggestions_and_upvotes:
        await interaction.response.send_message(f'"{suggestion}" has already been suggested. Go vote on it?', ephemeral=True)
        return

    # Add the suggestion to the list
    suggestions_and_upvotes[suggestion] = set()

    # Send the message to the channel
    # channel = client.get_channel(channel_id)
    msg = await source_channel.send(f'Suggestion: {suggestion}')
    # Add the upvote/downvote reactions
    await msg.add_reaction('👍')
    await msg.add_reaction('👎')
    await interaction.response.send_message(f'Suggestion {suggestion} added.', ephemeral=True)


@client.event
async def on_reaction_add(reaction, user):
    print(
        f'Got reaction {reaction.emoji} from {user} on {reaction.message.content}')
    await handle_reaction(reaction, user)


@client.event
async def on_reaction_remove(reaction, user):
    print(
        f'Removed reaction {reaction.emoji} from {user} on {reaction.message.content}')
    await handle_reaction(reaction, user)


async def handle_reaction(reaction, user):
    print(
        f'Reaction {reaction.emoji} from {user} on {reaction.message}')

    # Ignore reactions from the bot
    if user == client.user:
        return

    # Ignore reactions on messages that aren't from the bot
    if reaction.message.author != client.user:
        return

    # Get the suggestion text
    suggestion = reaction.message.content[12:]

    # Check all reactions on the message
    upvoters = set()
    downvoters = set()
    for reaction in reaction.message.reactions:
        if reaction.emoji == '👍':
            upvoters = {u async for u in reaction.users()}
        elif reaction.emoji == '👎':
            downvoters = {u async for u in reaction.users()}
    actual_upvoters = upvoters - downvoters - {client.user}
    suggestions_and_upvotes[suggestion] = actual_upvoters

    await check_and_report_consensus(client)


@client.event
async def on_ready():
    print(f'We have logged in as {client.user}')
    print('Syncing command tree...')
    await tree.sync()
    print('Command tree synced')
    global channel
    # channel = client.get_channel(channel_id)
    channel = await client.fetch_channel(channel_id)
    await channel.send('I\'m alive!')


async def check_and_report_consensus(client):
    games = find_consensus()
    if games is None:
        return
    lines = ["Consensus reached! Here's the list of games to play:"]
    for game in games:
        players = ', '.join(u.name for u in suggestions_and_upvotes[game])
        lines.append(f' - {game}: {players}')
    await channel.send('\n'.join(lines))


def find_consensus():
    all_voters = set()
    for voters in suggestions_and_upvotes.values():
        all_voters.update(voters)

    # Check whether there's a non-overlapping covering set of voter-sets for progressively larger candidate covering set sizes.
    # (Divide by two because the smallest usable voter-set is size 2)
    for num_partitions in range(1, len(all_voters)//2 + 1):
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
