"""LLM 工具调用 - 网络搜索与音乐控制"""

import json
import re
from typing import Tuple, List

from PyQt5.QtCore import QSettings

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from duckduckgo_search import DDGS
    HAS_DDG = True
except ImportError:
    HAS_DDG = False

from ai.music_player import music_play, music_pause, music_next, music_stop

SETTINGS_ONLINE_SEARCH = "llm/online_search"
SETTINGS_ONLINE_MUSIC = "llm/online_music"

# 工具 JSON 正则（支持单行 JSON）
_TOOL_PATTERN = re.compile(
    r'\{\s*"tool"\s*:\s*"(web_search|music_play|music_pause|music_next|music_stop)"[^}]*\}',
    re.IGNORECASE,
)

# 用户意图正则（小模型未输出 JSON 时的补全）
_MUSIC_INTENT_PATTERNS = [
    re.compile(r"(?:播放|放一?首|来一?首|播一?首|我想听|帮我放|放一下)(.+)", re.I),
    re.compile(r"(?:听一?首)(.+?)(?:的歌|的音乐)?$", re.I),
]
_SEARCH_INTENT_PATTERNS = [
    re.compile(r"(?:搜索|查一下|查询|帮我查|联网查)(.+)", re.I),
    re.compile(r"(.+?)(?:天气怎么样|今天天气|最新消息|新闻)", re.I),
]
_MUSIC_CONTROL = {
    "暂停": "music_pause", "暂停播放": "music_pause", "继续播放": "music_pause",
    "停止播放": "music_stop", "停止音乐": "music_stop", "别放了": "music_stop",
    "下一首": "music_next", "切歌": "music_next", "换一首": "music_next",
}


def is_online_search_enabled() -> bool:
    return QSettings("BanBox", "BGAICard").value(SETTINGS_ONLINE_SEARCH, True, type=bool)


def is_online_music_enabled() -> bool:
    return QSettings("BanBox", "BGAICard").value(SETTINGS_ONLINE_MUSIC, True, type=bool)


class ToolExecutor:
    """解析并执行 LLM 输出的工具指令"""

    def extract_tool_calls(self, text: str) -> Tuple[str, List[dict]]:
        tools = []
        for match in _TOOL_PATTERN.finditer(text):
            try:
                tool_obj = json.loads(match.group(0))
                if "tool" in tool_obj:
                    tools.append(tool_obj)
            except json.JSONDecodeError:
                continue
        clean = _TOOL_PATTERN.sub("", text).strip()
        return clean, tools

    def detect_intent_from_user(self, user_text: str) -> List[dict]:
        """从用户原话推断工具意图（LLM 未输出 JSON 时补全）"""
        text = user_text.strip()
        if not text:
            return []

        # 音乐控制短指令
        if is_online_music_enabled():
            for phrase, tool_name in _MUSIC_CONTROL.items():
                if phrase in text:
                    return [{"tool": tool_name}]

        # 播放音乐
        if is_online_music_enabled():
            for pat in _MUSIC_INTENT_PATTERNS:
                m = pat.search(text)
                if m:
                    keyword = m.group(1).strip("吧了呢啊呀的 ")
                    if keyword and len(keyword) >= 2:
                        return [{"tool": "music_play", "keyword": keyword}]

        # 联网搜索
        if is_online_search_enabled():
            for pat in _SEARCH_INTENT_PATTERNS:
                m = pat.search(text)
                if m:
                    query = m.group(1).strip("吧了呢啊呀 ")
                    if query and len(query) >= 2:
                        return [{"tool": "web_search", "query": query}]

        return []

    def execute(self, tool_obj: dict) -> str:
        name = tool_obj.get("tool", "").lower()
        if name == "web_search":
            if not is_online_search_enabled():
                return "联网搜索已在设置中关闭"
            return web_search(tool_obj.get("query", ""))
        if name == "music_play":
            if not is_online_music_enabled():
                return "在线音乐已在设置中关闭"
            return music_play(tool_obj.get("keyword", "") or tool_obj.get("url", ""))
        if name == "music_pause":
            return music_pause()
        if name == "music_next":
            return music_next()
        if name == "music_stop":
            return music_stop()
        return f"未知工具: {name}"


