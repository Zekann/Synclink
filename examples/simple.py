"""
MIT License
Copyright (c) 2019-Present PythonistaGuild
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
import nextcord
import synclink
from nextcord.ext import commands


class Bot(commands.Bot):

    def __init__(self) -> None:
        intents = nextcord.Intents.default()
        intents.message_content = True

        super().__init__(intents=intents, command_prefix='?')

    async def on_ready(self) -> None:
        print(f'Logged in {self.user} | {self.user.id}')

    async def setup_hook(self) -> None:
        # synclink 2.0 has made connecting Nodes easier... Simply create each Node
        # and pass it to NodePool.connect with the client/bot.
        node: synclink.Node = synclink.Node(uri='http://localhost:2333', password='youshallnotpass')
        await synclink.NodePool.connect(client=self, nodes=[node])


bot = Bot()


@bot.command()
async def play(ctx: commands.Context, *, search: str) -> None:
    """Simple play command."""

    if not ctx.voice_client:
        vc: synclink.Player = await ctx.author.voice.channel.connect(cls=synclink.Player)
    else:
        vc: synclink.Player = ctx.voice_client

    track = await synclink.YouTubeTrack.search(search, return_first=True)
    await vc.play(track)


@bot.command()
async def disconnect(ctx: commands.Context) -> None:
    """Simple disconnect command.
    This command assumes there is a currently connected Player.
    """
    vc: synclink.Player = ctx.voice_client
    await vc.disconnect()