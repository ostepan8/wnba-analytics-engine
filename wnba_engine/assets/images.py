"""Mirror team logos and player headshots into our own object storage.

**Why mirror rather than hotlink.** Pointing an <img> at a provider's CDN makes
every page view a request to someone else's infrastructure for an asset we do
not control: they can rename a path, rate-limit us, or serve something
different, and the site breaks in a way no test catches. Fetching once and
serving from our own bucket also means the image path stops depending on a
provider id, which is exactly the kind of coupling the crosswalk table exists to
contain.

Sizes are requested from the provider's own resizer rather than downloading
full-resolution art and shrinking it here: a headshot is 300 KB at source and
36 KB at display size, and there is no reason to move the other 264 KB across
the network, into the bucket, and out again to every visitor.

Idempotent. An object already present is left alone unless --force is passed,
so a re-run after adding twenty players fetches twenty images, not six hundred.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

# The provider's image resizer. Requesting display size rather than source size
# is a ~90% bandwidth saving on headshots.
ESPN_COMBINER = "https://a.espncdn.com/combiner/i"
HEADSHOT_PATH = "/i/headshots/wnba/players/full/{external_id}.png"
LOGO_PATH = "/i/teamlogos/wnba/500/{abbreviation}.png"

HEADSHOT_WIDTH = 350
LOGO_WIDTH = 240

BUCKET = "wnba-assets"
PLAYER_PREFIX = "players"
TEAM_PREFIX = "teams"

# A provider 404 for one player is normal -- rookies and short-stint signings
# often have no headshot. It is not a failure of the sync.
MISSING_STATUSES = frozenset({403, 404})


class ObjectStore(Protocol):
    """The slice of S3 this needs. Narrow on purpose: it keeps the tests free of
    a real client and makes the MinIO/R2/S3 choice irrelevant here."""

    def exists(self, bucket: str, key: str) -> bool: ...
    def put(self, bucket: str, key: str, body: bytes, content_type: str) -> None: ...


@dataclass(frozen=True, slots=True)
class SyncResult:
    uploaded: int = 0
    skipped_existing: int = 0
    missing_upstream: int = 0
    failed: int = 0

    def __str__(self) -> str:
        return (
            f"{self.uploaded} uploaded, {self.skipped_existing} already present, "
            f"{self.missing_upstream} with no upstream image, {self.failed} failed"
        )


@dataclass(frozen=True, slots=True)
class ImageTarget:
    """One image to mirror: where to get it and where it lands."""

    key: str
    url: str
    params: dict[str, str]


def player_target(*, player_id: int, external_id: str) -> ImageTarget:
    return ImageTarget(
        key=f"{PLAYER_PREFIX}/{player_id}.png",
        url=ESPN_COMBINER,
        params={"img": HEADSHOT_PATH.format(external_id=external_id), "w": str(HEADSHOT_WIDTH)},
    )


def team_target(*, team_id: int, abbreviation: str) -> ImageTarget:
    return ImageTarget(
        key=f"{TEAM_PREFIX}/{team_id}.png",
        url=ESPN_COMBINER,
        params={"img": LOGO_PATH.format(abbreviation=abbreviation.lower()), "w": str(LOGO_WIDTH)},
    )


def sync_images(
    targets: list[ImageTarget],
    *,
    store: ObjectStore,
    client: httpx.Client,
    force: bool = False,
) -> SyncResult:
    """Fetch each target and upload it, skipping ones already stored.

    One target failing never stops the rest: a sync that gives up partway
    through leaves the site with a random subset of its images and no record of
    which ones, which is worse than finishing with a count of what failed.
    """
    result = SyncResult()
    for target in targets:
        try:
            result = _sync_one(target, store=store, client=client, force=force, result=result)
        except Exception:  # noqa: BLE001 -- one bad image must not sink the batch
            logger.exception("failed to mirror %s", target.key)
            result = replace(result, failed=result.failed + 1)
    logger.info("image sync: %s", result)
    return result


def _sync_one(
    target: ImageTarget,
    *,
    store: ObjectStore,
    client: httpx.Client,
    force: bool,
    result: SyncResult,
) -> SyncResult:
    if not force and store.exists(BUCKET, target.key):
        return replace(result, skipped_existing=result.skipped_existing + 1)

    response = client.get(target.url, params=target.params)
    if response.status_code in MISSING_STATUSES:
        logger.debug("no upstream image for %s", target.key)
        return replace(result, missing_upstream=result.missing_upstream + 1)
    response.raise_for_status()

    # A resizer that fails often answers 200 with an HTML error page. Uploading
    # that would put a broken "image" in the bucket that only a human looking at
    # the page would ever notice.
    content_type = response.headers.get("content-type", "")
    if not content_type.startswith("image/"):
        raise ValueError(f"{target.key}: expected an image, got {content_type!r}")

    store.put(BUCKET, target.key, response.content, content_type)
    return replace(result, uploaded=result.uploaded + 1)
