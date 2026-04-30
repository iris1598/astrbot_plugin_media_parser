"""消息节点构建器，将解析结果转换为可发送消息节点。"""
import os
from typing import Dict, Any, List, Optional, Union

from ..logger import logger

from astrbot.api.message_components import Plain, Image, Video

from ..downloader.utils import strip_media_prefixes
from ..types import BuildAllNodesResult, LinkBuildMeta

# ── 平台显示名映射 ──────────────────────────────────────

_PLATFORM_DISPLAY: Dict[str, str] = {
    "bilibili": "B站",
    "douyin": "抖音",
    "tiktok": "TikTok",
    "kuaishou": "快手",
    "weibo": "微博",
    "xiaohongshu": "小红书",
    "xianyu": "闲鱼",
    "toutiao": "头条",
    "xiaoheihe": "小黑盒",
    "twitter": "Twitter",
}

# ── nonebot 风格统计标签映射 ────────────────────────────

_STAT_LABELS = {
    "点赞": "点赞",
    "投币": "硬币",
    "硬币": "硬币",
    "收藏": "收藏",
    "分享": "分享",
    "播放": "总播放量",
    "弹幕": "弹幕数量",
    "评论": "评论",
    "like": "点赞",
    "coin": "硬币",
    "favorite": "收藏",
    "share": "分享",
    "view": "总播放量",
    "danmaku": "弹幕数量",
    "reply": "评论",
}


def _format_stat_value(value: Any) -> str:
    """格式化统计数据，大于10000时显示为万单位"""
    try:
        val = int(value)
        if val > 10000:
            return f"{val / 10000:.1f}万"
        return str(val)
    except (TypeError, ValueError):
        return str(value)


def _resolve_output_flag(
    metadata: Dict[str, Any],
    key: str,
    default: bool
) -> bool:
    value = metadata.get(key)
    if value is None:
        return bool(default)
    return bool(value)


def _append_media_skip_summary(text_parts: List[str], metadata: Dict[str, Any]) -> None:
    """将媒体跳过统计和逐项原因追加到文本节点。"""
    video_reasons = metadata.get('video_skip_reasons', []) or []
    image_reasons = metadata.get('image_skip_reasons', []) or []
    video_count = metadata.get('video_count', len(metadata.get('video_urls', [])))
    image_count = metadata.get('image_count', len(metadata.get('image_urls', [])))
    skipped_videos = [
        (idx + 1, reason)
        for idx, reason in enumerate(video_reasons)
        if reason
    ]
    skipped_images = [
        (idx + 1, reason)
        for idx, reason in enumerate(image_reasons)
        if reason
    ]
    if not skipped_videos and not skipped_images:
        return

    summary_parts = []
    if video_count:
        summary_parts.append(f"视频 {len(skipped_videos)}/{video_count}")
    if image_count:
        summary_parts.append(f"图片 {len(skipped_images)}/{image_count}")
    if summary_parts:
        text_parts.append(f"媒体跳过：{', '.join(summary_parts)}")

    for idx, reason in skipped_videos[:5]:
        text_parts.append(f"  视频[{idx}]：{reason}")
    for idx, reason in skipped_images[:5]:
        text_parts.append(f"  图片[{idx}]：{reason}")


def _mark_media_failure(
    metadata: Dict[str, Any],
    kind: str,
    index: int,
    reason: str
) -> None:
    """节点构建失败时回填跳过原因，供文本节点或调试使用。"""
    key = 'video_skip_reasons' if kind == 'video' else 'image_skip_reasons'
    modes_key = 'video_modes' if kind == 'video' else 'image_modes'
    count_key = 'failed_video_count' if kind == 'video' else 'failed_image_count'
    reasons = metadata.setdefault(key, [])
    while len(reasons) <= index:
        reasons.append(None)
    if not reasons[index]:
        reasons[index] = reason
    modes = metadata.setdefault(modes_key, [])
    while len(modes) <= index:
        modes.append('skip')
    modes[index] = 'skip'
    try:
        metadata[count_key] = int(metadata.get(count_key, 0) or 0) + 1
    except (TypeError, ValueError):
        metadata[count_key] = 1


