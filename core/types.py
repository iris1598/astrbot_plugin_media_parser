"""项目统一类型定义（TypedDict、别名与结构约束）。"""
from typing import TypedDict, List, Dict, Optional, Any

class MediaMetadata(TypedDict, total=False):
    """提取的媒体元数据信息结构"""
    url: str
    source_url: Optional[str]
    title: Optional[str]
    author: Optional[str]
    desc: Optional[str]
    timestamp: Optional[str]
    video_urls: List[List[str]]
    image_urls: List[List[str]]
    image_headers: Dict[str, str]
    video_headers: Dict[str, str]
    video_force_download: Optional[bool]
    access_status: Optional[str]
    restriction_type: Optional[str]
    restriction_label: Optional[str]
    can_access_full_video: Optional[bool]
    is_preview_only: Optional[bool]
    access_message: Optional[str]
    timelength_ms: Optional[int]
    available_length_ms: Optional[int]
    hot_comments: Optional[List[Dict[str, Any]]]
    error: Optional[str]
    is_normal: Optional[bool]
    is_large_media: Optional[bool]
    link_nodes: Optional[List[Any]]
    video_files: Optional[List[str]]
