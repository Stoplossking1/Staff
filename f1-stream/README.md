# f1-stream

Minimal replay stream source for vision agents.

## Local startup

```bash
cd f1-stream
npm ci
npm run stream
```

Stable local URL:

- `http://127.0.0.1:4173/`

Direct media URL:

- `http://127.0.0.1:4173/lando.mp4`

## Playback contract

The stream surface intentionally renders only one real replay video (`lando.mp4`) with no synthetic HUD overlays.

The `<video>` element is configured with:

- `autoPlay`
- `muted`
- `loop`
- `playsInline`
- `preload="auto"`

## Stability notes

- `lando.mp4` is served from `public/lando.mp4` so it is available in both dev and preview modes.
- The player retries `play()` on `canplay`, on periodic health checks, and after stalled events.
- A fixed host/port (`127.0.0.1:4173`) is provided by `npm run stream` for a stable agent-facing endpoint.

## Optional preview mode

```bash
cd f1-stream
npm ci
npm run build
npm run stream:preview
```
