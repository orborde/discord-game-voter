#! /usr/bin/env python3

# Discord app to collect suggestions and reaction votes for games to play.

# TODO: incorporate logging of the last assignment people accepted so that we can assign players together with
#       others they haven't played with lately.

import collections
from dataclasses import dataclass
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

status_channel_id = 1061770027860230265
# TODO: figure out why get_channel doesn't work
status_channel: Optional[discord.TextChannel] = None


MINIMUM_VOTES = 4


GameName = str
PlayerName = str
Assignment = Dict[PlayerName, GameName]


def number_of_games(assignment: Assignment) -> int:
    games = set(assignment.values())
    return len(games)


def imbalance(assignment: Assignment) -> int:
    games_to_players = collections.defaultdict(set)
    for player, game in assignment.items():
        games_to_players[game].add(player)
    return max(len(players) for players in games_to_players.values()) - min(len(players) for players in games_to_players.values())


def assignment_better(a: Assignment, b: Assignment) -> bool:
    if number_of_games(a) == number_of_games(b):
        return imbalance(a) < imbalance(b)
    return number_of_games(a) < number_of_games(b)


@dataclass
class VoteState:
    channel: discord.TextChannel
    suggestions_and_upvotes: Dict[str, Set[str]]
    # TODO: clean up old consensus messages somehow
    last_assignment_reported: Optional[Assignment]
    suggestion_messages: Set[discord.Message]

    async def handle_suggest(self, interaction: discord.interactions.Interaction, suggestion: str, voter: str):
        source_channel = interaction.channel

        if suggestion in self.suggestions_and_upvotes:
            await interaction.response.send_message(f'"{suggestion}" has already been suggested. Go vote on it?', ephemeral=True)
            return

        # Add the suggestion to the list
        self.suggestions_and_upvotes[suggestion] = set()

        # Send the message to the channel
        # channel = client.get_channel(channel_id)
        msg = await source_channel.send(f'Suggestion: {suggestion}')
        self.suggestion_messages.add(msg)
        # Add the upvote/downvote reactions
        await msg.add_reaction('👍')
        await msg.add_reaction('👎')
        await interaction.response.send_message(f'Suggestion {suggestion} added.', ephemeral=True)

    async def handle_reaction(self, reaction, user):
        print(
            f'Reaction {reaction.emoji} from {user} on {reaction.message}')

        # Ignore reactions from the bot
        if user == client.user:
            return

        # Ignore reactions on non-vote messages.
        if reaction.message not in self.suggestion_messages:
            print('Ignoring reaction on non-vote message')
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
        self.suggestions_and_upvotes[suggestion] = actual_upvoters

        await self.check_and_report_consensus()

    async def check_and_report_consensus(self):
        assignment = self.find_best_assignment()
        if assignment is None:
            return
        if self.last_assignment_reported is not None and assignment == self.last_assignment_reported:
            return
        lines = ["Consensus reached! Here's the list of games to play:"]
        games_to_players = collections.defaultdict(set)
        for player, game in assignment.items():
            games_to_players[game].add(player)
        for game, players in sorted(games_to_players.items()):
            players = ', '.join(u.name for u in players)
            lines.append(f' - {game}: {players}')
        await self.channel.send('\n'.join(lines))
        # Doing this at the end in case the send fails
        self.last_assignment_reported = assignment

    def possible_assignments(self) -> Iterable[Assignment]:
        # Find all possible assignments of players to games
        players_to_games = collections.defaultdict(set)
        for game in self.suggestions_and_upvotes:
            for player in self.suggestions_and_upvotes[game]:
                players_to_games[player].add(game)
        players_list = list(self.suggestions_and_upvotes.keys())
        for games_list in itertools.product(*[players_to_games[p] for p in players_list]):
            assignment = dict(zip(players_list, games_list))
            # Check that no player is alone.
            games_to_players = collections.defaultdict(set)
            for player, game in assignment.items():
                games_to_players[game].add(player)
            if any(len(players) == 1 for players in games_to_players.values()):
                continue
            yield assignment

    def find_best_assignment(self) -> Optional[Assignment]:
        if len(set.union(*self.suggestions_and_upvotes.values())) < MINIMUM_VOTES:
            return None

        # Find the best assignment of players to games
        best_assignment = None
        for assignment in self.possible_assignments():
            if best_assignment is None:
                best_assignment = assignment
            elif assignment_better(assignment, best_assignment):
                best_assignment = assignment
        return best_assignment


pending_votes: Dict[discord.TextChannel, VoteState] = {}


async def get_vote_state(channel: discord.TextChannel):
    if channel not in pending_votes:
        print(
            f'Creating new vote state for {channel}')
        await channel.send('Starting a new vote!')
        pending_votes[channel] = VoteState(
            channel=channel,
            suggestions_and_upvotes={},
            last_assignment_reported=None,
            suggestion_messages=set(),
        )
    return pending_votes[channel]


@tree.command(name='suggest')
async def suggest_command(interaction: discord.interactions.Interaction, suggestion: str):
    vote_state = await get_vote_state(interaction.channel)
    await vote_state.handle_suggest(interaction, suggestion, interaction.user.name)


@tree.command(name='end')
async def end_command(interaction: discord.interactions.Interaction):
    if interaction.channel not in pending_votes:
        await interaction.response.send_message('No pending votes.', ephemeral=True)
        return

    del pending_votes[interaction.channel]
    await interaction.response.send_message('Vote ended.')


@client.event
async def on_reaction_add(reaction: discord.Reaction, user: discord.User):
    print(
        f'Got reaction {reaction.emoji} from {user} on {reaction.message.content}')
    if reaction.message.channel not in pending_votes:
        print('...ignored because no pending vote')
        return
    await pending_votes[reaction.message.channel].handle_reaction(reaction, user)


@client.event
async def on_reaction_remove(reaction, user):
    print(
        f'Removed reaction {reaction.emoji} from {user} on {reaction.message.content}')
    if reaction.message.channel not in pending_votes:
        print('...ignored because no pending vote')
        return
    await pending_votes[reaction.message.channel].handle_reaction(reaction, user)


@client.event
async def on_ready():
    print(f'We have logged in as {client.user}')
    print('Syncing command tree...')
    await tree.sync()
    print('Command tree synced')
    global status_channel
    # TODO: get_channel
    status_channel = await client.fetch_channel(status_channel_id)
    await status_channel.send('I\'m alive!')


if __name__ == '__main__':
    client.run(TOKEN)
