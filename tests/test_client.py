"""Fetching, from core/response-fetching, against a local server."""

from __future__ import annotations

import gzip
from collections.abc import AsyncIterator, Awaitable, Callable

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestServer

from rest_mapper.client import (
    AuthFailedError,
    BearerAuth,
    ClientFailedError,
    ConnectFailedError,
    Fetched,
    FetchSpec,
    FormatError,
    HeaderAuth,
    NotModified,
    QueryAuth,
    RateLimitedError,
    RedirectError,
    ServerFailedError,
    SizeExceededError,
    decode_json,
    fetch,
    redact_url,
)
from rest_mapper.policy import Validators

type Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]
type Serve = Callable[[Handler], Awaitable[str]]


@pytest_asyncio.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as client:
        yield client


@pytest_asyncio.fixture
async def serve() -> AsyncIterator[Serve]:
    servers: list[TestServer] = []

    async def start(handler: Handler) -> str:
        app = web.Application()
        app.router.add_get("/{tail:.*}", handler)
        server = TestServer(app)
        await server.start_server()
        servers.append(server)
        return str(server.make_url("/data"))

    yield start
    for server in servers:
        await server.close()


async def test_bearer(serve: Serve, session: aiohttp.ClientSession) -> None:
    async def handler(request: web.Request) -> web.Response:
        assert request.headers["Authorization"] == "Bearer abc"
        return web.json_response({})

    url = await serve(handler)
    assert isinstance(await fetch(session, FetchSpec(url, BearerAuth("abc"))), Fetched)


async def test_header_key(serve: Serve, session: aiohttp.ClientSession) -> None:
    async def handler(request: web.Request) -> web.Response:
        assert request.headers["X-Key"] == "abc"
        return web.json_response({})

    url = await serve(handler)
    await fetch(session, FetchSpec(url, HeaderAuth("X-Key", "abc")))


async def test_key_in_a_query_parameter(serve: Serve, session: aiohttp.ClientSession) -> None:
    async def handler(request: web.Request) -> web.Response:
        assert request.query["a"] == "1"
        assert request.query["key"] == "abc"
        return web.json_response({})

    url = await serve(handler)
    await fetch(session, FetchSpec(f"{url}?a=1", QueryAuth("key", "abc")))


async def test_same_origin_redirect(serve: Serve, session: aiohttp.ClientSession) -> None:
    async def handler(request: web.Request) -> web.Response:
        if request.path == "/data":
            raise web.HTTPFound("/moved")
        assert request.headers["X-Key"] == "abc"
        return web.json_response({})

    url = await serve(handler)
    assert isinstance(await fetch(session, FetchSpec(url, HeaderAuth("X-Key", "abc"))), Fetched)


async def test_same_origin_redirect_keeps_a_query_key(
    serve: Serve, session: aiohttp.ClientSession
) -> None:
    async def handler(request: web.Request) -> web.Response:
        if request.path == "/data":
            raise web.HTTPFound("/moved")
        assert request.query["k"] == "v"
        return web.json_response({})

    url = await serve(handler)
    assert isinstance(await fetch(session, FetchSpec(url, QueryAuth("k", "v"))), Fetched)


async def test_redirect_to_another_host(serve: Serve, session: aiohttp.ClientSession) -> None:
    seen: list[str] = []

    async def other(request: web.Request) -> web.Response:
        seen.append(request.path)
        return web.json_response({})

    other_url = await serve(other)

    async def handler(_: web.Request) -> web.Response:
        raise web.HTTPFound(other_url)

    url = await serve(handler)
    with pytest.raises(RedirectError):
        await fetch(session, FetchSpec(url, HeaderAuth("X-Key", "abc")))
    assert seen == []


async def test_redirect_loop(serve: Serve, session: aiohttp.ClientSession) -> None:
    async def handler(_: web.Request) -> web.Response:
        raise web.HTTPFound("/data")

    with pytest.raises(RedirectError):
        await fetch(session, FetchSpec(await serve(handler)))


async def test_declared_too_large(serve: Serve, session: aiohttp.ClientSession) -> None:
    async def handler(_: web.Request) -> web.Response:
        return web.Response(body=b"x" * 2000)

    with pytest.raises(SizeExceededError):
        await fetch(session, FetchSpec(await serve(handler), max_bytes=1000))


