/* Vercel serverless endpoint for Metanomia's public YouTube feeds. */
const koConfig = require('../data/media-videos.ko.json');
const enConfig = require('../data/media-videos.en.json');

function decodeXml(value = '') {
  return value
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, '$1')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'");
}

function tag(entry, name) {
  const match = entry.match(new RegExp(`<${name}[^>]*>([\\s\\S]*?)<\\/${name}>`, 'i'));
  return match ? decodeXml(match[1].trim()) : '';
}

function parseFeed(xml, program, programInfo, lang) {
  const entries = xml.match(/<entry>[\s\S]*?<\/entry>/g) || [];
  return entries.map((entry) => {
    const videoId = tag(entry, 'yt:videoId');
    const published = tag(entry, 'published');
    const date = published ? new Date(published) : null;
    const displayDate = date && !Number.isNaN(date.getTime())
      ? (lang === 'ko'
          ? `${date.getUTCFullYear()}년 ${date.getUTCMonth() + 1}월 ${date.getUTCDate()}일`
          : date.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' }))
      : '';
    return {
      program,
      type: programInfo?.type || (lang === 'ko' ? '영상' : 'Video'),
      title: tag(entry, 'title'),
      url: videoId ? `https://www.youtube.com/watch?v=${videoId}` : tag(entry, 'link'),
      thumbnail: videoId ? `https://i.ytimg.com/vi/${videoId}/maxresdefault.jpg` : '',
      date: displayDate,
      published
    };
  }).filter((item) => item.url && item.title);
}

async function fetchFeed(url, program, info, lang) {
  const response = await fetch(url, { headers: { 'user-agent': 'Metanomia/1.0' } });
  if (!response.ok) throw new Error(`YouTube feed ${response.status}`);
  return parseFeed(await response.text(), program, info, lang);
}

function mergeItems(items) {
  const seen = new Set();
  return items
    .filter((item) => item && item.url && !seen.has(item.url) && seen.add(item.url))
    .sort((a, b) => String(b.published || b.date || '').localeCompare(String(a.published || a.date || '')));
}

module.exports = async function handler(req, res) {
  const lang = req.query.lang === 'ko' ? 'ko' : 'en';
  const program = String(req.query.program || 'all');
  const config = lang === 'ko' ? koConfig : enConfig;
  const manual = (config.items || []).filter((item) => program === 'all' || item.program === program);

  try {
    let remote = [];
    if (program === 'all') {
      const playlists = Object.entries(config.programs || {}).filter(([, info]) => info.playlistId);
      if (playlists.length) {
        const groups = await Promise.all(playlists.map(([key, info]) =>
          fetchFeed(`https://www.youtube.com/feeds/videos.xml?playlist_id=${encodeURIComponent(info.playlistId)}`, key, info, lang)
        ));
        remote = groups.flat();
      } else if (config.channelId) {
        remote = await fetchFeed(
          `https://www.youtube.com/feeds/videos.xml?channel_id=${encodeURIComponent(config.channelId)}`,
          'all',
          null,
          lang
        );
      }
    } else {
      const info = (config.programs || {})[program];
      if (info?.playlistId) {
        remote = await fetchFeed(
          `https://www.youtube.com/feeds/videos.xml?playlist_id=${encodeURIComponent(info.playlistId)}`,
          program,
          info,
          lang
        );
      }
    }

    res.setHeader('Cache-Control', 's-maxage=900, stale-while-revalidate=3600');
    res.status(200).json({ items: mergeItems([...manual, ...remote]) });
  } catch (error) {
    res.setHeader('Cache-Control', 'no-store');
    res.status(200).json({ items: mergeItems(manual), warning: 'YouTube feed unavailable' });
  }
};