def web_search(query: str) -> str:
    if not query.strip():
        return "搜索关键词为空"

    # 1. 天气查询专用（wttr.in，国内可用）
    if any(kw in query for kw in ["天气", "气温", "温度", "weather"]):
        try:
            import re as _re
            # 提取城市名
            city = _re.sub(r"(今天|明天|后天|当前|现在|的|天气|气温|温度|怎么样|如何|weather)", "", query).strip()
            if not city:
                city = "Beijing"
            # 城市名转拼音（wttr.in 不支持中文城市名 JSON 查询）
            city_pinyin = _city_to_pinyin(city)
            resp = requests.get(
                f"https://wttr.in/{city_pinyin}",
                params={"format": "j1"},
                headers={"User-Agent": "curl/7.68.0"},
                timeout=10,
                verify=False,
            )
            if resp.status_code == 200:
                data = resp.json()
                current = data.get("current_condition", [{}])[0]
                desc_en = current.get("weatherDesc", [{}])[0].get("value", "")
                desc = _translate_weather(desc_en)
                temp = current.get("temp_C", "?")
                humidity = current.get("humidity", "?")
                wind = current.get("windspeedKmph", "?")
                feels = current.get("FeelsLikeC", "?")
                # 未来预报
                forecast_lines = []
                for day in data.get("weather", [])[:2]:
                    date = day.get("date", "")
                    max_t = day.get("maxtempC", "?")
                    min_t = day.get("mintempC", "?")
                    day_desc_en = day.get("hourly", [{}])[4].get("weatherDesc", [{}])[0].get("value", "") if len(day.get("hourly", [])) > 4 else ""
                    forecast_lines.append(f"{date}: {_translate_weather(day_desc_en)}, {min_t}~{max_t}°C")
                result = f"{city}当前{desc}，气温{temp}°C（体感{feels}°C），湿度{humidity}%，风速{wind}km/h"
                if forecast_lines:
                    result += "\n预报：\n" + "\n".join(forecast_lines)
                return result
        except Exception as e:
            print(f"[Tools] 天气查询失败: {e}")

    # 2. 百度搜索（HTML 解析）
    if HAS_REQUESTS:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = requests.get(
                "https://www.baidu.com/s",
                params={"wd": query, "rn": "5"},
                headers=headers,
                timeout=8,
                verify=False,
            )
            if resp.status_code == 200:
                import re as _re
                text = resp.text
                snippets = []
                # 多种百度搜索结果 HTML 模式
                for m in _re.finditer(
                    r'<span class="content-right_[^"]*">(.*?)</span>|'
                    r'<div class="c-abstract[^"]*">(.*?)?</div>|'
                    r'<p class="content"[^>]*>(.*?)?</p>|'
                    r'<div class="c-span-last"[^>]*>.*?<span[^>]*>(.*?)?</span>',
                    text, _re.DOTALL
                ):
                    s = m.group(1) or m.group(2) or m.group(3) or m.group(4) or ""
                    s = _re.sub(r"<[^>]+>", "", s).strip()
                    if s and len(s) > 10:
                        snippets.append(s[:200])
                if snippets:
                    return "搜索结果：\n" + "\n".join(snippets[:3])
        except Exception as e:
            print(f"[Tools] 百度搜索失败: {e}")

    # 3. 必应国内版
    if HAS_REQUESTS:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = requests.get(
                "https://cn.bing.com/search",
                params={"q": query, "count": "5"},
                headers=headers,
                timeout=8,
                verify=False,
            )
            if resp.status_code == 200:
                import re as _re
                text = resp.text
                snippets = []
                for m in _re.finditer(
                    r'<p class="b_lineclamp[12][^"]*"[^>]*>(.*?)?</p>|'
                    r'<div class="b_caption"[^>]*>.*?<p[^>]*>(.*?)?</p>',
                    text, _re.DOTALL
                ):
                    s = m.group(1) or m.group(2) or ""
                    s = _re.sub(r"<[^>]+>", "", s).strip()
                    if s and len(s) > 10:
                        snippets.append(s[:200])
                if snippets:
                    return "搜索结果：\n" + "\n".join(snippets[:3])
        except Exception as e:
            print(f"[Tools] 必应搜索失败: {e}")

    # 4. 备用：DuckDuckGo
    if HAS_DDG:
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=3))
            if results:
                snippets = []
                for r in results[:3]:
                    title = r.get("title", "")
                    body = r.get("body", "")
                    snippets.append(f"{title}: {body[:150]}")
                return "搜索结果：\n" + "\n".join(snippets)
        except Exception as e:
            print(f"[Tools] DDG 搜索失败: {e}")

    return "无法完成网络搜索，请检查网络连接"