def _format_bilibili_text(metadata: Dict[str, Any]) -> Optional[List[str]]:
    """构建B站 nonebot 原版风格文本"""
    title = metadata.get('title', '').strip()
    if not title:
        return None
    text_parts = [f"识别：B站，{title}"]

    # nonebot 统计行：点赞: xxx | 硬币: xxx | 收藏: xxx | 分享: xxx | 总播放量: xxx | 弹幕数量: xxx | 评论: xxx |
    stat = metadata.get("stat", {})
    if isinstance(stat, dict) and stat:
        stat_parts = []
        order = ["点赞", "硬币", "收藏", "分享", "总播放量", "弹幕数量", "评论"]
        for label in order:
            if label in stat:
                val = stat[label]
                stat_parts.append(f"{label}: {_format_stat_value(val)}")
        if stat_parts:
            text_parts.append(" | ".join(stat_parts) + " | ")

    # 简介（nonebot 原版无 📝 emoji）
    desc = metadata.get('desc', '').strip()
    if desc:
        if len(desc) > 300:
            desc = desc[:297] + "..."
        text_parts.append(f"📝 简介：{desc}")

    return text_parts


def _format_douyin_text(metadata: Dict[str, Any]) -> Optional[List[str]]:
    """构建抖音 nonebot 风格文本"""
    parts = []
    parts.append("【抖音】")
    author = metadata.get('author', '').strip()
    if author:
        parts.append(f"作者：{author}")
    title = metadata.get('title', '').strip()
    if title:
        parts.append(f"标题：{title}")
    return parts if len(parts) > 1 else None


def _format_xiaohongshu_text(metadata: Dict[str, Any]) -> Optional[List[str]]:
    """构建小红书 nonebot 风格文本"""
    parts = []
    title = metadata.get('title', '').strip()
    desc = metadata.get('desc', '').strip()
    if not title and not desc:
        return None
    if title:
        parts.append(f"小红书，{title}")
    if desc:
        if len(desc) > 300:
            desc = desc[:297] + "..."
        parts.append(desc)
    return parts if parts else None


def _format_generic_text(metadata: Dict[str, Any]) -> Optional[List[str]]:
    """通用平台文本（nonebot 简洁风格）"""
    parts = []
    platform = metadata.get("platform", "") or ""
    disp = _PLATFORM_DISPLAY.get(platform, platform.capitalize())
    title = metadata.get('title', '').strip()
    if title:
        parts.append(f"识别：{disp}，{title}")
    else:
        parts.append(f"识别：{disp}")

    author = metadata.get('author', '').strip()
    if author:
        parts.append(f"作者：{author}")

    desc = metadata.get('desc', '').strip()
    if desc:
        if len(desc) > 300:
            desc = desc[:297] + "..."
        parts.append(f"📝 简介：{desc}")

    ts = metadata.get('timestamp', '').strip()
    if ts:
        parts.append(f"🕐 发布时间：{ts}")

    # 通用统计
    stat = metadata.get("stat", {})
    if isinstance(stat, dict) and stat:
        stat_parts = []
        for key, val in stat.items():
            label = _STAT_LABELS.get(key, key)
            stat_parts.append(f"{label}: {_format_stat_value(val)}")
        if stat_parts:
            parts.append(" | ".join(stat_parts))

    access_msg = metadata.get("access_message", "").strip()
    if access_msg:
        parts.append(f"⏱ {access_msg}")

    return parts


