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
from __future__ import annotations

import logging
import random
import re
import string
from typing import TYPE_CHECKING, Any, TypeVar

import aiohttp
import nextcord
from nextcord.enums import try_enum
from nextcord.utils import MISSING, classproperty
import urllib.parse

from .enums import LoadType, NodeStatus
from .exceptions import *
from .websocket import Websocket

if TYPE_CHECKING:
    from .player import Player
    from .tracks import *
    from .types.request import Request
    from .ext import spotify as spotify_

    PlayableT = TypeVar('PlayableT', bound=Playable)


__all__ = ('Node', 'NodePool')


logger: logging.Logger = logging.getLogger(__name__)


# noinspection PyShadowingBuiltins
class Node:
    """The base Synclink Node.
    The Node is responsible for keeping the Websocket alive, tracking the state of Players
    and fetching/decoding Tracks and Playlists.
    .. note::
        The Node class should only be created once per Lavalink connection.
        To retrieve a Node use the appropriate :class:`NodePool` methods instead.
    .. warning::
        The Node will not be connected until passed to :meth:`NodePool.connect`.
    Parameters
    ----------
    id: Optional[str]
        The unique identifier for this Node. If not passed, one will be generated randomly.
    uri: str
        The uri to connect to your Lavalink server. E.g ``http://localhost:2333``.
    password: str
        The password used to connect to your Lavalink server.
    secure: Optional[bool]
        Whether the connection should use https/wss.
    use_http: Optional[bool]
        Whether to use http:// over ws:// when connecting to the Lavalink websocket. Defaults to False.
    session: Optional[aiohttp.ClientSession]
        The session to use for this Node. If no session is passed a default will be used.
    heartbeat: float
        The time in seconds to send a heartbeat ack. Defaults to 15.0.
    retries: Optional[int]
        The amount of times this Node will try to reconnect after a disconnect.
        If not set the Node will try unlimited times.
    Attributes
    ----------
    heartbeat: float
        The time in seconds to send a heartbeat ack. Defaults to 15.0.
    client: :class:`nextcord.Client`
        The nextcord client used to connect this Node. Could be None if this Node has not been connected.
    """

    def __init__(
            self,
            *,
            id: str | None = None,
            uri: str,
            password: str,
            secure: bool = False,
            use_http: bool = False,
            session: aiohttp.ClientSession = MISSING,
            heartbeat: float = 15.0,
            retries: int | None = None,
    ) -> None:
        if id is None:
            id = ''.join(random.sample(string.ascii_letters + string.digits, 12))

        self._id: str = id
        self._uri: str = uri
        self._secure: bool = secure
        self._use_http: bool = use_http
        host: str = re.sub(r'(?:http|ws)s?://', '', self._uri)
        self._host: str = f'{"https://" if secure else "http://"}{host}'
        self._password: str = password

        self._session: aiohttp.ClientSession = session
        self.heartbeat: float = heartbeat
        self._retries: int | None = retries

        self.client: nextcord.Client | None = None
        self._websocket: Websocket = MISSING
        self._session_id: str | None = None

        self._players: dict[int, Player] = {}

        self._status: NodeStatus = NodeStatus.DISCONNECTED
        self._major_version: int | None = None

        self._spotify: spotify_.SpotifyClient | None = None

    def __repr__(self) -> str:
        return f'Node: id="{self._id}", uri="{self.uri}", status={self.status}'

    def __eq__(self, other: object) -> bool:
        return self.id == other.id if isinstance(other, Node) else NotImplemented

    @property
    def id(self) -> str:
        """The Nodes unique identifier."""
        return self._id

    @property
    def uri(self) -> str:
        """The URI used to connect this Node to Lavalink."""
        return self._host

    @property
    def password(self) -> str:
        """The password used to connect this Node to Lavalink."""
        return self._password

    @property
    def players(self) -> dict[int, Player]:
        """A mapping of Guild ID to Player."""
        return self._players

    @property
    def status(self) -> NodeStatus:
        """The connection status of this Node.
        DISCONNECTED
        CONNECTING
        CONNECTED
        """
        return self._status

    def get_player(self, guild_id: int, /) -> Player | None:
        """Return the :class:`player.Player` associated with the provided guild ID.
        If no :class:`player.Player` is found, returns None.
        Parameters
        ----------
        guild_id: int
            The Guild ID to return a Player for.
        Returns
        -------
        Optional[:class:`player.Player`]
        """
        return self._players.get(guild_id, None)

    async def _connect(self, client: nextcord.Client) -> None:
        if client.user is None:
            raise RuntimeError('')

        if not self._session:
            self._session = aiohttp.ClientSession(headers={'Authorization': self._password})

        self.client = client

        self._websocket = Websocket(node=self)

        await self._websocket.connect()

        async with self._session.get(f'{self._host}/version') as resp:
            version: str = await resp.text()

            if version.endswith('-SNAPSHOT'):
                self._major_version = 3
                return

            version_tuple = tuple(int(v) for v in version.split('.'))
            if version_tuple[0] < 3:
                raise InvalidLavalinkVersion(f'Synclink 2 is not compatible with Lavalink "{version}".')

            if version_tuple[0] == 3 and version_tuple[1] < 7:
                raise InvalidLavalinkVersion('Synclink 2 is not compatible with Lavalink versions under "3.7".')

            self._major_version = version_tuple[0]

    async def _send(self,
                    *,
                    method: str,
                    path: str,
                    guild_id: int | str | None = None,
                    query: str | None = None,
                    data: Request | None = None,
                    ) -> dict[str, Any] | None:

        uri: str = f'{self._host}/' \
                   f'v{self._major_version}/' \
                   f'{path}' \
                   f'{f"/{guild_id}" if guild_id else ""}' \
                   f'{f"?{query}" if query else ""}'

        async with self._session.request(method=method, url=uri, json=data or {}) as resp:
            if resp.status >= 300:
                raise InvalidLavalinkResponse(f'An error occurred when attempting to reach: "{uri}".',
                                              status=resp.status)

            if resp.status == 204:
                return

            return await resp.json()

    async def get_tracks(self, cls: type[PlayableT], query: str) -> list[PlayableT]:
        """|coro|
        Search for and retrieve Tracks based on the query and cls provided.
        .. note::
            If the query is not a Local search or direct URL, you will need to provide a search prefix.
            E.g. ``ytsearch:`` for a YouTube search.
        Parameters
        ----------
        cls: type[PlayableT]
            The type of Playable tracks that should be returned.
        query: str
            The query to search for and return tracks.
        Returns
        -------
        list[PlayableT]
            A list of found tracks converted to the provided cls.
        """
        data = await self._send(method='GET', path='loadtracks', query=f'identifier={query}')
        load_type = try_enum(LoadType, data.get("loadType"))

        if load_type is LoadType.load_failed:
            # TODO - Proper Exception...

            raise ValueError('Track Failed to load.')

        if load_type is LoadType.no_matches:
            return []

        if load_type is LoadType.track_loaded:
            track_data = data["tracks"][0]
            return [cls(track_data)]

        if load_type is not LoadType.search_result:
            # TODO - Proper Exception...

            raise ValueError('Track Failed to load.')

        return [cls(track_data) for track_data in data["tracks"]]

    async def get_playlist(self, cls: Playlist, query: str):
        """|coro|
        Search for and return a :class:`tracks.Playlist` given an identifier.
        Parameters
        ----------
        cls: Type[:class:`tracks.Playlist`]
            The type of which playlist should be returned, this must subclass :class:`tracks.Playlist`.
        query: str
            The playlist's identifier. This may be a YouTube playlist URL for example.
        Returns
        -------
        Optional[:class:`tracks.Playlist`]:
            The related synclink track object or ``None`` if none was found.
        Raises
        ------
        ValueError
            Loading the playlist failed.
        SynclinkException
            An unspecified error occurred when loading the playlist.
        """
        data = await self._send(method='GET', path='loadtracks', query=f'identifier={query}')

        load_type = try_enum(LoadType, data.get("loadType"))

        if load_type is LoadType.load_failed:
            # TODO Proper exception...
            raise ValueError('Tracks failed to Load.')

        if load_type is LoadType.no_matches:
            return None

        if load_type is not LoadType.playlist_loaded:
            raise SynclinkException("Track failed to load.")

        return cls(data)

    async def build_track(self, *, cls: type[PlayableT], encoded: str) -> PlayableT:
        """|coro|
        Build a track from the provided encoded string with the given Track class.
        Parameters
        ----------
        cls: type[PlayableT]
            The type of Playable track that should be returned.
        encoded: str
            The Tracks unique encoded string.
        """
        encoded = urllib.parse.quote(encoded)
        data = await self._send(method='GET', path='decodetrack', query=f'encodedTrack={encoded}')

        return cls(data=data)


