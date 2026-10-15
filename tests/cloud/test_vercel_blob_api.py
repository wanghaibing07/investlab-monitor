"""Verify the exact public Vercel Blob SDK 0.12 API, without using credentials."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from investlab import cloud


class FakeDownload:
    def __init__(self, content: bytes, declared_size: int | None = None):
        self.content = content
        self.metadata = SimpleNamespace(
            status_code=200,
            size=len(content) if declared_size is None else declared_size,
        )

    def __aiter__(self):
        self.sent = False
        return self

    async def __anext__(self):
        if self.sent:
            raise StopAsyncIteration
        self.sent = True
        return self.content


class FakeStream:
    def __init__(self, content: bytes, declared_size: int | None = None):
        self.result = FakeDownload(content, declared_size)

    async def __aenter__(self):
        return self.result

    async def __aexit__(self, *_exc):
        return False


class BlobAdapterTests(unittest.TestCase):
    def test_installed_sdk_public_exports(self):
        from vercel.blob import put_blob, query_blobs, stream_blob
        self.assertTrue(callable(put_blob))
        self.assertTrue(callable(query_blobs))
        self.assertTrue(callable(stream_blob))

    def test_query_blobs_uses_current_async_iterator(self):
        options = []
        async def results():
            for name in ("state/20261015-1.zip", "state/20261015-2.zip"):
                yield SimpleNamespace(pathname=name)

        def query(**kwargs):
            options.append(kwargs)
            return results()

        with patch("vercel.blob.query_blobs", new=query):
            items = asyncio.run(cloud._list("state/"))
        self.assertEqual([x.pathname for x in items], [
            "state/20261015-1.zip", "state/20261015-2.zip"])
        self.assertEqual(options, [{"prefix": "state/", "page_size": 1000}])

    def test_read_private_blob_by_path_and_limits_size(self):
        with patch("vercel.blob.stream_blob",
                   return_value=FakeStream(b"private bytes")) as stream:
            data = asyncio.run(cloud._read("state/a.zip", max_size=1024))
        self.assertEqual(data, b"private bytes")
        stream.assert_called_once_with("state/a.zip", access="private")
        with patch("vercel.blob.stream_blob",
                   return_value=FakeStream(b"x", declared_size=999)):
            with self.assertRaisesRegex(ValueError, "maximum"):
                asyncio.run(cloud._read("state/a.zip", max_size=20))

    def test_private_write_never_overwrites(self):
        async_put = AsyncMock(return_value=SimpleNamespace(pathname="state/new.zip"))
        with patch("vercel.blob.put_blob", new=async_put):
            path = asyncio.run(cloud._write("state", b"SQLite private backup", "zip"))
        self.assertEqual(path, "state/new.zip")
        self.assertEqual(async_put.await_count, 1)
        args, opts = async_put.await_args
        self.assertTrue(args[0].startswith("state/"))
        self.assertTrue(args[0].endswith(".zip"))
        self.assertEqual(args[1], b"SQLite private backup")
        self.assertEqual(opts["access"], "private")
        self.assertFalse(opts["allow_overwrite"])
        self.assertFalse(opts["add_random_suffix"])
        self.assertEqual(opts["content_type"], "application/zip")

    def test_latest_version_is_stably_selected(self):
        first = SimpleNamespace(pathname="runs/20261015-old.json")
        second = SimpleNamespace(pathname="runs/20261016-new.json")
        with (patch("investlab.cloud._list", new=AsyncMock(
                    return_value=[second, first])),
              patch("investlab.cloud._read", new=AsyncMock(
                    return_value=b'{"status":"SETUP_REQUIRED"}')) as reader):
            value = asyncio.run(cloud.latest_json("runs"))
        self.assertEqual(value["status"], "SETUP_REQUIRED")
        reader.assert_awaited_once_with(second.pathname, max_size=2_000_000)


if __name__ == "__main__":
    unittest.main()