def build_text_node(metadata: Dict[str, Any], max_video_size_mb: float = 0.0, enable_text_metadata: bool = True) -> Optional[Plain]:
    """构建文本节点（nonebot-plugin-resolver 风格格式，按平台区分）

    Args:
        metadata: 元数据字典
        max_video_size_mb: 最大允许的视频大小(MB)，用于显示详细的错误信息
        enable_text_metadata: 是否包含视频图文文本信息的附加文本

    Returns:
        Plain文本节点，无内容时为None
    """
    if not enable_text_metadata:
        return None

    platform = metadata.get("platform", "") or ""
    error = metadata.get('error', '').strip()
    has_valid_media = metadata.get('has_valid_media')
    video_urls = metadata.get('video_urls', [])
    image_urls = metadata.get('image_urls', [])
    exceeds_max = metadata.get('exceeds_max_size', False)

    # ── 选择平台格式化器 ───────────────────────────
    if platform == "bilibili":
        text_parts = _format_bilibili_text(metadata)
    elif platform == "douyin":
        text_parts = _format_douyin_text(metadata)
    elif platform == "xiaohongshu":
        text_parts = _format_xiaohongshu_text(metadata)
    else:
        text_parts = _format_generic_text(metadata)

    if text_parts is None:
        text_parts = []

    # ── 视频大小 ─────────────────────────────────
    video_count = metadata.get('video_count', 0)
    if video_count > 0:
        actual_max_video_size_mb = metadata.get('max_video_size_mb')
        total_video_size_mb = metadata.get('total_video_size_mb', 0.0)
        if actual_max_video_size_mb is not None:
            if video_count == 1:
                text_parts.append(f"💾 视频大小：{actual_max_video_size_mb:.1f} MB")
            else:
                text_parts.append(
                    f"💾 视频大小：最大 {actual_max_video_size_mb:.1f} MB "
                    f"(共 {video_count} 个视频, 总计 {total_video_size_mb:.1f} MB)"
                )

    # ── 热评 ─────────────────────────────────────
    hot_comments = metadata.get("hot_comments", [])
    if isinstance(hot_comments, list) and hot_comments:
        text_parts.append(f"🔥 热评（{len(hot_comments)}条）:")
        total = len(hot_comments)
        for idx, item in enumerate(hot_comments, start=1):
            if not isinstance(item, dict):
                continue
            username = str(item.get("username", "") or "").strip() or "未知用户"
            uid = str(item.get("uid", "") or "").strip()
            try:
                likes = int(item.get("likes", 0) or 0)
            except (TypeError, ValueError):
                likes = 0
            time_text = str(item.get("time", "") or "").strip() or "-"
            message = str(item.get("message", "") or "").strip() or "（无文本内容）"
            user_label = f"{username}(uid:{uid})" if uid else username
            text_parts.append(f"[{idx}] {user_label}")
            text_parts.append(f"点赞: {likes} | 时间: {time_text}")
            text_parts.append(message)
            if idx < total:
                text_parts.append("")

    # ── 错误/失败信息 ─────────────────────────────
    if error:
        text_parts.append(f"❌ {error}")

    has_text_metadata = bool(
        metadata.get('title') or metadata.get('author') or
        metadata.get('desc') or metadata.get('timestamp')
    )
    if has_valid_media is False and (video_urls or image_urls) and has_text_metadata and not exceeds_max:
        if metadata.get('has_access_denied'):
            text_parts.append("⚠️ 解析失败：媒体访问被拒绝(403 Forbidden)")
        else:
            text_parts.append("⚠️ 解析失败：直链内未找到有效媒体")

    if exceeds_max:
        actual_video_size = metadata.get('max_video_size_mb')
        if actual_video_size is not None:
            if max_video_size_mb > 0:
                text_parts.append(
                    f"⚠️ 解析失败：视频大小超过管理员设定的限制"
                    f"（{actual_video_size:.1f}MB > {max_video_size_mb:.1f}MB）"
                )
            else:
                text_parts.append(f"⚠️ 解析失败：视频大小超过限制（{actual_video_size:.1f}MB）")

    _append_media_skip_summary(text_parts, metadata)

    # ── 原始链接 ─────────────────────────────────
    if metadata.get('url'):
        text_parts.append(f"🔗 原始链接：{metadata['url']}")

    if not text_parts:
        return None
    return Plain("\n".join(text_parts))


