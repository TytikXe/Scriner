from __future__ import annotations

import socket

import aiohttp
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession


def build_bot(token: str) -> Bot:
    session = AiohttpSession()
    session._connector_init["family"] = socket.AF_INET
    session._connector_init["resolver"] = aiohttp.ThreadedResolver()
    return Bot(token, session=session)