async def test_undeclared_too_large(serve: Serve, session: aiohttp.ClientSession) -> None:
    async def handler(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse()
        await response.prepare(request)
        for _ in range(10):
            await response.write(b"x" * 500)
        await response.write_eof()
        return response

    with pytest.raises(SizeExceededError):
        await fetch(session, FetchSpec(await serve(handler), max_bytes=1000))


async def test_compressed_too_large(serve: Serve, session: aiohttp.ClientSession) -> None:
    async def handler(_: web.Request) -> web.Response:
        return web.Response(
            body=gzip.compress(b"x" * 1_000_000), headers={"Content-Encoding": "gzip"}
        )

    with pytest.raises(SizeExceededError):
        await fetch(session, FetchSpec(await serve(handler), max_bytes=100_000))


async def test_validators(serve: Serve, session: aiohttp.ClientSession) -> None:
    async def handler(request: web.Request) -> web.Response:
        assert request.headers["If-None-Match"] == '"a"'
        assert request.headers["If-Modified-Since"] == "then"
        return web.Response(status=304)

    url = await serve(handler)
    assert isinstance(await fetch(session, FetchSpec(url), Validators('"a"', "then")), NotModified)


async def test_validators_returned(serve: Serve, session: aiohttp.ClientSession) -> None:
    async def handler(_: web.Request) -> web.Response:
        return web.json_response({}, headers={"ETag": '"a"', "Last-Modified": "then"})

    result = await fetch(session, FetchSpec(await serve(handler)))
    assert isinstance(result, Fetched)
    assert (result.etag, result.last_modified) == ('"a"', "then")


@pytest.mark.parametrize("status", [401, 403])
async def test_refused_credentials(
    serve: Serve, session: aiohttp.ClientSession, status: int
) -> None:
    async def handler(_: web.Request) -> web.Response:
        return web.Response(status=status)

    with pytest.raises(AuthFailedError):
        await fetch(session, FetchSpec(await serve(handler)))


async def test_rate_limit(serve: Serve, session: aiohttp.ClientSession) -> None:
    async def handler(_: web.Request) -> web.Response:
        return web.Response(status=429, headers={"Retry-After": "120"})

    with pytest.raises(RateLimitedError) as error:
        await fetch(session, FetchSpec(await serve(handler)))
    assert error.value.retry_after == "120"


async def test_server_error(serve: Serve, session: aiohttp.ClientSession) -> None:
    async def handler(_: web.Request) -> web.Response:
        return web.Response(status=503, headers={"Retry-After": "5"})

    with pytest.raises(ServerFailedError) as error:
        await fetch(session, FetchSpec(await serve(handler)))
    assert error.value.retry_after == "5"


async def test_missing_resource(serve: Serve, session: aiohttp.ClientSession) -> None:
    async def handler(_: web.Request) -> web.Response:
        return web.Response(status=404)

    with pytest.raises(ClientFailedError) as error:
        await fetch(session, FetchSpec(await serve(handler)))
    assert error.value.status == 404


async def test_connection_failure_hides_the_key(session: aiohttp.ClientSession) -> None:
    spec = FetchSpec("http://127.0.0.1:1/data?other=hidden", QueryAuth("key", "secret"))
    with pytest.raises(ConnectFailedError) as error:
        await fetch(session, spec)
    assert "secret" not in str(error.value)
    assert "hidden" not in str(error.value)
    assert "127.0.0.1:1/data" in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__


def test_wrong_content_type_is_decoded() -> None:
    assert decode_json(b'{"a": 1}') == {"a": 1}


def test_byte_order_mark() -> None:
    assert decode_json(b'\xef\xbb\xbf{"a": 1}') == {"a": 1}


@pytest.mark.parametrize("body", [b"<html>secret</html>", b"\xff\xfe", b"NaN", b"[Infinity]"])
def test_not_json(body: bytes) -> None:
    with pytest.raises(FormatError) as error:
        decode_json(body)
    assert "secret" not in str(error.value)


def test_integer_past_the_digit_limit() -> None:
    with pytest.raises(FormatError):
        decode_json(b"1" * 5000)


async def test_url_with_a_space_is_encoded(serve: Serve, session: aiohttp.ClientSession) -> None:
    async def handler(request: web.Request) -> web.Response:
        assert request.path == "/data/a b"
        return web.json_response({})

    url = await serve(handler)
    assert isinstance(await fetch(session, FetchSpec(f"{url}/a b")), Fetched)


def test_redact_url() -> None:
    assert redact_url("https://u:p@example.com:8443/a?k=v#f") == "https://example.com:8443/a"


def test_reprs_hold_no_secrets() -> None:
    spec = FetchSpec("https://example.com/?key=secret", BearerAuth("secret"))
    assert "secret" not in repr(spec)
    assert "secret" not in repr(HeaderAuth("X", "secret"))
    assert "secret" not in repr(QueryAuth("k", "secret"))