def build_media_nodes(
    metadata: Dict[str, Any],
    use_local_files: bool = False,
    enable_rich_media: bool = True
) -> List[Union[Image, Video]]:
    """构建媒体节点

    Args:
        metadata: 元数据字典
        use_local_files: 是否使用本地文件
        enable_rich_media: 是否构建富媒体节点

    Returns:
        媒体节点列表（Image或Video节点）
    """
    nodes = []
    url = metadata.get('url', '')

    if not enable_rich_media:
        logger.debug(f"富媒体输出已关闭，跳过媒体节点: {url}")
        return nodes
    
    if metadata.get('exceeds_max_size'):
        logger.debug(f"媒体超过大小限制，跳过节点构建: {url}")
        return nodes
    
    has_valid_media = metadata.get('has_valid_media')
    if has_valid_media is None:
        logger.warning(f"元数据中has_valid_media字段为None，视为False: {url}")
        has_valid_media = False
    
    if has_valid_media is False:
        logger.debug(f"媒体无效，跳过节点构建: {url}")
        return nodes
    
    video_urls = metadata.get('video_urls', [])
    image_urls = metadata.get('image_urls', [])
    file_paths = metadata.get('file_paths', [])
    video_modes = metadata.get('video_modes') or []
    image_modes = metadata.get('image_modes') or []
    use_fts = metadata.get('use_file_token_service', False)
    file_token_urls = metadata.get('file_token_urls', [])
    
    logger.debug(
        f"构建媒体节点: {url}, "
        f"视频: {len(video_urls)}, 图片: {len(image_urls)}, "
        f"文件路径: {len(file_paths)}, 使用本地文件: {use_local_files}, "
        f"文件Token服务: {use_fts}"
    )
    
    if not video_urls and not image_urls and not file_paths:
        logger.debug(f"无媒体内容，跳过节点构建: {url}")
        return nodes
    
    file_idx = 0
    
    for idx, url_list in enumerate(video_urls):
        mode = video_modes[idx] if idx < len(video_modes) else (
            'local' if use_local_files else 'direct'
        )
        if mode == 'skip':
            file_idx += 1
            continue
        if not url_list or not isinstance(url_list, list):
            file_idx += 1
            continue
        
        video_url = url_list[0] if url_list else None
        if not video_url:
            file_idx += 1
            continue
        
        token_url = (
            file_token_urls[file_idx]
            if use_fts and file_idx < len(file_token_urls)
            else None
        )
        if token_url:
            try:
                nodes.append(Video.fromURL(token_url))
                file_idx += 1
                continue
            except Exception as e:
                logger.warning(f"使用Token URL构建视频节点失败: {token_url}, 错误: {e}")
        
        if mode == 'local' and file_idx < len(file_paths) and file_paths[file_idx] and os.path.exists(file_paths[file_idx]):
            try:
                nodes.append(Video.fromFileSystem(file_paths[file_idx]))
            except Exception as e:
                logger.warning(f"构建视频节点失败: {file_paths[file_idx]}, 错误: {e}")
                _mark_media_failure(metadata, 'video', idx, f"构建本地视频节点失败: {e}")
        elif mode == 'local':
            _mark_media_failure(metadata, 'video', idx, "本地视频文件不存在或不可访问")
        else:
            actual_video_url = strip_media_prefixes(video_url)
            try:
                nodes.append(Video.fromURL(actual_video_url))
            except Exception as e:
                logger.warning(f"构建视频节点失败: {actual_video_url}, 错误: {e}")
                _mark_media_failure(metadata, 'video', idx, f"构建视频URL节点失败: {e}")
        
        file_idx += 1
    
    for image_idx, url_list in enumerate(image_urls):
        mode = image_modes[image_idx] if image_idx < len(image_modes) else (
            'local' if use_local_files else 'direct'
        )
        if mode == 'skip':
            file_idx += 1
            continue
        if not url_list or not isinstance(url_list, list):
            file_idx += 1
            continue
        
        image_url = url_list[0] if url_list else None
        if not image_url:
            file_idx += 1
            continue
        
        token_url = (
            file_token_urls[file_idx]
            if use_fts and file_idx < len(file_token_urls)
            else None
        )
        if token_url:
            try:
                nodes.append(Image.fromURL(token_url))
                file_idx += 1
                continue
            except Exception as e:
                logger.warning(f"使用Token URL构建图片节点失败: {token_url}, 错误: {e}")
        
        if mode == 'local' and file_idx < len(file_paths) and file_paths[file_idx]:
            try:
                nodes.append(Image.fromFileSystem(file_paths[file_idx]))
            except Exception as e:
                logger.warning(f"构建图片节点失败: {file_paths[file_idx]}, 错误: {e}")
                _mark_media_failure(metadata, 'image', image_idx, f"构建本地图片节点失败: {e}")
        elif mode == 'local':
            _mark_media_failure(metadata, 'image', image_idx, "本地图片文件不存在或不可访问")
        else:
            try:
                nodes.append(Image.fromURL(image_url))
            except Exception as e:
                logger.warning(f"构建图片节点失败: {image_url}, 错误: {e}")
                _mark_media_failure(metadata, 'image', image_idx, f"构建图片URL节点失败: {e}")
        
        file_idx += 1
    
    logger.debug(f"构建媒体节点完成: {url}, 共 {len(nodes)} 个节点")
    return nodes


def _build_cover_node(metadata: Dict[str, Any], enable_rich_media: bool) -> Optional[Image]:
    """构建封面图片节点

    Args:
        metadata: 元数据字典
        enable_rich_media: 是否启用富媒体

    Returns:
        Image节点，无封面时为None
    """
    if not enable_rich_media:
        return None
    cover_url = metadata.get("cover_url", "")
    if not cover_url:
        return None
    try:
        return Image.fromURL(cover_url)
    except Exception as e:
        logger.warning(f"构建封面图片节点失败: {cover_url}, 错误: {e}")
        return None


