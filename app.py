# -*- coding: utf-8 -*-
from flask import Flask, jsonify, render_template_string
import requests, re, csv, io
from datetime import datetime
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DISTRICT_MAP = {
    "中西區": ["香港公園", "中環碼頭", "青洲", "山頂"],
    "灣仔": ["跑馬地"],
    "東區": ["筲箕灣", "北角"],
    "南區": ["黃竹坑", "赤柱", "香港航海學校"],
    "油尖旺": ["天文台", "京士柏", "天星碼頭"],
    "九龍城": ["九龍城", "啟德跑道公園", "啟德"],
    "觀塘": ["觀塘"],
    "深水埗": ["深水埗"],
    "黃大仙": ["黃大仙", "大老山"],
    "葵青": ["青衣"],
    "荃灣": ["荃灣可觀", "荃灣城門谷", "大帽山"],
    "屯門": ["屯門"],
    "元朗": ["元朗公園", "流浮山", "石崗", "濕地公園"],
    "北區": ["打鼓嶺", "上水"],
    "大埔": ["大埔", "大美督", "大埔滘"],
    "沙田": ["沙田"],
    "西貢": ["西貢", "清水灣", "將軍澳", "北潭涌", "滘西洲", "塔門"],
    "離島": ["長洲", "坪洲", "昂坪", "赤鱲角", "南丫島", "長洲泳灘", "橫瀾島"]
}

DISTRICT_CENTERS = {
    "中西區": (22.284, 114.155), "灣仔": (22.276, 114.183), "東區": (22.285, 114.225),
    "南區": (22.247, 114.160), "油尖旺": (22.305, 114.172), "九龍城": (22.328, 114.192),
    "觀塘": (22.313, 114.226), "深水埗": (22.330, 114.162), "黃大仙": (22.342, 114.198),
    "葵青": (22.357, 114.128), "荃灣": (22.372, 114.113), "屯門": (22.391, 113.977),
    "元朗": (22.443, 114.022), "北區": (22.496, 114.138), "大埔": (22.451, 114.171),
    "沙田": (22.382, 114.188), "西貢": (22.381, 114.270), "離島": (22.261, 113.946)
}

HEADERS = {"User-Agent": "Mozilla/5.0"}
TIMEOUT = 15

_cache = {"time": 0, "data": None}
CACHE_TTL = 600


def get_json(url):
    r = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
    r.encoding = "utf-8"
    return r.json()


def get_warnsum():
    return get_json("https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=warnsum&lang=tc")


def get_rhrread():
    return get_json("https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=rhrread&lang=tc")


def get_text_readings():
    r = requests.get("https://www.hko.gov.hk/textonly/v2/forecast/text_readings_v2_uc.htm",
                      timeout=TIMEOUT, headers=HEADERS)
    r.encoding = "utf-8"
    m = re.search(r"<pre id=\'ming\' >(.*?)</pre>", r.text, re.S)
    return m.group(1) if m else ""


def parse_text_readings(pre_text):
    lines = pre_text.split("\n")
    section = None
    temp_data, wind_data, pressure_data = {}, {}, {}
    name_re = r"^([\u4e00-\u9fff](?:\s{0,2}[\u4e00-\u9fff])*)\s{2,}(.+)$"

    for line in lines:
        s = line.rstrip()
        if not s.strip():
            continue
        st = s.strip()
        if "十分鐘平均風向" in st:
            section = "wind"; continue
        if "平均海平面氣壓" in st:
            section = "pressure"; continue
        if "十分鐘平均能見度" in st:
            section = "visibility"; continue
        if "太陽總輻射量" in st or "瓦特" in st:
            section = "solar"; continue
        if "「 N/A 」" in st or "此乃臨時數據" in st or "「 * 」" in st:
            section = None; continue
        if "氣溫" in st and "相對濕度" in st:
            section = None; continue
        if re.match(r"^\d{4}年", st):
            continue
        if "（攝氏）" in st or "午夜至現時" in st or "過去二十四小時" in st or "草溫" in st or "昨日下午" in st or "今日上午" in st:
            continue

        m = re.match(name_re, s)
        if not m:
            continue
        place = m.group(1).replace(" ", "")
        rest = m.group(2).strip()
        parts = re.split(r"\s+", rest)

        if section is None:
            if len(parts) >= 5 and parts[3] == "/":
                temp_data[place] = {
                    "temperature": parts[0], "humidity": parts[1],
                    "max_temp": parts[2], "min_temp": parts[4],
                    "temp_diff_24h": parts[5] if len(parts) > 5 else "N/A"
                }
        elif section == "wind":
            if len(parts) >= 3:
                wind_data[place] = {"direction": parts[0], "speed": parts[1], "gust": parts[2]}
        elif section == "pressure":
            if len(parts) >= 1:
                pressure_data[place] = parts[0]

    return temp_data, wind_data, pressure_data


def get_nowcast_by_district():
    try:
        r = requests.get(
            "https://data.weather.gov.hk/weatherAPI/hko_data/F3/Gridded_rainfall_nowcast_tc.csv",
            timeout=TIMEOUT, headers=HEADERS)
        r.encoding = "utf-8-sig"
        f = io.StringIO(r.text)
        reader = csv.reader(f)
        next(reader)
        rows = []
        for row in reader:
            try:
                lat, lon, rain = float(row[2]), float(row[3]), float(row[4])
            except (ValueError, IndexError):
                continue
            if 22.13 <= lat <= 22.58 and 113.83 <= lon <= 114.45:
                rows.append((lat, lon, rain))
        result = {}
        for dist, (dlat, dlon) in DISTRICT_CENTERS.items():
            if rows:
                best = min(rows, key=lambda r: (r[0] - dlat) ** 2 + (r[1] - dlon) ** 2)
                result[dist] = best[2]
            else:
                result[dist] = None
        return result
    except Exception as e:
        return {"error": str(e)}


def build_payload():
    try:
        rhr = get_rhrread()
    except Exception as e:
        rhr = {"error": str(e)}
    try:
        warn = get_warnsum()
    except Exception as e:
        warn = {"error": str(e)}
    try:
        pre = get_text_readings()
        temp_data, wind_data, pressure_data = parse_text_readings(pre)
    except Exception:
        temp_data, wind_data, pressure_data = {}, {}, {}

    nowcast = get_nowcast_by_district()

    districts = {}
    for dist, stations in DISTRICT_MAP.items():
        st_list = []
        for st in stations:
            entry = {"name": st}
            if st in temp_data:
                entry.update(temp_data[st])
            if st in wind_data:
                entry["wind"] = wind_data[st]
            if st in pressure_data:
                entry["pressure"] = pressure_data[st]
            st_list.append(entry)
        districts[dist] = st_list

    hourly_rain = rhr.get("rainfall", {}) if isinstance(rhr, dict) else {}
    rainfall_by_district = {item["place"]: item for item in hourly_rain.get("data", [])}

    return {
        "updateTime": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "warnings": warn,
        "rainfall_1hr_by_district": rainfall_by_district,
        "rainfall_period": {
            "start": hourly_rain.get("startTime"),
            "end": hourly_rain.get("endTime")
        },
        "nowcast_by_district": nowcast,
        "districts": districts
    }


@app.route("/api/weather")
def api_weather():
    now = datetime.now().timestamp()
    if _cache["data"] is None or (now - _cache["time"]) > CACHE_TTL:
        _cache["data"] = build_payload()
        _cache["time"] = now
    return jsonify(_cache["data"])


@app.route("/")
def index():
    with open("index.html", "r", encoding="utf-8") as f:
        return render_template_string(f.read())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)
