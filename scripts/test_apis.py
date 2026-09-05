import os
import sys
import json
import urllib.request
import urllib.error
import urllib.parse
from dotenv import load_dotenv

load_dotenv(override=True)

headers_ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
results = {}

# 1. Google Gemini API
google_key = os.getenv("GOOGLE_API_KEY", "").strip()
if not google_key:
    results["Google Gemini"] = {"status": "MISSING", "detail": "GOOGLE_API_KEY not set"}
else:
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={google_key}"
        req = urllib.request.Request(url, headers=headers_ua)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            gemini_models = [m.get("name").replace("models/", "") for m in data.get("models", []) if "gemini" in m.get("name", "")]
            results["Google Gemini"] = {
                "status": "SUCCESS",
                "detail": f"Active & authenticated. Accessible models: {len(gemini_models)} (e.g. {', '.join(gemini_models[:3])})"
            }
    except urllib.error.HTTPError as e:
        results["Google Gemini"] = {"status": "FAILED", "detail": f"HTTP {e.code}: {e.read().decode(errors='ignore')[:150]}"}
    except Exception as e:
        results["Google Gemini"] = {"status": "FAILED", "detail": str(e)}

# 2. Groq API
groq_key = os.getenv("GROQ_API_KEY", "").strip()
if not groq_key:
    results["Groq"] = {"status": "MISSING", "detail": "GROQ_API_KEY not set"}
else:
    try:
        url = "https://api.groq.com/openai/v1/models"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {groq_key}", **headers_ua})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            models = [m.get("id") for m in data.get("data", [])]
            results["Groq"] = {
                "status": "SUCCESS",
                "detail": f"Active & authenticated. Accessible models: {len(models)} (e.g. {', '.join(models[:3])})"
            }
    except urllib.error.HTTPError as e:
        results["Groq"] = {"status": "FAILED", "detail": f"HTTP {e.code}: {e.read().decode(errors='ignore')[:150]}"}
    except Exception as e:
        results["Groq"] = {"status": "FAILED", "detail": str(e)}

# 3. Weather API (OpenWeatherMap vs WeatherAPI.com)
weather_key = os.getenv("OPENWEATHER_API_KEY", "").strip()
if not weather_key:
    results["Weather API"] = {"status": "MISSING", "detail": "OPENWEATHER_API_KEY not set"}
else:
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q=Kochi,IN&appid={weather_key}&units=metric"
        req = urllib.request.Request(url, headers=headers_ua)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            results["Weather (OpenWeatherMap)"] = {
                "status": "SUCCESS",
                "detail": f"Active. Current Kochi, IN: {data.get('main', {}).get('temp')}°C, {data.get('weather', [{}])[0].get('description')}, Wind: {data.get('wind', {}).get('speed')} m/s"
            }
    except urllib.error.HTTPError as e:
        results["Weather API"] = {"status": "FAILED", "detail": f"HTTP {e.code}: {e.read().decode(errors='ignore')[:150]}"}
    except Exception as e:
        results["Weather API"] = {"status": "FAILED", "detail": str(e)}

# 4. NASA Earthdata Token
earthdata_token = os.getenv("EARTHDATA_TOKEN", "").strip()
if not earthdata_token:
    results["NASA Earthdata"] = {"status": "MISSING", "detail": "EARTHDATA_TOKEN not set"}
else:
    try:
        url = "https://cmr.earthdata.nasa.gov/search/collections.json?keyword=MODIS&page_size=1"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {earthdata_token}", **headers_ua})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            hits = data.get("feed", {}).get("hits", 0)
            results["NASA Earthdata"] = {
                "status": "SUCCESS",
                "detail": f"Active & authenticated. CMR search returned {hits:,} satellite collections."
            }
    except urllib.error.HTTPError as e:
        results["NASA Earthdata"] = {"status": "FAILED", "detail": f"HTTP {e.code}: {e.read().decode(errors='ignore')[:150]}"}
    except Exception as e:
        results["NASA Earthdata"] = {"status": "FAILED", "detail": str(e)}

# 5. Copernicus Marine (CMEMS CAS / Keycloak)
cop_user = os.getenv("COPERNICUS_USER", "").strip()
cop_pwd = os.getenv("COPERNICUS_PASSWORD", "").strip()

if not cop_user or not cop_pwd:
    results["Copernicus Marine"] = {"status": "MISSING", "detail": "COPERNICUS_USER or COPERNICUS_PASSWORD not set"}
else:
    try:
        token_url = "https://auth.marine.copernicus.eu/realms/MIS/protocol/openid-connect/token"
        data = urllib.parse.urlencode({
            "client_id": "toolbox",
            "scope": "openid profile email",
            "grant_type": "password",
            "username": cop_user,
            "password": cop_pwd
        }).encode("utf-8")
        req = urllib.request.Request(token_url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded", **headers_ua})
        with urllib.request.urlopen(req, timeout=10) as resp:
            res = json.loads(resp.read().decode())
            access_token = res.get("access_token", "")
            # fetch user info
            u_req = urllib.request.Request(
                "https://auth.marine.copernicus.eu/realms/MIS/protocol/openid-connect/userinfo",
                headers={"Authorization": f"Bearer {access_token}", **headers_ua}
            )
            with urllib.request.urlopen(u_req, timeout=10) as u_resp:
                u_info = json.loads(u_resp.read().decode())
                username_out = u_info.get("preferred_username", cop_user)
                results["Copernicus Marine"] = {
                    "status": "SUCCESS",
                    "detail": f"Active & authenticated as '{username_out}'. Token acquired (expires in {res.get('expires_in')}s)."
                }
    except urllib.error.HTTPError as e:
        results["Copernicus Marine"] = {"status": "FAILED", "detail": f"HTTP {e.code}: {e.read().decode(errors='ignore')[:150]}"}
    except Exception as e:
        results["Copernicus Marine"] = {"status": "FAILED", "detail": str(e)}

print("\n================ API VERIFICATION REPORT ================\n")
for name, info in results.items():
    icon = "[PASS]" if info["status"] == "SUCCESS" else "[FAIL]"
    print(f"{icon} {name}: {info['status']}")
    print(f"       {info['detail']}\n")
print("=========================================================\n")