def build_nodes_for_link(
    metadata: Dict[str, Any],
    use_local_files: bool = False,
    max_video_size_mb: float = 0.0,
    enable_text_metadata: bool = True,
    enable_rich_media: bool = True
) -> List[Union[Plain, Image, Video]]:
    """构建单个链接的节点列表

    Args:
        metadata: 元数据字典
        use_local_files: 是否使用本地文件
        max_video_size_mb: 最大允许的视频大小(MB)，用于显示详细的错误信息
        enable_text_metadata: 是否发送图文文本消息
        enable_rich_media: 是否发送图片/视频

    Returns:
        节点列表（Plain、Image、Video对象）
    """
    nodes = []
    effective_text_metadata = _resolve_output_flag(
        metadata,
        "_enable_text_metadata",
        enable_text_metadata,
    )
    effective_rich_media = _resolve_output_flag(
        metadata,
        "_enable_rich_media",
        enable_rich_media,
    )

    media_nodes = build_media_nodes(
        metadata,
        use_local_files,
        effective_rich_media,
    )
    
    cover_img = _build_cover_node(metadata, effective_rich_media)
    if cover_img:
        nodes.append(cover_img)
    
    text_node = build_text_node(
        metadata,
        max_video_size_mb,
        effective_text_metadata,
    )
    if text_node:
        nodes.append(text_node)
    nodes.extend(media_nodes)
    
    return nodes


def is_pure_image_gallery(nodes: List[Union[Plain, Image, Video]]) -> bool:
    """判断节点列表是否是纯图片图集

    Args:
        nodes: 节点列表

    Returns:
        是否为纯图片图集
    """
    has_video = False
    has_image = False
    for node in nodes:
        if isinstance(node, Video):
            has_video = True
            break
        elif isinstance(node, Image):
            has_image = True
    return has_image and not has_video


def build_all_nodes(
    metadata_list: List[Dict[str, Any]],
    is_auto_pack: bool,
    large_video_threshold_mb: float = 0.0,
    max_video_size_mb: float = 0.0,
    enable_text_metadata: bool = True,
    enable_rich_media: bool = True
) -> BuildAllNodesResult:
    """构建所有链接的节点，处理消息打包逻辑

    Args:
        metadata_list: 元数据列表
        is_auto_pack: 是否打包为Node
        large_video_threshold_mb: 大视频阈值(MB)
        max_video_size_mb: 最大允许的视频大小(MB)，用于显示错误信息
        enable_text_metadata: 是否发送图文文本消息
        enable_rich_media: 是否发送图片/视频

    Returns:
        BuildAllNodesResult 命名元组
    """
    all_link_nodes = []
    link_metadata = []
    temp_files = []
    video_files = []
    
    logger.debug(f"开始构建所有节点，元数据数量: {len(metadata_list)}, 打包模式: {is_auto_pack}")
    
    for idx, metadata in enumerate(metadata_list):
        url = metadata.get('url', '')
        max_video_size = metadata.get('max_video_size_mb')
        exceeds_max_size = metadata.get('exceeds_max_size', False)
        is_large_media = False
        if large_video_threshold_mb > 0 and max_video_size is not None and not exceeds_max_size:
            if max_video_size > large_video_threshold_mb:
                is_large_media = True
        
        use_local_files = metadata.get('use_local_files', False)
        
        logger.debug(
            f"构建节点[{idx}]: {url}, "
            f"大媒体: {is_large_media}, 使用本地文件: {use_local_files}"
        )
        
        link_nodes = build_nodes_for_link(
            metadata,
            use_local_files,
            max_video_size_mb,
            enable_text_metadata,
            enable_rich_media
        )
        
        logger.debug(f"节点构建完成[{idx}]: {url}, 节点数量: {len(link_nodes)}")
        
        link_file_paths = metadata.get('file_paths', [])
        link_video_files = []
        link_temp_files = []
        
        video_urls = metadata.get('video_urls', [])
        video_count = len(video_urls)
        video_modes = metadata.get('video_modes') or []
        image_modes = metadata.get('image_modes') or []

        for fp_idx, file_path in enumerate(link_file_paths):
            if not file_path:
                continue
            if fp_idx < video_count:
                mode = video_modes[fp_idx] if fp_idx < len(video_modes) else ''
                if mode == 'local':
                    link_video_files.append(file_path)
                    video_files.append(file_path)
            else:
                img_idx = fp_idx - video_count
                mode = image_modes[img_idx] if img_idx < len(image_modes) else ''
                if mode == 'local':
                    link_temp_files.append(file_path)
                    temp_files.append(file_path)
        
        if link_nodes:
            all_link_nodes.append(link_nodes)
            link_metadata.append(LinkBuildMeta(
                link_nodes=link_nodes,
                is_large_media=is_large_media,
                is_normal=not is_large_media,
                video_files=link_video_files,
                temp_files=link_temp_files,
            ))
        else:
            logger.debug(f"节点为空，跳过发送队列: {url}")
    
    logger.debug(
        f"所有节点构建完成: "
        f"链接节点: {len(all_link_nodes)}, "
        f"临时文件: {len(temp_files)}, "
        f"视频文件: {len(video_files)}"
    )
    
    return BuildAllNodesResult(all_link_nodes, link_metadata, temp_files, video_files)

