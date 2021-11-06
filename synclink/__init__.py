__title__ = 'Synclink'
__author__ = 'Zekann'
__license__ = 'MIT'
__copyright__ = 'Copyright 2021 (c) Zekann'
__version__ = '1.0.0a'

from .client import Client
from .errors import *
from .eqs import *
from .events import *
from .player import *
from .node import Node
from .meta import WavelinkMixin
from .websocket import WebSocket
