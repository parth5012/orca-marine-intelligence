"""
INCOIS TextData GeoJSON Daily Ingestion

Owner: M-B (Data Extractors & Storage) — INCOIS fetcher
Module: backend/ingest/incois_textdata.py

Parses INCOIS TextData HTML tables published daily (~11:30 IST) and
converts to unified GeoJSON FeatureCollection PFZ zones.
Supports sectors SEC001 through SEC014.
Falls back to local data/pfz-today.geojson or Copernicus Marine fallback
when INCOIS is offline or network fails.
"""

import asyncio
import json
import logging
import os
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from scripts.dms_to_decimal import dms_to_decimal

logger = logging.getLogger(__name__)

# Module-level circuit breaker state for INCOIS web scraper
_INCOIS_CIRCUIT_OPEN_UNTIL: float = 0.0
_CIRCUIT_COOLDOWN_SECONDS: float = 120.0

# Sector mappings for all 14 INCOIS coastal sectors
INCOIS_SECTORS: Dict[str, str] = {
    "SEC001": "GUJARAT",
    "SEC002": "MAHARASHTRA",
    "SEC003": "GOA",
    "SEC004": "KARNATAKA",
    "SEC005": "KERALA",
    "SEC006": "TAMILNADU_WEST",
    "SEC007": "TAMILNADU_EAST",
    "SEC008": "ANDHRA",
    "SEC009": "ODISHA",
    "SEC010": "WESTBENGAL",
    "SEC011": "ANDAMAN",
    "SEC012": "NICOBAR",
    "SEC013": "LAKSHADWEEP",
    "SEC014": "LAKSHADWEEP",
}

INCOIS_HOME_URL = "https://incois.gov.in/MarineFisheries/TextDataHome?mfid=1"
INCOIS_SECTOR_URL = "https://incois.gov.in/MarineFisheries/TextData?secid={sector}"


def _get_pfz_data_path() -> Path:
    """Resolve the path to data/pfz-today.geojson."""
    cwd_path = Path("data/pfz-today.geojson")
    if cwd_path.is_file():
        return cwd_path.resolve()
    repo_root = Path(__file__).resolve().parent.parent.parent
    data_path = repo_root / "data" / "pfz-today.geojson"
    return data_path