# noinspection PyShadowingBuiltins
class NodePool:
    """The Synclink NodePool is responsible for keeping track of all :class:`Node`.
    Attributes
    ----------
    nodes: dict[str, :class:`Node`]
        A mapping of :class:`Node` identifier to :class:`Node`.
    .. warning::
        This class should never be initialised. All methods are class methods.
    """

    __nodes: dict[str, Node] = {}

    @classmethod
    async def connect(
            cls,
            *,
            client: nextcord.Client,
            nodes: list[Node],
            spotify: spotify_.SpotifyClient | None = None
    ) -> dict[str, Node]:
        """|coro|
        Connect a list of Nodes.
        Parameters
        ----------
        client: :class:`nexctord.Client`
            The nextcord Client or Bot used to connect the Nodes.
        nodes: list[:class:`Node`]
            A list of Nodes to connect.
        spotify: Optional[:class:`ext.spotify.SpotifyClient`]
            The spotify Client to use when searching for Spotify Tracks.
        Returns
        -------
        dict[str, :class:`Node`]
            A mapping of :class:`Node` identifier to :class:`Node`.
        """
        if client.user is None:
            raise RuntimeError('')

        for node in nodes:

            if spotify:
                node._spotify = spotify

            if node.id in cls.__nodes:
                logger.error(f'A Node with the ID "{node.id}" already exists on the NodePool. Disregarding.')
                continue

            try:
                await node._connect(client)
            except AuthorizationFailed:
                logger.error(f'The Node <{node!r}> failed to authenticate properly. '
                             f'Please check your password and try again.')
            else:
                cls.__nodes[node.id] = node

        return cls.nodes

    @classproperty
    def nodes(cls) -> dict[str, Node]:
        """A mapping of :class:`Node` identifier to :class:`Node`."""
        return cls.__nodes

    @classmethod
    def get_node(cls, id: str | None = None) -> Node:
        """Retrieve a :class:`Node` with the given ID or best, if no ID was passed.
        Parameters
        ----------
        id: Optional[str]
            The unique identifier of the :class:`Node` to retrieve. If not passed the best :class:`Node`
            will be fetched.
        Returns
        -------
        :class:`Node`
        Raises
        ------
        InvalidNode
            The given id does nto resolve to a :class:`Node` or no :class:`Node` has been connected.
        """
        if id:
            if id not in cls.__nodes:
                raise InvalidNode(f'A Node with ID "{id}" does not exist on the Synclink NodePool.')

            return cls.__nodes[id]

        if not cls.__nodes:
            raise InvalidNode('No Node currently exists on the Synclink NodePool.')

        nodes = cls.__nodes.values()
        return sorted(nodes, key=lambda n: len(n.players))[0]

    @classmethod
    def get_connected_node(cls) -> Node:
        """Get the best available connected :class:`Node`.
        Returns
        -------
        :class:`Node`
            The best available connected Node.
        Raises
        ------
        InvalidNode
            No Nodes are currently in the connected state.
        """

        nodes: list[Node] = [n for n in cls.__nodes.values() if n.status is NodeStatus.CONNECTED]
        if not nodes:
            raise InvalidNode('There are no Nodes on the Synclink NodePool that are currently in the connected state.')

        return sorted(nodes, key=lambda n: len(n.players))[0]

    @classmethod
    async def get_tracks(cls_,  # type: ignore
                         query: str,
                         /,
                         *,
                         cls: type[PlayableT],
                         node: Node | None = None
                         ) -> list[PlayableT]:
        """|coro|
        Helper method to retrieve tracks from the NodePool without fetching a :class:`Node`.
        Parameters
        ----------
        query: str
            The query to search for and return tracks.
        cls: type[PlayableT]
            The type of Playable tracks that should be returned.
        node: Optional[:class:`Node`]
            The node to use for retrieving tracks. If not passed, the best :class:`Node` will be used.
            Defaults to None.
        Returns
        -------
        list[PlayableT]
            A list of found tracks converted to the provided cls.
        """
        if not node:
            node = cls_.get_connected_node()

        return await node.get_tracks(cls=cls, query=query)

    @classmethod
    async def get_playlist(cls_,  # type: ignore
                           query: str,
                           /,
                           *,
                           cls: Playlist,
                           node: Node | None = None
                           ) -> Playlist:
        """|coro|
        Helper method to retrieve a playlist from the NodePool without fetching a :class:`Node`.
        .. warning::
            The only playlist currently supported is :class:`tracks.YouTubePlaylist`.
        Parameters
        ----------
        query: str
            The query to search for and return a playlist.
        cls: type[PlayableT]
            The type of Playlist that should be returned.
        node: Optional[:class:`Node`]
            The node to use for retrieving tracks. If not passed, the best :class:`Node` will be used.
            Defaults to None.
        Returns
        -------
        Playlist
            A Playlist with its tracks.
        """
        if not node:
            node = cls_.get_connected_node()

        return await node.get_playlist(cls=cls, query=query)
