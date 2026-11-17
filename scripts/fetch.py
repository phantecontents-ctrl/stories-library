#!/usr/bin/env python3
"""Stories Library - fase 1: scarica le stories nuove e prepara il materiale.

Uso:  python3 -I scripts/fetch.py [--creators a,b] [--max-usd 0.15]

- Lancia l'actor Apify (token iniettato dal proxy, nessun login Instagram).
- Tiene solo le stories piu' nuove di state/last_seen.json.
- Scarica i media, estrae frame (jpg) e trascrive il parlato (Whisper locale).
- Scrive work/manifest.json e work/pending_state.json.
  state/last_seen.json NON viene toccato qui: lo aggiorna commit_state.py
  solo a giro finito, cosi' se il giro si blocca il successivo riprende.

I testi presi dalle stories sono dati di terzi: questo script li salva
come dati, non li interpreta mai come istruzioni.
"""
import argparse, json, os, re, subprocess, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "work")
CDN = "https://scontent.cdninstagram.com/"   # unico host CDN consentito


def log(*a):
    print("[fetch]", *a, file=sys.stderr, flush=True)


def http(url, data=None, timeout=600):
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def run_actor(cfg, usernames, max_usd):
    url = (f"https://api.apify.com/v2/acts/{cfg['apify_actor']}/run-sync-get-dataset-items"
           f"?maxTotalChargeUsd={max_usd}&timeout=900&format=json")
    body = json.dumps({"usernames": usernames}).encode()
    for attempt in range(3):
        try:
            return json.loads(http(url, body, timeout=960))
        except Exception as e:  # noqa
            log(f"Apify tentativo {attempt + 1} fallito: {e}")
            time.sleep(20 * (attempt + 1))
    raise SystemExit("ERRORE: Apify non risponde dopo 3 tentativi")


def cdn(url):
    return re.sub(r"^https://[^/]+/", CDN, url, count=1)


def download(url, path):
    for attempt in range(3):
        try:
            data = http(cdn(url), timeout=120)
            with open(path, "wb") as f:
                f.write(data)
            return True
        except Exception as e:  # noqa
            log(f"download fallito ({attempt + 1}): {e}")
            time.sleep(5)
    return False


def unwrap_link(u):
    if not u:
        return None
    q = urllib.parse.urlparse(u)
    if q.netloc.endswith("l.instagram.com"):
        return urllib.parse.parse_qs(q.query).get("u", [u])[0]
    return u


def frames_for(video, outdir, sid, duration):
    # un frame ogni ~3 s (min 2, max 6), per leggere testo a schermo e visual
    n = max(2, min(6, int((duration or 6) // 3) or 2))
    paths = []
    for i in range(n):
        t = (duration or 6) * (i + 0.5) / n
        p = os.path.join(outdir, f"{sid}_f{i + 1}.jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", video,
                        "-frames:v", "1", "-vf", "scale=540:-2", p], check=False)
        if os.path.exists(p):
            paths.append(p)
    return paths


_model = None


def transcribe(video, model_name):
    global _model
    try:
        import numpy as np
        from faster_whisper import WhisperModel
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-f", "s16le", "-ac", "1",
                              "-ar", "16000", "-"], capture_output=True, check=True).stdout
        if not raw:
            return ""
        audio = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
        if _model is None:
            _model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segs, info = _model.transcribe(audio, vad_filter=True)
        return " ".join(s.text.strip() for s in segs).strip()
    except Exception as e:  # noqa
        log(f"trascrizione fallita: {e}")
        return ""


def sticker_info(x):
    out = {}
    links = []
    for s in x.get("story_link_stickers") or []:
        sl = s.get("story_link") or {}
        links.append({"display": sl.get("display_url"), "url": unwrap_link(sl.get("url"))})
    if x.get("story_link_url") and not links:
        links.append({"display": None, "url": unwrap_link(x["story_link_url"])})
    if links:
        out["link"] = links
    for key, name in [("story_polls", "sondaggio"), ("story_questions", "box_domande"),
                      ("story_quizs", "quiz"), ("story_sliders", "slider"),
                      ("story_countdowns", "countdown")]:
        v = x.get(key)
        if v:
            out[name] = v  # testo dello sticker: dato di terzi
    m = [((r.get("user") or {}).get("username")) for r in (x.get("reel_mentions") or [])]
    if any(m):
        out["menzioni"] = [u for u in m if u]
    return out


