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

import abc
from typing import TYPE_CHECKING, ClassVar, Literal, overload, Optional, Any

import aiohttp
import yarl
from nextcord.ext import commands

from .enums import TrackSource
from .exceptions import NoTracksError
from .node import Node, NodePool

if TYPE_CHECKING:
    from typing_extensions import Self

    from .types.track import Track as TrackPayload

__all__ = (
    'Playable',
    'Playlist',
    'YouTubeTrack',
    'GenericTrack',
    'YouTubeMusicTrack',
    'SoundCloudTrack',
    'YouTubePlaylist'
)


_source_mapping: dict[str, TrackSource] = {
    'youtube': TrackSource.YouTube
}


class Playlist(metaclass=abc.ABCMeta):
    """An ABC that defines the basic structure of a lavalink playlist resource.
    Attributes
    ----------
    data: Dict[str, Any]
        The raw data supplied by Lavalink.
    """

    def __init__(self, data: dict[str, Any]):
        self.data: dict[str, Any] = data


class Playable(metaclass=abc.ABCMeta):
    """Base ABC Track used in all the Synclink Track types.
    Attributes
    ----------
    data: dict[str, Any]
        The raw data received via Lavalink.
    encoded: str
        The encoded Track string.
    is_seekable: bool
        Whether the Track is seekable.
    is_stream: bool
        Whether the Track is a stream.
    length: int
        The length of the track in milliseconds.
    duration: int
        An alias for length.
    position: int
        The position the track will start in milliseconds. Defaults to 0.
    title: str
        The Track title.
    source: :class:`TrackSource`
        The source this Track was fetched from.
    uri: Optional[str]
        The URI of this track. Could be None.
    author: Optional[str]
        The author of this track. Could be None.
    identifier: Optional[str]
        The Youtube/YoutubeMusic identifier for this track. Could be None.
    """

    PREFIX: ClassVar[str] = ''
    
    def __init__(self, data: TrackPayload) -> None:
        self.data: TrackPayload = data
        self.encoded: str = data['encoded']

        info = data['info']
        self.is_seekable: bool = info.get('isSeekable', False)
        self.is_stream: bool = info.get('isStream', False)
        self.length: int = info.get('length', 0)
        self.duration: int = self.length
        self.position: int = info.get('position', 0)

        self.title: str = info.get('title', 'Unknown Title')

        source: str | None = info.get('sourceName')
        self.source: TrackSource = _source_mapping.get(source, TrackSource.Unknown)

        self.uri: str | None = info.get('uri')
        self.author: str | None = info.get('author')
        self.identifier: str | None = info.get('identifier')

    def __str__(self) -> str:
        return self.title

    def __repr__(self) -> str:
        return f'Playable: source={self.source}, title={self.title}'

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Playable):
            return self.encoded == other.encoded
        return NotImplemented
    
    @overload
    @classmethod
    async def search(cls,
                     query: str,
                     /,
                     *,
                     return_first: Literal[False] = ...,
                     node: Node | None = ...
                     ) -> list[Self]:
        ...

    @overload
    @classmethod
    async def search(cls,
                     query: str,
                     /,
                     *,
                     return_first: Literal[True] = ...,
                     node: Node | None = ...
                     ) -> Self:
        ...

    @overload
    @classmethod
    async def search(cls,
                     query: str,
                     /,
                     *,
                     return_first: bool = ...,
                     node: Node | None = ...
                     ) -> Self | list[Self]:
        ...

    @overload
    @classmethod
    async def search(cls,
                     query: str,
                     /,
                     *,
                     return_first: bool = ...,
                     node: Node | None = ...
                     ) -> YouTubePlaylist:
        ...

    @classmethod
    async def search(cls,
                     query: str,
                     /,
                     *,
                     return_first: bool = False,
                     node: Node | None = None
                     ) -> Self | list[Self]:
        """Search and retrieve tracks for the given query.
        Parameters
        ----------
        query: str
            The query to search for.
        return_first: Optional[bool]
            Whether to return the first track from the search results. Defaults to False.
        node: Optional[:class:`Node`]
            The node to use when searching for tracks. If no :class:`Node` is passed,
            one will be fetched via the :class:`NodePool`.
        """

        check = yarl.URL(query)

        if str(check.host) == 'youtube.com' or str(check.host) == 'www.youtube.com' and check.query.get("list") or \
                cls.PREFIX == 'ytpl:':

            playlist = await NodePool.get_playlist(query, cls=YouTubePlaylist, node=node)
            return playlist
        else:
            tracks = await NodePool.get_tracks(f'{cls.PREFIX}{query}', cls=cls, node=node)
        
        try:
            track = tracks[0]
        except IndexError:
            raise NoTracksError(f'Your search query "{query}" returned no tracks.')

        if return_first:
            return track

        return tracks

    @classmethod
    async def convert(cls, ctx: commands.Context, argument: str) -> Self:
        """Converter which searches for and returns the first track.
        Used as a type hint in a nextcord command.
        """
        results = await cls.search(argument)

        if not results:
            raise commands.BadArgument("Could not find any songs matching that query.")

        if issubclass(cls, YouTubePlaylist):
            return results  # type: ignore

        return results[0]


class GenericTrack(Playable):
    """Generic Synclink Track.
    Use this track for searching for Local songs or direct URLs.
    """
    ...


class YouTubeTrack(Playable):

    PREFIX: str = 'ytsearch:'

    @property
    def thumbnail(self) -> str:
        """The URL to the thumbnail of this video.
        .. note::
            Due to YouTube limitations this may not always return a valid thumbnail.
            Use :func:`.fetch_thumbnail` to fallback.
        Returns
        -------
        str
            The URL to the video thumbnail.
        """
        return f"https://img.youtube.com/vi/{self.identifier}/maxresdefault.jpg"

    thumb = thumbnail

    async def fetch_thumbnail(self, *, node: Node | None = None) -> str:
        """Fetch the max resolution thumbnail with a fallback if it does not exist.
        .. note::
            This method uses an API request to fetch the thumbnail.
        Returns
        -------
        str
            The URL to the video thumbnail.
        """
        if not node:
            node = NodePool.get_node()

        session: aiohttp.ClientSession = node._session
        url: str = f"https://img.youtube.com/vi/{self.identifier}/maxresdefault.jpg"

        async with session.get(url=url) as resp:
            if resp.status == 404:
                url = f'https://img.youtube.com/vi/{self.identifier}/hqdefault.jpg'

        return url


class YouTubeMusicTrack(YouTubeTrack):
    """A track created using a search to YouTube Music."""

    PREFIX: str = "ytmsearch:"


class SoundCloudTrack(Playable):
    """A track created using a search to SoundCloud."""

    PREFIX: str = "scsearch:"


class YouTubePlaylist(Playable, Playlist):
    """Represents a Lavalink YouTube playlist object.
    Attributes
    ----------
    name: str
        The name of the playlist.
    tracks: :class:`YouTubeTrack`
        The list of :class:`YouTubeTrack` in the playlist.
    selected_track: Optional[int]
        The selected video in the playlist. This could be ``None``.
    """

    PREFIX: str = "ytpl:"

    def __init__(self, data: dict):
        self.tracks: list[YouTubeTrack] = []
        self.name: str = data["playlistInfo"]["name"]

        self.selected_track: Optional[int] = data["playlistInfo"].get("selectedTrack")
        if self.selected_track is not None:
            self.selected_track = int(self.selected_track)

        for track_data in data["tracks"]:
            track = YouTubeTrack(track_data)
            self.tracks.append(track)

    def __str__(self) -> str:
        return self.name
