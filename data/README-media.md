# Media YouTube connection

`channelId` is set in both `data/media-videos.ko.json` and `data/media-videos.en.json`
and points at the Metanomia channel (`UCpx2b9zuLWHvtiSit8jwVIg`). Every
`programs.*.playlistId` is still blank, which is what the two feeds do differently:

- **All Videos** (`/media`, `/ko/media`) falls back to the channel feed when no
  playlist is set, so uploads appear there without any further configuration.
- **Individual program pages** (`/media/weekly-crypto` and the rest) have no
  fallback. Each one keeps showing its preparation message until that program's
  `playlistId` is filled in.

To finish the connection:

1. Create one public YouTube playlist per program.
2. Copy each playlist ID (the `list=` value in the playlist URL, starting with `PL`)
   into the matching `programs` entry.
3. Use the same IDs in both language files; keep translated `type` and `name`
   values in each file.

The `/api/youtube-feed` endpoint reads YouTube's public RSS feeds without an API
key, so no credentials or quota apply. New uploads appear once the deployment
cache refreshes, normally within 15 minutes. The optional `items` array can still
be used for manually curated videos.
