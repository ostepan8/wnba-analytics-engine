"""Mirroring images into our own storage.

The failure this guards against is a bucket full of things that are not images.
A resizer under load answers 200 with an HTML error page, and nothing downstream
notices: the upload succeeds, the key exists, a later sync skips it as "already
present", and the only symptom is a broken image on a page nobody is testing.
"""

from __future__ import annotations

import httpx
import pytest

from wnba_engine.assets.images import (
    BUCKET,
    player_target,
    sync_images,
    team_target,
)


class FakeStore:
    def __init__(self, existing: set[str] | None = None) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.existing = existing or set()

    def exists(self, bucket: str, key: str) -> bool:
        assert bucket == BUCKET
        return key in self.existing or key in self.objects

    def put(self, bucket: str, key: str, body: bytes, content_type: str) -> None:
        self.objects[key] = (body, content_type)


def client_returning(*responses: httpx.Response) -> httpx.Client:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if queue:
            return queue.pop(0)
        return httpx.Response(200, content=b"x", headers={"content-type": "image/png"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def png(content: bytes = b"\x89PNG-data") -> httpx.Response:
    return httpx.Response(200, content=content, headers={"content-type": "image/png"})


class TestTargets:
    def test_a_player_key_uses_our_id_not_the_providers(self) -> None:
        """The bucket path must not encode an ESPN id. Provider ids belong in the
        crosswalk table; baking one into a URL spreads that coupling into the
        frontend, where changing providers would break every image."""
        target = player_target(player_id=36, external_id="3149391")
        assert target.key == "players/36.png"
        assert "3149391" in target.params["img"]

    def test_a_team_logo_is_looked_up_by_lowercase_abbreviation(self) -> None:
        target = team_target(team_id=7, abbreviation="MIN")
        assert target.key == "teams/7.png"
        assert target.params["img"].endswith("/min.png")

    def test_display_size_is_requested_from_the_resizer(self) -> None:
        """A headshot is 300 KB at source and 36 KB at display size; asking the
        provider to resize avoids moving the other 264 KB three times."""
        assert player_target(player_id=1, external_id="9").params["w"] == "350"


class TestSync:
    def test_images_are_uploaded(self) -> None:
        store = FakeStore()
        result = sync_images(
            [player_target(player_id=36, external_id="3149391")],
            store=store, client=client_returning(png(b"IMAGE")),
        )
        assert result.uploaded == 1
        assert store.objects["players/36.png"] == (b"IMAGE", "image/png")

    def test_an_existing_object_is_skipped(self) -> None:
        """A re-run after adding twenty players must fetch twenty images, not
        six hundred."""
        store = FakeStore(existing={"players/36.png"})
        result = sync_images(
            [player_target(player_id=36, external_id="3149391")],
            store=store, client=client_returning(png()),
        )
        assert (result.skipped_existing, result.uploaded) == (1, 0)

    def test_force_refetches_an_existing_object(self) -> None:
        store = FakeStore(existing={"players/36.png"})
        result = sync_images(
            [player_target(player_id=36, external_id="3149391")],
            store=store, client=client_returning(png(b"NEW")), force=True,
        )
        assert result.uploaded == 1
        assert store.objects["players/36.png"][0] == b"NEW"

    @pytest.mark.parametrize("status", [403, 404])
    def test_a_player_with_no_upstream_image_is_counted_not_failed(self, status: int) -> None:
        """Rookies and short-stint signings often have no headshot. That is
        normal and must not read as a broken sync."""
        store = FakeStore()
        result = sync_images(
            [player_target(player_id=1, external_id="0")],
            store=store, client=client_returning(httpx.Response(status)),
        )
        assert (result.missing_upstream, result.failed, result.uploaded) == (1, 0, 0)
        assert store.objects == {}

    def test_an_html_error_page_is_never_stored_as_an_image(self) -> None:
        """The core guard. A 200 with text/html is a resizer error, and storing
        it poisons the key permanently -- every later sync skips it as present."""
        store = FakeStore()
        result = sync_images(
            [player_target(player_id=1, external_id="0")],
            store=store,
            client=client_returning(
                httpx.Response(200, content=b"<html>error</html>",
                               headers={"content-type": "text/html"})),
        )
        assert result.failed == 1
        assert store.objects == {}

    def test_one_failure_does_not_stop_the_batch(self) -> None:
        """A sync that gives up partway leaves a random subset of images stored
        and no record of which -- worse than finishing with a failure count."""
        store = FakeStore()
        result = sync_images(
            [
                player_target(player_id=1, external_id="a"),
                player_target(player_id=2, external_id="b"),
                player_target(player_id=3, external_id="c"),
            ],
            store=store,
            client=client_returning(
                png(b"ONE"),
                httpx.Response(200, content=b"nope", headers={"content-type": "text/html"}),
                png(b"THREE"),
            ),
        )
        assert (result.uploaded, result.failed) == (2, 1)
        assert set(store.objects) == {"players/1.png", "players/3.png"}

    def test_a_server_error_is_reported_as_a_failure(self) -> None:
        store = FakeStore()
        result = sync_images(
            [player_target(player_id=1, external_id="a")],
            store=store, client=client_returning(httpx.Response(500)),
        )
        assert (result.failed, result.uploaded) == (1, 0)