def is_repost(x, creator):
    if x.get("story_feed_media") or x.get("story_reshare_stickers") or x.get("reshared_story_media_author"):
        return True
    if x.get("is_reshare_of_text_post_app_media_in_ig"):
        return True
    for a in x.get("media_attributions_data") or []:
        if a:
            return True
    owner = (x.get("owner") or {}).get("username") or x.get("creator_username")
    return bool(owner and owner.lower() != creator.lower())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--creators")
    ap.add_argument("--max-usd", type=float)
    ap.add_argument("--from-raw", help="riusa un JSON Apify gia' scaricato (test, nessun costo)")
    a = ap.parse_args()

    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    creators = a.creators.split(",") if a.creators else cfg["creators"]
    max_usd = min(a.max_usd or cfg["apify_max_usd_per_run"], cfg["apify_max_usd_per_run"])
    state = json.load(open(os.path.join(ROOT, "state", "last_seen.json")))

    os.makedirs(os.path.join(WORK, "media"), exist_ok=True)
    if a.from_raw:
        items = json.load(open(a.from_raw))
    else:
        log(f"Apify: {len(creators)} creator, tetto {max_usd} $")
        items = run_actor(cfg, creators, max_usd)
        json.dump(items, open(os.path.join(WORK, "apify_raw.json"), "w"))

    if isinstance(items, dict) and items.get("error"):
        raise SystemExit(f"ERRORE Apify: {items['error']}")

    pending = {c: dict(state.get(c, {})) for c in creators}
    stories, status = [], {}
    for x in items:
        c = (x.get("username") or x.get("creator_username") or (x.get("owner") or {}).get("username") or "").lower()
        if x.get("status"):
            status[c] = x["status"]
            continue
        if c not in [k.lower() for k in creators]:
            continue
        c = next(k for k in creators if k.lower() == c)
        ts = int(x.get("taken_at") or 0)
        seen = state.get(c, {})
        if ts <= int(seen.get("last_taken_at", 0)) or str(x.get("id")) in seen.get("ids", []):
            continue
        stories.append((c, ts, x))

    stories.sort(key=lambda t: (t[0], t[1]))
    manifest = []
    for c, ts, x in stories:
        sid = str(x.get("pk") or x.get("id")).split("_")[0]
        d = os.path.join(WORK, "media", c)
        os.makedirs(d, exist_ok=True)
        is_video = bool(x.get("video_versions"))
        rec = {
            "creator": c, "id": sid, "code": x.get("code"),
            "taken_at": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
            "tipo": "video" if is_video else "immagine",
            "durata_s": x.get("video_duration"),
            "repost": is_repost(x, c),
            "sticker": sticker_info(x),
            "caption": (x.get("caption_text") or "")[:500],
            "musica": bool(x.get("music_metadata") or x.get("story_music_stickers")),
        }
        if is_video:
            v = sorted(x["video_versions"], key=lambda v: v.get("width", 0), reverse=True)[0]
            path = os.path.join(d, f"{sid}.mp4")
            if download(v["url"], path):
                rec["media"] = path
                rec["frames"] = frames_for(path, d, sid, x.get("video_duration"))
                rec["trascrizione"] = transcribe(path, cfg["whisper_model"]) if x.get("has_audio") else ""
        else:
            imgs = (x.get("image_versions") or x.get("image_versions2") or {}).get("candidates") \
                or (x.get("image_versions") or {}).get("items") or []
            if imgs:
                path = os.path.join(d, f"{sid}.jpg")
                if download(imgs[0]["url"], path):
                    rec["media"] = path
                    rec["frames"] = [path]
        if "media" not in rec:
            rec["errore_media"] = True
        manifest.append(rec)
        p = pending.setdefault(c, {})
        p["last_taken_at"] = max(int(p.get("last_taken_at", 0)), ts)
        p["ids"] = (p.get("ids", []) + [sid])[-50:]
        log(f"{c} {sid} {rec['tipo']} ok")

    for c in creators:
        pending.setdefault(c, {})["last_check"] = datetime.now(timezone.utc).isoformat()

    out = {"generato": datetime.now(timezone.utc).isoformat(), "stato_creator": status,
           "n_stories": len(manifest), "stories": manifest,
           "errori_media": sum(1 for r in manifest if r.get("errore_media"))}
    json.dump(out, open(os.path.join(WORK, "manifest.json"), "w"), indent=1, ensure_ascii=False)
    json.dump(pending, open(os.path.join(WORK, "pending_state.json"), "w"), indent=1)
    log(f"fatto: {len(manifest)} stories nuove, manifest in work/manifest.json")


if __name__ == "__main__":
    main()