def load_local_pfz(sectors: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Load PFZ features from local data/pfz-today.geojson as fallback.
    """
    data_path = _get_pfz_data_path()
    if not data_path.is_file():
        # Also check pfz-all.json
        alt_path = data_path.parent / "pfz-all.json"
        if alt_path.is_file():
            data_path = alt_path
        else:
            logger.warning("Local PFZ data file not found at %s", data_path)
            return []

    try:
        with open(data_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        features: List[Dict[str, Any]] = []
        now_iso = datetime.now(timezone.utc).isoformat()

        if isinstance(raw, dict) and raw.get("type") == "FeatureCollection":
            features = raw.get("features", [])
        elif isinstance(raw, list):
            # Convert raw list of dicts to GeoJSON features
            for idx, item in enumerate(raw):
                lat = float(item.get("lat", 0.0))
                lon = float(item.get("lon", 0.0))
                feat = {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {
                        "place": item.get("place", f"Point_{idx}"),
                        "sector": item.get("sector", "SEC005"),
                        "sector_name": item.get("sector_name", "KERALA"),
                        "dir": item.get("dir", "W"),
                        "direction": item.get("dir", "W"),
                        "bearing": item.get("bearing", 270),
                        "distance": str(item.get("distance", "")),
                        "depth": str(item.get("depth", "")),
                        "lat_dms": item.get("lat_dms", ""),
                        "lon_dms": item.get("lon_dms", ""),
                        "suitability": "high",
                        "timestamp": now_iso,
                        "source": "incois_textdata",
                    },
                }
                features.append(feat)

        # Standardize properties
        norm_sector_set = {s.upper() for s in sectors} if sectors else None
        valid_features = []
        for feat in features:
            props = feat.setdefault("properties", {})
            feat_sec = str(props.get("sector", "")).upper()
            feat_sec_name = str(props.get("sector_name", "")).upper()
            if norm_sector_set and (feat_sec not in norm_sector_set and feat_sec_name not in norm_sector_set):
                continue
            safe_place = str(props.get("place", "zone")).replace(" ", "_")
            props.setdefault("zone_id", f"{feat_sec or 'SEC000'}_{safe_place}_{len(valid_features):03d}")
            props.setdefault("suitability", "high")
            props.setdefault("timestamp", now_iso)
            props.setdefault("source", "incois_textdata")
            if "dir" in props and "direction" not in props:
                props["direction"] = props["dir"]
            elif "direction" in props and "dir" not in props:
                props["dir"] = props["direction"]
            valid_features.append(feat)

        return valid_features
    except Exception as exc:
        logger.error("Failed loading local PFZ fallback from %s: %s", data_path, exc)
        return []


def parse_incois_table(content: str, sector: str, sector_name: str) -> List[Dict[str, Any]]:
    """
    Parse INCOIS HTML table or formatted text table rows into GeoJSON Point Features.
    Expected 7 columns: Place, Direction, Bearing, Depth, Distance, Lat (DMS), Lon (DMS).
    """
    features: List[Dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    if "<table" in content.lower() or "<tr" in content.lower():
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(content, "html.parser")
            tables = soup.find_all("table")
            for table in tables:
                for tr in table.find_all("tr"):
                    cells = tr.find_all(["td", "th"])
                    if len(cells) < 7:
                        continue
                    texts = [c.get_text(strip=True) for c in cells]
                    # Filter out header rows
                    col0_lower = texts[0].lower()
                    if any(h in col0_lower for h in ["landing", "place", "centre", "sl.", "s.no", "sector"]):
                        continue
                    if any(h in texts[5].lower() for h in ["lat", "deg", "coordinates"]):
                        continue

                    place, direction, bearing_raw, depth, distance, lat_dms, lon_dms = texts[:7]
                    lat = dms_to_decimal(lat_dms)
                    lon = dms_to_decimal(lon_dms)
                    if lat is None or lon is None:
                        continue

                    bearing = None
                    if bearing_raw:
                        m = re.search(r'\d+', bearing_raw)
                        if m:
                            bearing = int(m.group())

                        feat = {
                            "type": "Feature",
                            "geometry": {
                                "type": "Point",
                                "coordinates": [round(lon, 5), round(lat, 5)],
                            },
                            "properties": {
                                "place": place,
                                "sector": sector,
                                "sector_name": sector_name,
                                "dir": direction,
                                "direction": direction,
                                "bearing": bearing,
                                "distance": distance,
                                "depth": depth,
                                "lat_dms": lat_dms,
                                "lon_dms": lon_dms,
                                "suitability": "high",
                                "timestamp": now_iso,
                                "source": "incois_textdata",
                                "zone_id": f"{sector}_{place.replace(' ', '_')}_{len(features):03d}",
                            },
                        }
                    features.append(feat)
        except Exception as exc:
            logger.warning("Error parsing HTML table for sector %s: %s", sector, exc)
    else:
        # Plain text table / TSV parsing
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "\t" in line:
                parts = [p.strip() for p in line.split("\t")]
            elif "|" in line:
                parts = [p.strip() for p in line.split("|")]
            else:
                parts = [p.strip() for p in re.split(r'\s{2,}', line)]

            if len(parts) >= 7:
                col0_lower = parts[0].lower()
                if any(h in col0_lower for h in ["landing", "place", "centre", "sl.", "s.no", "sector"]):
                    continue
                place, direction, bearing_raw, depth, distance, lat_dms, lon_dms = parts[:7]
                lat = dms_to_decimal(lat_dms)
                lon = dms_to_decimal(lon_dms)
                if lat is None or lon is None:
                    continue

                bearing = None
                if bearing_raw:
                    m = re.search(r'\d+', bearing_raw)
                    if m:
                        bearing = int(m.group())

                feat = {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [round(lon, 5), round(lat, 5)],
                    },
                    "properties": {
                        "place": place,
                        "sector": sector,
                        "sector_name": sector_name,
                        "dir": direction,
                        "direction": direction,
                        "bearing": bearing,
                        "distance": distance,
                        "depth": depth,
                "lat_dms": lat_dms,
                "lon_dms": lon_dms,
                "suitability": "high",
                "timestamp": now_iso,
                "source": "incois_textdata",
                "zone_id": f"{sector}_{place.replace(' ', '_')}_{len(features):03d}",
            },
        }
        features.append(feat)

    return features


async def fetch_incois_sectors(
    sectors: Optional[List[str]] = None, session_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Fetch INCOIS TextData from government portal for given sectors (SEC001 to SEC014).
    If network fails, session expires, or portal is offline, loads latest local data/pfz-today.geojson.
    If local data is unavailable, falls back to Copernicus Marine fallback.
    """
    global _INCOIS_CIRCUIT_OPEN_UNTIL

    target_sectors = sectors or list(INCOIS_SECTORS.keys())
    features: List[Dict[str, Any]] = []

    # Fast-fail circuit breaker check
    now_ts = time.time()
    if now_ts < _INCOIS_CIRCUIT_OPEN_UNTIL:
        logger.info(
            "INCOIS circuit breaker is OPEN (cooldown %.1fs remaining); fast-failing to local GeoJSON",
            _INCOIS_CIRCUIT_OPEN_UNTIL - now_ts,
        )
        return load_local_pfz(sectors=target_sectors)

    # Attempt live web fetch from INCOIS
    try:
        import httpx

        sess = session_id or os.getenv("INCOIS_JSESSIONID")
        client_cookies = {"JSESSIONID": sess} if sess else {}

        async with httpx.AsyncClient(
            timeout=8.0, follow_redirects=True, cookies=client_cookies
        ) as client:
            # Probe home endpoint or initialize session cookie
            if not sess:
                try:
                    home_resp = await client.get(INCOIS_HOME_URL, timeout=2.5)
                    if home_resp.status_code >= 500:
                        logger.warning(
                            "INCOIS home probe returned status %d; tripping circuit breaker",
                            home_resp.status_code,
                        )
                        _INCOIS_CIRCUIT_OPEN_UNTIL = time.time() + _CIRCUIT_COOLDOWN_SECONDS
                        return load_local_pfz(sectors=target_sectors)
                    if "JSESSIONID" in home_resp.cookies:
                        client.cookies.set("JSESSIONID", home_resp.cookies["JSESSIONID"])
                except Exception as probe_err:
                    logger.debug("INCOIS home probe failed: %s", probe_err)

            # Concurrent sector scrape with aggregate SLA timeout (max 4.0s total)
            async def _fetch_sec(sec: str) -> List[Dict[str, Any]]:
                sec_name = INCOIS_SECTORS.get(sec, "COASTAL")
                url = INCOIS_SECTOR_URL.format(sector=sec)
                try:
                    resp = await client.get(url, timeout=3.0)
                    if resp.status_code == 200 and len(resp.text) > 100:
                        return parse_incois_table(resp.text, sec, sec_name)
                    elif resp.status_code >= 500:
                        return [{"__server_error__": resp.status_code}]
                except Exception as req_exc:
                    logger.debug("Failed fetching sector %s: %s", sec, req_exc)
                return []

            try:
                sector_tasks = [_fetch_sec(sec) for sec in target_sectors]
                results = await asyncio.wait_for(
                    asyncio.gather(*sector_tasks, return_exceptions=True),
                    timeout=4.0,
                )
                server_errors = 0
                for res in results:
                    if isinstance(res, list):
                        for item in res:
                            if "__server_error__" in item:
                                server_errors += 1
                            else:
                                features.append(item)
                # If multiple sectors returned 500/503, trip breaker for 120s
                if server_errors >= 2 and not features:
                    logger.warning(
                        "INCOIS returned %d server errors (500s); tripping circuit breaker for 120s",
                        server_errors,
                    )
                    _INCOIS_CIRCUIT_OPEN_UNTIL = time.time() + _CIRCUIT_COOLDOWN_SECONDS
            except asyncio.TimeoutError:
                logger.warning("INCOIS parallel sector fetch timed out (>4.0s); tripping circuit breaker for 120s")
                _INCOIS_CIRCUIT_OPEN_UNTIL = time.time() + _CIRCUIT_COOLDOWN_SECONDS
    except Exception as exc:
        logger.warning("Live INCOIS web scrape encounter error: %s", exc)
        _INCOIS_CIRCUIT_OPEN_UNTIL = time.time() + _CIRCUIT_COOLDOWN_SECONDS

    # If live fetch returned no features, load local data/pfz-today.geojson
    if not features:
        logger.info("INCOIS live scrape empty/offline; loading local data/pfz-today.geojson")
        features = load_local_pfz(sectors=target_sectors)

    # If still empty (e.g. fresh clone or missing file), invoke Copernicus Marine fallback
    if not features:
        logger.info("Primary INCOIS and local file empty; invoking Copernicus fallback")
        from backend.ingest.copernicus_fallback import fetch_copernicus_fallback

        cop_data = await fetch_copernicus_fallback()
        cop_feats = cop_data.get("features", [])
        if target_sectors:
            sec_set = set(target_sectors)
            cop_feats = [f for f in cop_feats if f.get("properties", {}).get("sector") in sec_set]
        features = cop_feats

    return features


# Persist-guard thresholds: a partial live scrape (portal sector rotation)
# must never clobber the good fallback file. Fresh data is persisted only
# when it carries >=3 sectors (or at least as many as the previous doc when
# that is smaller) and >=50% of the previous feature count.
_MIN_FRESH_SECTORS = 3
_MIN_FRESH_COUNT_FRACTION = 0.5


def _read_previous_doc() -> Optional[Dict[str, Any]]:
    """Best-effort raw read of the current fallback file (None when absent)."""
    try:
        prev_path = _get_pfz_data_path()
        if not prev_path.is_file():
            return None
        with open(prev_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict) and raw.get("features"):
            return raw
    except Exception as exc:
        logger.debug("Previous PFZ doc unreadable: %s", exc)
    return None


def _fresh_doc_passes_guard(
    features: List[Dict[str, Any]],
    sector_set: set,
    prev_doc: Optional[Dict[str, Any]],
) -> bool:
    """True when fresh features are safe to persist over the previous doc."""
    if not features or prev_doc is None:
        return bool(features)
    prev_features = prev_doc.get("features", []) or []
    prev_count = len(prev_features)
    prev_sectors = {
        f.get("properties", {}).get("sector")
        for f in prev_features
        if f.get("properties", {}).get("sector")
    }
    if not prev_count:
        return True
    min_sectors = min(_MIN_FRESH_SECTORS, len(prev_sectors) or _MIN_FRESH_SECTORS)
    if len(sector_set) < min_sectors:
        return False
    return len(features) >= _MIN_FRESH_COUNT_FRACTION * prev_count


async def ingest_textdata(
    session_id: Optional[str] = None,
    valid_date: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Fetch and parse INCOIS TextData into unified GeoJSON FeatureCollection.
    Writes data/pfz-today.geojson, upserts into PostGIS pfz_zones table if connected,
    and caches in Redis with 6h TTL.

    Args:
        session_id: Optional active INCOIS JSESSIONID cookie value.

    Returns:
        dict: GeoJSON FeatureCollection with properties and metadata.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    features = await fetch_incois_sectors(session_id=session_id)

    # Determine primary source
    source = "incois_textdata"
    if features and features[0].get("properties", {}).get("source") == "copernicus_fallback":
        source = "copernicus_fallback"

    sector_set = {
        f.get("properties", {}).get("sector")
        for f in features
        if f.get("properties", {}).get("sector")
    }

    # Rotation guard: retain the previous good doc when the fresh scrape is
    # a partial rotation (fewer sectors / collapsing count). Persisting it
    # would wipe Kerala etc. from the file, PostGIS, and cache at once.
    retained_previous = False
    prev_doc = _read_previous_doc()
    if not _fresh_doc_passes_guard(features, sector_set, prev_doc):
        prev_features = prev_doc.get("features", []) if prev_doc else []
        logger.warning(
            "Partial INCOIS rotation detected (%d features, %d sectors vs "
            "previous %d features) — retaining previous fallback file",
            len(features),
            len(sector_set),
            len(prev_features),
        )
        features = prev_features
        sector_set = {
            f.get("properties", {}).get("sector")
            for f in features
            if f.get("properties", {}).get("sector")
        }
        source = prev_doc.get("source", "incois_textdata") if prev_doc else source
        retained_previous = True

    geojson_doc: Dict[str, Any] = {
        "type": "FeatureCollection",
        "source": source,
        "timestamp": now_iso,
        "count": len(features),
        "sector_count": len(sector_set),
        "features": features,
        "artifacts": [],
    }

    # Track per-sink artifacts: only sinks that actually succeed are reported,
    # so cron/API envelopes never claim persistence that did not happen.
    artifacts: List[str] = []

    # 1. Write data/pfz-today.geojson (only if features non-empty AND fresh —
    #    a retained previous doc is already on disk, so rewriting it would
    #    only churn the timestamp; PostGIS keeps yesterday's rows too).
    if features and not retained_previous:
        out_path = _get_pfz_data_path()
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = out_path.with_name(f"{out_path.stem}.tmp_{os.getpid()}")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(geojson_doc, f, indent=2)
            os.replace(tmp_path, out_path)
            logger.info("Saved %d PFZ features to %s", len(features), out_path)
            artifacts.append("data/pfz-today.geojson")
        except Exception as io_err:
            logger.warning("Could not write %s: %s", out_path, io_err)

        # 2. Upsert to PostGIS if connected
        try:
            from backend.db.postgis import upsert_pfz_features

            upserted = await upsert_pfz_features(features, valid_date=valid_date)
            logger.info("Upserted %d PFZ zones to PostGIS database", upserted)
            artifacts.append("postgis:pfz_zones")
        except Exception as db_err:
            logger.debug("PostGIS upsert skipped (offline/disconnected): %s", db_err)

    # 3. Cache in Redis (6-hour TTL for today, 7-day TTL for history sliding window)
    try:
        from backend.db.redis import set_json

        await set_json("pfz:today", geojson_doc, ttl_seconds=21600)
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        await set_json(f"pfz:history:{today_str}", geojson_doc, ttl_seconds=604800)
        artifacts.append("redis:pfz:today")
    except Exception as redis_err:
        logger.debug("Redis cache set skipped: %s", redis_err)

    geojson_doc["artifacts"] = artifacts
    if retained_previous:
        geojson_doc["retained_previous"] = True

    # Re-persist the final document so stored payloads carry the completed
    # artifact list (both were serialized above while it was still empty).
    # Best-effort: never fail the run on rewrite. The file rewrite stays
    # gated on fresh features (never persist an empty file over yesterday's
    # data, and never rewrite a retained doc); Redis refreshes whenever it
    # persisted, even for empty feature sets.
    if artifacts and not retained_previous:
        if features:
            try:
                with open(_get_pfz_data_path(), "w", encoding="utf-8") as f:
                    json.dump(geojson_doc, f, indent=2)
            except Exception as rewrite_err:
                logger.debug("Final GeoJSON rewrite skipped: %s", rewrite_err)
        try:
            from backend.db.redis import set_json as _refresh_json

            await _refresh_json("pfz:today", geojson_doc, ttl_seconds=21600)
        except Exception as refresh_err:
            logger.debug("Final Redis refresh skipped: %s", refresh_err)

    return geojson_doc
