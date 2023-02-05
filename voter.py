#! /usr/bin/env python3

# Discord app to collect suggestions and reaction votes for games to play.

# TODO: incorporate logging of the last assignment people accepted so that we can assign players together with
#       others they haven't played with lately.
# TODO: add an "I will play this but am not actively upvoting it" reaction

import asyncio
import collections
from dataclasses import dataclass
import itertools
import textwrap
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


MINIMUM_VOTES = 1
MINIMUM_PLAYERS_PER_GAME = 2


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
    suggestions_to_messages: Dict[str, discord.Message]
    messages_to_suggestions: Dict[discord.Message, str]

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
        self.suggestions_to_messages[suggestion] = msg
        self.messages_to_suggestions[msg] = suggestion
        # Add the upvote/downvote reactions
        await msg.add_reaction('👍')
        print(f'{voter} added suggestion "{suggestion}" to {source_channel}.')
        await interaction.response.send_message(f'Suggestion {suggestion} added.', ephemeral=True)

    async def handle_delete(self, interaction: discord.interactions.Interaction, suggestion: str):
        if suggestion not in self.suggestions_and_upvotes:
            await interaction.response.send_message(f'"{suggestion}" has not been suggested.', ephemeral=True)
            return
        message = self.suggestions_to_messages[suggestion]
        await message.delete()
        del self.suggestions_and_upvotes[suggestion]
        del self.messages_to_suggestions[message]
        del self.suggestions_to_messages[suggestion]
        await interaction.response.send_message(f'Suggestion {suggestion} deleted.', ephemeral=True)

    async def handle_reaction(self, reaction, user):
        # Ignore reactions from the bot
        if user == client.user:
            return

        # Ignore reactions on non-vote messages.
        if reaction.message not in self.messages_to_suggestions:
            print('Ignoring reaction on non-vote message')
            return

        # Get the suggestion text
        suggestion = self.messages_to_suggestions[reaction.message]

        # Check all reactions on the message
        upvoters = set()
        for reaction in reaction.message.reactions:
            if reaction.emoji == '👍':
                upvoters = {u async for u in reaction.users()}
        actual_upvoters = upvoters - {client.user}
        self.suggestions_and_upvotes[suggestion] = actual_upvoters

    async def check_and_report_consensus(self, interaction: discord.interactions.Interaction, ephemeral: bool):
        assignment = self.find_best_assignment()
        if assignment is None:
            await interaction.response.send_message(
                textwrap.dedent(
                    f"""
                    No suitable assignment found.
                    (At least {MINIMUM_VOTES} people need to cast votes, and I'm looking for at least {MINIMUM_PLAYERS_PER_GAME} players in each game.)
                    """),
                ephemeral=ephemeral)
            return
        lines = ["Here's the list of games to play:"]
        games_to_players = collections.defaultdict(set)
        for player, game in assignment.items():
            games_to_players[game].add(player)
        for game, players in sorted(games_to_players.items()):
            players = ', '.join(u.name for u in players)
            lines.append(f' - {game}: {players}')
        await interaction.response.send_message('\n'.join(lines), ephemeral=ephemeral)
        # Doing this at the end in case the send fails
        self.last_assignment_reported = assignment

    def possible_assignments(self) -> Iterable[Assignment]:
        # Find all possible assignments of players to games
        players_to_games = collections.defaultdict(set)
        for game in self.suggestions_and_upvotes:
            for player in self.suggestions_and_upvotes[game]:
                players_to_games[player].add(game)
        players_list = list(players_to_games.keys())
        for games_list in itertools.product(*[players_to_games[p] for p in players_list]):
            assignment = dict(zip(players_list, games_list))
            # Check that no game is too small.
            games_to_players = collections.defaultdict(set)
            for player, game in assignment.items():
                games_to_players[game].add(player)
            if any(len(players) > 0 and len(players) < MINIMUM_PLAYERS_PER_GAME for players in games_to_players.values()):
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


global_state_lock = asyncio.Lock()
pending_votes: Dict[discord.TextChannel, VoteState] = {}


async def get_vote_state(channel: discord.TextChannel):
    if channel not in pending_votes:
        print(
            f'Creating new vote state for {channel}')
        await channel.send(
            textwrap.dedent("""
            Starting a new vote!

            I'm a bot that tries to find a game that everyone wants to play. If I can't, I'll try to split the group into two smaller groups that can play different games.

            - React 👍 on what you're willing to play
            - `/suggest <game>` to add an option
            - `/tally` to see the current results
            - `/endvote` to end the vote
            """))
        pending_votes[channel] = VoteState(
            channel=channel,
            suggestions_and_upvotes={},
            last_assignment_reported=None,
            suggestions_to_messages={},
            messages_to_suggestions={},
        )
    return pending_votes[channel]


@tree.command(name='suggest')
async def suggest_command(interaction: discord.interactions.Interaction, suggestion: str):
    async with global_state_lock:
        vote_state = await get_vote_state(interaction.channel)
        await vote_state.handle_suggest(interaction, suggestion, interaction.user.name)


@tree.command(name='delete')
async def delete_command(interaction: discord.interactions.Interaction, suggestion: str):
    async with global_state_lock:
        if interaction.channel not in pending_votes:
            await interaction.response.send_message('No vote in progress.', ephemeral=True)
            return

        vote_state = pending_votes[interaction.channel]
        await vote_state.handle_delete(interaction, suggestion)


@tree.command(name='tally')
async def tally_command(interaction: discord.interactions.Interaction):
    async with global_state_lock:
        if interaction.channel not in pending_votes:
            await interaction.response.send_message('No vote in progress.', ephemeral=True)
            return

        vote_state = pending_votes[interaction.channel]
        await vote_state.check_and_report_consensus(interaction, ephemeral=True)


@tree.command(name='endvote')
async def endvote_command(interaction: discord.interactions.Interaction):
    async with global_state_lock:
        if interaction.channel not in pending_votes:
            await interaction.response.send_message('No vote in progress.', ephemeral=True)
            return

        vote_state = pending_votes[interaction.channel]
        del pending_votes[interaction.channel]
        await vote_state.check_and_report_consensus(interaction, ephemeral=False)
        await interaction.channel.send('Vote ended.')


@client.event
async def on_reaction_add(reaction: discord.Reaction, user: discord.User):
    async with global_state_lock:
        print(
            f'Got reaction {reaction.emoji} from {user} on {reaction.message.content}')
        if reaction.message.channel not in pending_votes:
            print('...ignored because no pending vote')
            return
        await pending_votes[reaction.message.channel].handle_reaction(reaction, user)


@client.event
async def on_reaction_remove(reaction, user):
    async with global_state_lock:
        print(
            f'Removed reaction {reaction.emoji} from {user} on {reaction.message.content}')
        if reaction.message.channel not in pending_votes:
            print('...ignored because no pending vote')
            return
        await pending_votes[reaction.message.channel].handle_reaction(reaction, user)


@client.event
async def on_ready():
    async with global_state_lock:
        print(f'We have logged in as {client.user}')
        print('Syncing command tree...')
        await tree.sync()
        print('Command tree synced')
        global status_channel
        # TODO: get_channel
        status_channel = await client.fetch_channel(status_channel_id)
        await status_channel.send('I\'m alive!')


async def main():
    global global_state_lock
    global_state_lock = asyncio.Lock()
    await client.start(TOKEN)

if __name__ == '__main__':
    asyncio.run(main())
