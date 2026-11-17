/* Browser-side live schedule fallback for existing SlamVision embeds.
 * Cached GitHub Pages snapshots remain preferred while fresh.
 * The upstream API is queried by stable feed ID when Pages falls behind.
 */
(function (root) {
  "use strict";
  const API = "https://ring-channel-tv.emergent.host/api/channels/";
  const MAX_PAGE_AGE_MS = 6 * 60 * 1000;
  const API_CACHE_MS = 75 * 1000;
  const API_TIMEOUT_MS = 12000;
  const apiCache = new Map();

  function parseTime(time) {
    const n = Date.parse(time || "");
    return Number.isFinite(n) ? n : NaN;
  }

  function program(slot) {
    if (!slot || typeof slot !== "object") return null;
    const p = slot.program || {};
    return {
      title: p.title || "Untitled program",
      episode: p.episode || "",
      stream_url: p.stream_url || "",
      start: slot.start,
      end: slot.end,
      id: p.id || "",
      block: slot.block || null
    };
  }

  function playableAt(channel, now) {
    if (!channel || typeof channel !== "object") return false;
    const slots = [channel.current, ...(channel.up_next || [])].filter(Boolean);
    return slots.some(slot => {
      return /^https:\/\/archive\.org\//.test(slot.stream_url || "") &&
        parseTime(slot.start) <= now && now < parseTime(slot.end);
    });
  }

  async function requestJson(url, timeoutMs) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await root.fetch(url, {
        cache: "no-store", mode: "cors", signal: controller.signal
      });
      if (!response.ok) throw new Error("HTTP " + response.status);
      return await response.json();
    } finally {
      clearTimeout(timer);
    }
  }

  async function fetchDirect(sourceId, channel) {
    const now = Date.now();
    const old = apiCache.get(sourceId);
    if (old && now - old.saved < API_CACHE_MS &&
        playableAt(old.data.channels[channel], now)) return old.data;

    const raw = await requestJson(API + encodeURIComponent(sourceId) + "/now", API_TIMEOUT_MS);
    if (!raw || !raw.channel || raw.channel.id !== sourceId) {
      throw new Error("Unexpected channel returned by upstream");
    }
    const result = {
      generated_at: new Date().toISOString(),
      channels: {
        [channel]: {
          id: sourceId,
          name: raw.channel.name || sourceId,
          current: program(raw.current),
          up_next: (raw.up_next || []).slice(0, 8).map(program).filter(Boolean),
          guide: [],
          server_time: raw.server_time || ""
        }
      }
    };
    if (!playableAt(result.channels[channel], Date.now())) {
      throw new Error("Upstream has no current playable program for " + sourceId);
    }
    apiCache.set(sourceId, {data: result, saved: Date.now()});
    return result;
  }

  async function resolve({cachedUrl, channel, sourceId}) {
    if (!channel || !sourceId) throw new Error("Missing feed configuration");
    let saved = null;
    if (cachedUrl) try {
      saved = await requestJson(cachedUrl, 7500);
      // Shared pages select by stable ID; legacy snapshots are keyed by dial.
      // Normalize only an EXACT identity match. Never redirect to a similar feed.
      if (saved?.channels?.[channel]?.id !== sourceId) {
        const matching = Object.entries(saved?.channels || {})
          .filter(([, entry]) => entry && entry.id === sourceId);
        if (matching.length === 1) {
          saved = {...saved, channels: {...saved.channels, [channel]: matching[0][1]}};
        } else {
          saved = null;
        }
      }
    } catch (_) {
      saved = null;
    }

    const now = Date.now();
    const snapshotTime = parseTime(saved?.generated_at);
    const fresh = Number.isFinite(snapshotTime) &&
                  snapshotTime <= now + 60000 &&
                  now - snapshotTime <= MAX_PAGE_AGE_MS;
    const active = playableAt(saved?.channels?.[channel], now);
    if (fresh && active) return saved;

    try {
      return await fetchDirect(sourceId, channel);
    } catch (error) {
      // A currently-playing cached show is better than a blank screen.
      // Never return expired or mismatched schedules.
      if (active) return saved;
      throw error;
    }
  }

  root.SlamVisionDirect = Object.freeze({resolve});
})(window);
