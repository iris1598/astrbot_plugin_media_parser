"core.parser.platform.xiaohongshu 模块。"
import asyncio
import json
import re
from datetime import datetime
from typing import Optional, Dict, Any, List
from urllib.parse import unquote, urlparse, parse_qs, urlencode, urlunparse

import aiohttp

from ...logger import logger

from .base import BaseVideoParser
from ..utils import build_request_headers, is_live_url, SkipParse
from ...constants import Config


ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/142.0.0.0 Mobile Safari/537.36 Edg/142.0.0.0"
)

PC_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/142.0.0.0 Safari/537.36 Edg/142.0.0.0"
)


class XiaohongshuParser(BaseVideoParser):

    "XiaohongshuParser 类。"
    def __init__(self, hot_comment_count: int = 0, use_cookie: bool = False, cookie: str = ""):
        """初始化小红书解析器

        Args:
            hot_comment_count: 热评数量
            use_cookie: 是否使用Cookie
            cookie: 小红书Cookie
        """
        super().__init__("xiaohongshu")
        self.headers = {
            "User-Agent": ANDROID_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "gzip, deflate",
        }
        self.semaphore = asyncio.Semaphore(Config.PARSER_MAX_CONCURRENT)
        try:
            self.hot_comment_count = max(0, int(hot_comment_count))
        except (TypeError, ValueError):
            self.hot_comment_count = 0
        self.use_cookie = bool(use_cookie)
        self.cookie = str(cookie or "").strip()

    def can_parse(self, url: str) -> bool:
        """判断是否可以解析此URL
        
        Args:
            url: 视频链接
            
        Returns:
            是否可以解析
        """
        if not url:
            return False
        url_lower = url.lower()
        if 'xhslink.com' in url_lower or 'xiaohongshu.com' in url_lower:
            return True
        return False

    def extract_links(self, text: str) -> List[str]:
        """从文本中提取小红书链接
        
        Args:
            text: 输入文本
            
        Returns:
            小红书链接列表
        """
        result_links_set = set()
        seen_urls = set()
        
        short_pattern = r'https?://xhslink\.com/[^\s<>"\'()]+'
        short_links = re.findall(short_pattern, text, re.IGNORECASE)
        for link in short_links:
            normalized = link.lower()
            if normalized not in seen_urls:
                seen_urls.add(normalized)
                result_links_set.add(link)
        
        long_pattern = (
            r'https?://(?:www\.)?xiaohongshu\.com/'
            r'(?:explore|discovery/item)/[^\s<>"\'()]+'
        )
        long_links = re.findall(long_pattern, text, re.IGNORECASE)
        for link in long_links:
            normalized = link.lower()
            if normalized not in seen_urls:
                seen_urls.add(normalized)
                result_links_set.add(link)
        
        result = list(result_links_set)
        if result:
            logger.debug(f"[{self.name}] extract_links: 提取到 {len(result)} 个链接: {result[:3]}{'...' if len(result) > 3 else ''}")
        else:
            logger.debug(f"[{self.name}] extract_links: 未提取到链接")
        return result

    def _is_pc_url(self, url: str) -> bool:
        """检测是否为PC端链接
        
        Args:
            url: 链接URL
            
        Returns:
            是否为PC端链接
        """
        url_lower = url.lower()
        return (
            '/explore/' in url_lower or
            'xsec_source=pc' in url_lower
        )

    def _clean_share_url(self, url: str) -> str:
        """清理分享长链URL，删除source和xhsshare参数
        
        注意：PC端链接（包含/explore/或xsec_token）不删除参数，保留xsec_token等
        
        Args:
            url: 原始URL
            
        Returns:
            清理后的URL
        """
        if self._is_pc_url(url):
            return url

        if "discovery/item" not in url:
            return url

        parsed = urlparse(url)
        query_params = parse_qs(parsed.query, keep_blank_values=True)
        query_params.pop('source', None)
        query_params.pop('xhsshare', None)

        flat_params = {}
        for key, value_list in query_params.items():
            flat_params[key] = value_list[0] if value_list and value_list[0] else ''

        new_query = urlencode(flat_params)
        new_parsed = parsed._replace(query=new_query)
        return urlunparse(new_parsed)

    async def _get_redirect_url(
        self,
        session: aiohttp.ClientSession,
        short_url: str
    ) -> str:
        """获取短链接重定向后的完整URL
        
        Args:
            session: aiohttp会话
            short_url: 短链接URL
            
        Returns:
            重定向后的完整URL
            
        Raises:
            RuntimeError: 当无法获取重定向URL时
        """
        async with session.get(
            short_url,
            headers=self.headers,
            allow_redirects=False
        ) as response:
            if response.status == 302:
                redirect_url = response.headers.get("Location", "")
                if not redirect_url:
                    raise RuntimeError("无法获取重定向URL")
                return unquote(redirect_url)
            else:
                raise RuntimeError(
                    f"无法获取重定向URL，状态码: {response.status}"
                )

    def _get_headers_for_url(self, url: str) -> dict:
        """根据URL类型获取对应的请求头

        Args:
            url: 页面URL

        Returns:
            请求头字典
        """
        headers = {
            "User-Agent": PC_UA if self._is_pc_url(url) else ANDROID_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "gzip, deflate",
        }
        if self._is_pc_url(url):
            headers["Sec-CH-UA-Mobile"] = "?0"
            headers["Sec-CH-UA-Platform"] = '"Windows"'
        if self.use_cookie and self.cookie:
            headers["Cookie"] = self.cookie
        return headers

    async def _fetch_page_with_cookie_api(
        self,
        session: aiohttp.ClientSession,
        note_id: str,
        xsec_source: str = "pc_feed",
        xsec_token: str = ""
    ) -> Optional[Dict[str, Any]]:
        """使用Cookie API方式获取笔记数据（需要登录）

        Args:
            session: aiohttp会话
            note_id: 笔记ID
            xsec_source: 来源标识
            xsec_token: 安全令牌

        Returns:
            笔记数据字典，失败时返回None
        """
        if not self.use_cookie or not self.cookie:
            return None

        api_url = f"https://www.xiaohongshu.com/explore/{note_id}"
        headers = {
            "User-Agent": PC_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Cookie": self.cookie,
            "Referer": "https://www.xiaohongshu.com/",
        }

        try:
            async with session.get(api_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status != 200:
                    logger.debug(f"[{self.name}] Cookie API请求失败，状态码: {response.status}")
                    return None
                html = await response.text()

            # 提取 __INITIAL_STATE__
            pattern = r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>'
            match = re.search(pattern, html, re.DOTALL)
            if match:
                json_str = match.group(1)
                json_str = re.sub(r'\bundefined\b', 'null', json_str)
                try:
                    data = json.loads(json_str)
                    note_data = (
                        (data.get("note") or {}).get("noteDetailMap", {}).get(note_id, {}).get("note")
                    )
                    if note_data:
                        return note_data
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            logger.debug(f"[{self.name}] Cookie API请求异常: {e}")

        return None

    def _extract_no_watermark_video_url(self, note_data: dict) -> str:
        """提取无水印视频URL

        从note_data中提取无水印视频URL。
        小红书无水印视频URL格式：https://sns-video-bd.xhscdn.com/{originVideoKey}

        Args:
            note_data: 笔记数据字典

        Returns:
            无水印视频URL，如果无法提取则返回空字符串
        """
        try:
            video_info = note_data.get("video", {})
            if not video_info:
                return ""

            # 优先尝试无水印URL：consumer.originVideoKey
            consumer = video_info.get("consumer", {})
            origin_video_key = consumer.get("originVideoKey", "")
            if origin_video_key:
                no_watermark_url = f"https://sns-video-bd.xhscdn.com/{origin_video_key}"
                logger.debug(f"[{self.name}] 获取到无水印视频URL: {no_watermark_url[:80]}...")
                return no_watermark_url

            # 备用：media.stream.h264.masterUrl（可能有水印）
            media = video_info.get("media", {})
            stream = media.get("stream", {})
            h264 = stream.get("h264", [])
            if h264 and isinstance(h264, list) and len(h264) > 0:
                master_url = h264[0].get("masterUrl", "")
                if master_url:
                    logger.debug(f"[{self.name}] 使用备用视频URL（可能有水印）")
                    return master_url

            return ""
        except Exception as e:
            logger.debug(f"[{self.name}] 提取无水印视频URL失败: {e}")
            return ""

    async def _fetch_page(
        self,
        session: aiohttp.ClientSession,
        url: str
    ) -> str:
        """获取页面HTML内容
        
        Args:
            session: aiohttp会话
            url: 页面URL
            
        Returns:
            HTML内容
            
        Raises:
            RuntimeError: 当无法获取页面内容时
        """
        headers = self._get_headers_for_url(url)
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                return await response.text()
            else:
                raise RuntimeError(
                    f"无法获取页面内容，状态码: {response.status}"
                )

    def _extract_initial_state(self, html: str) -> dict:
        """从HTML中提取window.__INITIAL_STATE__的JSON数据
        
        Args:
            html: HTML内容
            
        Returns:
            JSON数据字典
            
        Raises:
            RuntimeError: 当无法提取JSON数据时
        """
        pattern = r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>'
        match = re.search(pattern, html, re.DOTALL)
        if match:
            json_str = match.group(1)
            json_str = re.sub(r'\bundefined\b', 'null', json_str)
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

        start_marker = 'window.__INITIAL_STATE__'
        start_idx = html.find(start_marker)
        if start_idx == -1:
            raise RuntimeError("无法找到window.__INITIAL_STATE__数据")

        json_start = html.find('{', start_idx)
        if json_start == -1:
            raise RuntimeError("无法找到JSON开始位置")

        script_end = html.find('</script>', start_idx)
        if script_end == -1:
            script_end = len(html)

        brace_count = 0
        json_end = json_start
        in_string = False
        escape_next = False
        in_single_quote = False

        search_end = min(script_end, len(html))
        for i in range(json_start, search_end):
            char = html[i]

            if escape_next:
                escape_next = False
                continue

            if char == '\\':
                escape_next = True
                continue

            if char == '"' and not escape_next and not in_single_quote:
                in_string = not in_string
                continue

            if char == "'" and not escape_next and not in_string:
                in_single_quote = not in_single_quote
                continue

            if not in_string and not in_single_quote:
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        json_end = i + 1
                        break

        if brace_count != 0:
            raise RuntimeError("无法找到完整的JSON对象")

        json_str = html[json_start:json_end]
        json_str = re.sub(r'\bundefined\b', 'null', json_str)

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            error_pos = getattr(e, 'pos', 0)
            start_debug = max(0, error_pos - 200)
            end_debug = min(len(json_str), error_pos + 200)
            error_msg = (
                f"JSON解析失败: {e}\n"
                f"错误位置: {error_pos}\n"
                f"附近内容: {json_str[start_debug:end_debug]}"
            )
            raise RuntimeError(error_msg)

    def _clean_topic_tags(self, text: str) -> str:
        """清理简介中的话题标签，将#标签[话题]#格式改为#标签
        
        Args:
            text: 原始文本
            
        Returns:
            清理后的文本
        """
        if not text:
            return text
        pattern = r'#([^#\[]+)\[话题\]#'
        return re.sub(pattern, r'#\1', text)

    def _parse_note_data(self, data: dict, url: str = "") -> dict:
        """从JSON数据中提取所需信息
        
        支持移动端和PC端两种数据路径：
        - 移动端路径: noteData.data.noteData
        - PC端路径: note.noteDetailMap[noteId].note
        
        Args:
            data: JSON数据字典
            url: 原始URL，用于判断数据路径
            
        Returns:
            包含笔记信息的字典，包含以下字段：
            - type: 笔记类型（normal/video）
            - title: 标题
            - desc: 描述
            - author_name: 作者名称
            - author_id: 作者ID
            - publish_time: 发布时间
            - video_url: 视频URL（视频类型）
            - image_urls: 图片URL列表（图集类型）
            
        Raises:
            RuntimeError: 当数据提取失败时
        """
        note_data = None
        user_data = {}
        try:
            note_data = data["noteData"]["data"]["noteData"]
            user_data = note_data.get("user", {})
        except (KeyError, TypeError):
            pass

        if not note_data:
            try:
                note_detail_map = data.get("note", {}).get("noteDetailMap", {})
                for detail in note_detail_map.values():
                    potential = detail.get("note")
                    if potential and isinstance(potential, dict) and potential:
                        note_data = potential
                        user_data = note_data.get("user", {})
                        break
            except (KeyError, TypeError):
                pass

        if not note_data:
            raise RuntimeError("无法找到笔记数据，JSON结构可能不同（移动端和PC端路径都失败）")

        note_type = note_data.get("type", "normal")
        title = note_data.get("title", "")
        desc = note_data.get("desc", "")

        author_name = ""
        author_id = ""
        if user_data:
            author_name = user_data.get("nickName") or user_data.get("nickname", "")
            author_id = user_data.get("userId", "")

        timestamp = note_data.get("time", 0)
        if timestamp:
            dt = datetime.fromtimestamp(timestamp / 1000)
            publish_time = dt.strftime("%Y-%m-%d")
        else:
            publish_time = ""

        video_url = ""
        image_urls = []

        # 视频URL提取逻辑
        if note_type == "video":
            video_info = note_data.get("video", {})
            
            # 优先尝试无水印URL：consumer.originVideoKey
            consumer = video_info.get("consumer", {})
            origin_video_key = consumer.get("originVideoKey", "")
            if origin_video_key:
                video_url = f"https://sns-video-bd.xhscdn.com/{origin_video_key}"
            
            # 如果没有无水印URL，尝试media.stream.h264.masterUrl
            if not video_url and video_info:
                if "media" in video_info:
                    media = video_info["media"]
                    if "stream" in media:
                        stream = media["stream"]
                        if "h264" in stream and len(stream["h264"]) > 0:
                            h264 = stream["h264"][0]
                            video_url = h264.get("masterUrl", "")

            if video_url and video_url.startswith("http://"):
                video_url = video_url.replace("http://", "https://", 1)
            elif video_url and video_url.startswith("//"):
                video_url = "https:" + video_url
        else:
            image_list = note_data.get("imageList", [])
            if image_list:
                for img in image_list:
                    if isinstance(img, dict):
                        url = None
                        if "urlDefault" in img and img["urlDefault"]:
                            url = img["urlDefault"]
                        elif "url" in img and img["url"]:
                            url = img["url"]
                        elif "infoList" in img and isinstance(img["infoList"], list):
                            for info in img["infoList"]:
                                if isinstance(info, dict) and info.get("imageScene") == "WB_DFT":
                                    url = info.get("url")
                                    if url:
                                        break

                        if url:
                            if "picasso-static" not in url and "fe-platform" not in url:
                                if url.startswith("//"):
                                    url = "https:" + url
                                elif url.startswith("http://"):
                                    url = url.replace("http://", "https://", 1)
                                image_urls.append(url)

        desc = self._clean_topic_tags(desc)

        return {
            "type": note_type,
            "title": title,
            "desc": desc,
            "author_name": author_name,
            "author_id": author_id,
            "publish_time": publish_time,
            "video_url": video_url,
            "image_urls": image_urls,
        }

    @staticmethod
    def _format_comment_time(timestamp: Any) -> str:
        "处理format comment time逻辑。"
        if timestamp is None:
            return ""
        try:
            value = int(timestamp)
        except Exception:
            return str(timestamp)
        if value > 10 ** 12:
            value = value // 1000
        if value > 0:
            return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")
        return ""

    def _normalize_hot_comment_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        "处理normalize hot comment item逻辑。"
        user_info = (
            item.get("user")
            or item.get("userInfo")
            or item.get("user_info")
            or item.get("author")
            or {}
        )
        user_id = (
            user_info.get("userId")
            or user_info.get("user_id")
            or user_info.get("uid")
            or user_info.get("id")
            or item.get("userId")
            or item.get("user_id")
            or item.get("uid")
            or ""
        )
        username = (
            user_info.get("nickname")
            or user_info.get("nickName")
            or user_info.get("nick_name")
            or user_info.get("name")
            or item.get("nickname")
            or item.get("user_name")
            or ""
        )
        message = (
            item.get("content")
            or item.get("text")
            or item.get("message")
            or item.get("desc")
            or ""
        )
        likes = (
            item.get("likeCount")
            or item.get("likeViewCount")
            or item.get("like_count")
            or item.get("liked_count")
            or item.get("likes")
            or item.get("digg_count")
            or 0
        )
        created = (
            item.get("time")
            or item.get("create_time")
            or item.get("createTime")
            or item.get("ctime")
        )
        try:
            likes_value = int(likes or 0)
        except (TypeError, ValueError):
            likes_value = 0
        return {
            "username": str(username),
            "uid": str(user_id),
            "likes": likes_value,
            "message": str(message).replace("\n", " ").strip(),
            "time": self._format_comment_time(created),
        }

    def _extract_primary_comments(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        "处理extract primary comments逻辑。"
        note_data_comments = (
            (
                (
                    (state.get("noteData") or {}).get("data") or {}
                ).get("commentData")
                or {}
            ).get("comments")
            or []
        )
        if isinstance(note_data_comments, list) and note_data_comments:
            return [x for x in note_data_comments if isinstance(x, dict)]

        comment_data_comments = (
            ((state.get("commentData") or {}).get("comments") or [])
            if isinstance(state, dict)
            else []
        )
        if isinstance(comment_data_comments, list) and comment_data_comments:
            return [x for x in comment_data_comments if isinstance(x, dict)]

        note = state.get("note") or {}
        note_map = note.get("noteDetailMap") or {}
        if isinstance(note_map, dict):
            for item in note_map.values():
                comments_dict = (item or {}).get("comments") or {}
                comments_list = comments_dict.get("list") or []
                if isinstance(comments_list, list) and comments_list:
                    return [x for x in comments_list if isinstance(x, dict)]

        return []

    def _collect_hot_comments_from_state(
        self,
        state: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        "处理collect hot comments from state逻辑。"
        if self.hot_comment_count <= 0:
            return []
        candidates = self._extract_primary_comments(state)
        if not candidates:
            collected: List[Dict[str, Any]] = []

            def walk(obj: Any) -> None:
                """递归遍历状态树并收集候选评论项。"""
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        key_lower = key.lower()
                        if key_lower in {"subcomments", "sub_comments"}:
                            continue
                        if key_lower in {"comments", "commentlist"} and isinstance(value, list):
                            for item in value:
                                if isinstance(item, dict):
                                    collected.append(item)
                        if key_lower == "comments" and isinstance(value, dict):
                            maybe_list = value.get("list") or []
                            if isinstance(maybe_list, list):
                                for item in maybe_list:
                                    if isinstance(item, dict):
                                        collected.append(item)
                        walk(value)
                elif isinstance(obj, list):
                    for item in obj:
                        walk(item)

            walk(state)
            candidates = collected

        normalized: List[Dict[str, Any]] = []
        seen = set()
        for item in candidates:
            norm = self._normalize_hot_comment_item(item)
            if not norm["message"]:
                continue
            key = (norm["uid"], norm["message"], norm["time"])
            if key in seen:
                continue
            seen.add(key)
            normalized.append(norm)
        normalized.sort(key=lambda x: x.get("likes", 0), reverse=True)
        return normalized[:self.hot_comment_count]

    async def parse(
        self,
        session: aiohttp.ClientSession,
        url: str
    ) -> Optional[Dict[str, Any]]:
        """解析单个小红书链接

        Args:
            session: aiohttp会话
            url: 小红书链接

        Returns:
            解析结果字典，包含标准化的元数据格式：
            - url: 原始URL
            - title: 标题
            - author: 作者信息
            - desc: 描述
            - timestamp: 发布时间
            - video_urls: 视频URL列表（视频类型）
            - image_urls: 图片URL列表（图集类型）
            - image_headers: 图片请求头
            - video_headers: 视频请求头

        Raises:
            RuntimeError: 当解析失败时
        """
        logger.debug(f"[{self.name}] parse: 开始解析 {url}")
        async with self.semaphore:
            if "xhslink.com" in url:
                full_url = await self._get_redirect_url(session, url)
                logger.debug(f"[{self.name}] parse: 短链展开 {url} -> {full_url}")
            else:
                full_url = url
                if not full_url.startswith("http://") and not full_url.startswith("https://"):
                    full_url = "https://" + full_url

            if is_live_url(full_url) or is_live_url(url):
                logger.debug(f"[{self.name}] parse: 检测到直播域名链接，跳过解析 {url} -> {full_url}")
                raise SkipParse("直播域名链接不解析")

            full_url = self._clean_share_url(full_url)

            # 提取笔记ID用于Cookie方式解析
            note_id = None
            note_id_match = re.search(r'/explore/(\w+)', full_url)
            if not note_id_match:
                note_id_match = re.search(r'/discovery/item/(\w+)', full_url)
            if note_id_match:
                note_id = note_id_match.group(1)

            # 提取xsec_token参数
            xsec_source = "pc_feed"
            xsec_token = ""
            try:
                from urllib.parse import parse_qs
                parsed = urlparse(full_url)
                params = parse_qs(parsed.query)
                xsec_source = params.get('xsec_source', ['pc_feed'])[0] or "pc_feed"
                xsec_token = params.get('xsec_token', [''])[0] or ""
            except Exception:
                pass

            logger.debug(f"[{self.name}] parse: 获取页面内容")
            html = await self._fetch_page(session, full_url)
            initial_state = self._extract_initial_state(html)
            note_data = self._parse_note_data(initial_state, full_url)

            # 如果使用Cookie，优先使用Cookie API方式获取数据
            cookie_note_data = None
            if self.use_cookie and self.cookie and note_id:
                logger.debug(f"[{self.name}] parse: 使用Cookie方式获取数据")
                cookie_note_data = await self._fetch_page_with_cookie_api(
                    session, note_id, xsec_source, xsec_token
                )
                if cookie_note_data:
                    logger.debug(f"[{self.name}] parse: Cookie方式获取数据成功")
                    # 合并Cookie获取的数据
                    cookie_title = cookie_note_data.get("title", "")
                    cookie_desc = cookie_note_data.get("desc", "")
                    cookie_video_url = ""
                    cookie_image_urls = []

                    # 提取无水印视频URL
                    if cookie_note_data.get("type") == "video":
                        cookie_video_url = self._extract_no_watermark_video_url(cookie_note_data)

                    # 提取图片URL
                    if cookie_note_data.get("type") != "video":
                        image_list = cookie_note_data.get("imageList", [])
                        for img in image_list:
                            if isinstance(img, dict):
                                url_val = img.get("urlDefault") or img.get("url")
                                if url_val:
                                    if url_val.startswith("//"):
                                        url_val = "https:" + url_val
                                    cookie_image_urls.append(url_val)

                    # 优先使用Cookie获取的数据
                    if cookie_title:
                        note_data["title"] = cookie_title
                    if cookie_desc:
                        note_data["desc"] = cookie_desc
                    if cookie_video_url:
                        note_data["video_url"] = cookie_video_url
                        logger.debug(f"[{self.name}] parse: 使用无水印视频URL")
                    if cookie_image_urls:
                        note_data["image_urls"] = cookie_image_urls
            elif not note_data.get("title") and not note_data.get("desc"):
                # 如果普通解析数据不完整，尝试备用Cookie方式
                logger.debug(f"[{self.name}] parse: 普通解析数据不完整，尝试Cookie方式")
                cookie_note_data = await self._fetch_page_with_cookie_api(
                    session, note_id, xsec_source, xsec_token
                )
                if cookie_note_data:
                    logger.debug(f"[{self.name}] parse: Cookie备用方式获取数据成功")
                    cookie_title = cookie_note_data.get("title", "")
                    cookie_desc = cookie_note_data.get("desc", "")
                    cookie_video_url = ""
                    cookie_image_urls = []

                    if cookie_note_data.get("type") == "video":
                        cookie_video_url = self._extract_no_watermark_video_url(cookie_note_data)

                    if cookie_note_data.get("type") != "video":
                        image_list = cookie_note_data.get("imageList", [])
                        for img in image_list:
                            if isinstance(img, dict):
                                url_val = img.get("urlDefault") or img.get("url")
                                if url_val:
                                    if url_val.startswith("//"):
                                        url_val = "https:" + url_val
                                    cookie_image_urls.append(url_val)

                    if cookie_title and not note_data.get("title"):
                        note_data["title"] = cookie_title
                    if cookie_desc and not note_data.get("desc"):
                        note_data["desc"] = cookie_desc
                    if cookie_video_url and not note_data.get("video_url"):
                        note_data["video_url"] = cookie_video_url
                    if cookie_image_urls and not note_data.get("image_urls"):
                        note_data["image_urls"] = cookie_image_urls

            hot_comments = self._collect_hot_comments_from_state(initial_state)
            logger.debug(f"[{self.name}] parse: 笔记数据提取成功")

            note_type = note_data.get("type", "normal")
            video_url = note_data.get("video_url", "")
            image_urls = note_data.get("image_urls", [])
            title = note_data.get("title", "")
            desc = note_data.get("desc", "")
            author_name = note_data.get("author_name", "")
            author_id = note_data.get("author_id", "")
            publish_time = note_data.get("publish_time", "")

            author = ""
            if author_name and author_id:
                author = f"{author_name}(主页id:{author_id})"
            elif author_name:
                author = author_name
            elif author_id:
                author = f"(主页id:{author_id})"

            referer = full_url
            user_agent = PC_UA if self._is_pc_url(full_url) else ANDROID_UA
            headers = self._get_headers_for_url(full_url)
            image_headers = build_request_headers(
                is_video=False,
                referer=referer,
                user_agent=user_agent
            )
            video_headers = build_request_headers(
                is_video=True,
                referer=referer,
                user_agent=user_agent
            )

            # 如果使用Cookie，在请求头中添加Cookie
            if self.use_cookie and self.cookie:
                image_headers["Cookie"] = self.cookie
                video_headers["Cookie"] = self.cookie

            if note_type == "video":
                if not video_url:
                    logger.debug(f"[{self.name}] parse: 无法获取视频URL {url}")
                    raise RuntimeError(f"无法获取视频URL: {url}")

                result_dict = {
                    "url": url,
                    "title": title,
                    "author": author,
                    "desc": desc,
                    "timestamp": publish_time,
                    "video_urls": [[video_url]],
                    "image_urls": [],
                    "image_headers": image_headers,
                    "video_headers": video_headers,
                }
                if hot_comments:
                    result_dict["hot_comments"] = hot_comments
                logger.debug(f"[{self.name}] parse: 解析完成(视频) {url}, title={title[:50]}")
                return result_dict
            else:
                if not image_urls:
                    logger.debug(f"[{self.name}] parse: 无法获取图片URL {url}")
                    raise RuntimeError(f"无法获取图片URL: {url}")

                result_dict = {
                    "url": url,
                    "title": title,
                    "author": author,
                    "desc": desc,
                    "timestamp": publish_time,
                    "video_urls": [],
                    "image_urls": [[url] for url in image_urls],
                    "image_headers": image_headers,
                    "video_headers": video_headers,
                }
                if hot_comments:
                    result_dict["hot_comments"] = hot_comments
                logger.debug(f"[{self.name}] parse: 解析完成(图片) {url}, title={title[:50]}, image_count={len(image_urls)}")
                return result_dict
