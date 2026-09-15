# Media YouTube connection

`channelId` is set in both `data/media-videos.ko.json` and `data/media-videos.en.json`
and points at the Metanomia channel (`UCpx2b9zuLWHvtiSit8jwVIg`). Every
`programs.*.playlistId` is still blank, which is what the two feeds do differently:

- **All Videos** (`/media`, `/ko/media`) falls back to the channel feed when no
  playlist is set, so uploads appear there without any further configuration.
- **Individual program pages** (`/media/weekly-crypto` and the rest) show manually
  curated items whose `program` matches the page. A configured `playlistId` adds
  that program's YouTube playlist feed. The preparation message appears only
  when there are no matching videos.

## Manually curated videos

The first Crypto Tutoring video (`KYK9EYB6xk0`, published 2026-09-14) is registered
in the `items` array in both language files. It appears in Crypto Tutoring, All
Videos, and the media page's latest-video panel. Cards open YouTube in a new tab.

Each item has `program`, localized `type` and `title`, `url`, `thumbnail`, `date`,
and `published`. Keep `program`, URL, thumbnail, ISO `date` (`YYYY-MM-DD`), and
publication timestamp identical across languages. Use a canonical URL such as
`https://www.youtube.com/watch?v=KYK9EYB6xk0`, without share parameters: the feed
deduplicates by exact URL and gives curated metadata priority over RSS metadata.
Curated cards remain visible if the remote feed is temporarily unavailable.

## Automatic playlist feeds

To finish the connection:

1. Create one public YouTube playlist per program.
2. Copy each playlist ID (the `list=` value in the playlist URL, starting with `PL`)
   into the matching `programs` entry.
3. Use the same IDs in both language files; keep translated `type` and `name`
   values in each file.

The `/api/youtube-feed` endpoint reads YouTube's public RSS feeds without an API
key, so no credentials or quota apply. New uploads appear once the deployment
cache refreshes, normally within 15 minutes. Videos can be manually curated
before a playlist is connected.
