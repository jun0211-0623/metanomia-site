# Media YouTube connection

The site currently shows a preparation message because all IDs in `data/media-videos.ko.json` and `data/media-videos.en.json` are blank.

When the channel launches:

1. Put the YouTube channel ID in `channelId` for the All Videos feed.
2. Create one public YouTube playlist per program and put each playlist ID in the matching `programs` entry.
3. Use the same IDs in both language files; keep translated `type` values in each file.

The `/api/youtube-feed` endpoint reads YouTube's public RSS feeds without an API key. New uploads then appear automatically after the deployment cache refreshes (normally within 15 minutes). The optional `items` array can still be used for manually curated videos.