# ---- 天气辅助函数 ----

_WEATHER_ZH = {
    "sunny": "晴", "clear": "晴", "partly cloudy": "多云", "cloudy": "阴",
    "overcast": "阴天", "mist": "薄雾", "fog": "雾", "light rain": "小雨",
    "moderate rain": "中雨", "heavy rain": "大雨", "light rain shower": "小阵雨",
    "rain shower": "阵雨", "heavy rain shower": "大阵雨", "thunderstorm": "雷暴",
    "light snow": "小雪", "moderate snow": "中雪", "heavy snow": "大雪",
    "light snow shower": "小阵雪", "snow shower": "阵雪", "blizzard": "暴风雪",
    "hail": "冰雹", "sleet": "雨夹雪", "drizzle": "毛毛雨", "patchy rain": "零星小雨",
    "windy": "大风", "breeze": "微风", "humid": "潮湿", "dry": "干燥",
    "hot": "炎热", "cold": "寒冷", "freezing": "严寒",
}

_CITY_PINYIN = {
    "北京": "Beijing", "上海": "Shanghai", "广州": "Guangzhou", "深圳": "Shenzhen",
    "成都": "Chengdu", "杭州": "Hangzhou", "武汉": "Wuhan", "南京": "Nanjing",
    "重庆": "Chongqing", "天津": "Tianjin", "西安": "Xian", "苏州": "Suzhou",
    "长沙": "Changsha", "郑州": "Zhengzhou", "东莞": "Dongguan", "青岛": "Qingdao",
    "沈阳": "Shenyang", "宁波": "Ningbo", "昆明": "Kunming", "合肥": "Hefei",
    "福州": "Fuzhou", "厦门": "Xiamen", "哈尔滨": "Harbin", "济南": "Jinan",
    "大连": "Dalian", "长春": "Changchun", "太原": "Taiyuan", "贵阳": "Guiyang",
    "南宁": "Nanning", "南昌": "Nanchang", "石家庄": "Shijiazhuang", "兰州": "Lanzhou",
    "海口": "Haikou", "三亚": "Sanya", "拉萨": "Lhasa", "呼和浩特": "Hohhot",
    "乌鲁木齐": "Urumqi", "银川": "Yinchuan", "西宁": "Xining",
}


def _translate_weather(desc_en: str) -> str:
    """英文天气描述转中文"""
    if not desc_en:
        return "未知"
    desc_lower = desc_en.lower().strip()
    # 精确匹配
    if desc_lower in _WEATHER_ZH:
        return _WEATHER_ZH[desc_lower]
    # 模糊匹配（关键词）
    for en, zh in _WEATHER_ZH.items():
        if en in desc_lower:
            return zh
    return desc_en


def _city_to_pinyin(city: str) -> str:
    """中文城市名转拼音（wttr.in 需要）"""
    return _CITY_PINYIN.get(city, city)
