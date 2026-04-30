"""消息发送封装，统一不同会话场景下的发送行为。"""
from typing import Any, List, Union

from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Nodes, Plain, Image, Video, Node

from .node_builder import is_pure_image_gallery
from ..logger import logger


def _group_nodes(nodes: List) -> List[List]:
    """将节点列表分组发送，合并封面+文本到同一条消息

    规则：
    - Image(封面) + Plain(文本) → 合并为一条消息
    - Video 单独一条消息
    - 其余各占一条
    """
    grouped = []
    i = 0
    while i < len(nodes):
        node = nodes[i]
        if node is None:
            i += 1
            continue
        # Image(封面) + Plain(文本) → 合并
        if isinstance(node, Image) and i + 1 < len(nodes) and isinstance(nodes[i + 1], Plain):
            grouped.append([node, nodes[i + 1]])
            i += 2
        # Plain(文本) + Image(封面或内容图) → 合并
        elif isinstance(node, Plain) and i + 1 < len(nodes) and isinstance(nodes[i + 1], Image):
            grouped.append([node, nodes[i + 1]])
            i += 2
        else:
            grouped.append([node])
            i += 1
    return grouped


class MessageSender:

    """消息发送器，封装统一的私聊/群聊发送接口。"""

    def get_sender_info(self, event: AstrMessageEvent) -> tuple:
        """获取发送者信息

        Args:
            event: 消息事件对象

        Returns:
            包含发送者名称和ID的元组 (sender_name, sender_id)
        """
        sender_name = "视频解析bot"
        platform = event.get_platform_name()
        sender_id = event.get_self_id()
        if platform not in ("wechatpadpro", "webchat", "gewechat"):
            try:
                sender_id = int(sender_id)
            except (ValueError, TypeError):
                sender_id = 10000
        return sender_name, sender_id

    async def send_packed_results(
        self,
        event: AstrMessageEvent,
        link_metadata: list,
        sender_name: str,
        sender_id: Any,
        large_video_threshold_mb: float = 0.0
    ):
        """发送打包的结果（使用Nodes）

        Args:
            event: 消息事件对象
            link_metadata: 链接元数据列表
            sender_name: 发送者名称
            sender_id: 发送者ID
            large_video_threshold_mb: 大视频阈值(MB)
        """
        normal_metadata = [
            meta for meta in link_metadata if meta.get('is_normal', True)
        ]
        large_media_metadata = [
            meta for meta in link_metadata if meta.get('is_large_media', False)
        ]
        normal_link_nodes = [
            meta['link_nodes'] for meta in normal_metadata
        ]
        large_media_link_nodes = [
            meta['link_nodes'] for meta in large_media_metadata
        ]
        separator = "-------------------------------------"

        if normal_link_nodes:
            flat_nodes = []
            for link_idx, link_nodes in enumerate(normal_link_nodes):
                if is_pure_image_gallery(link_nodes):
                    texts = [
                        node for node in link_nodes
                        if isinstance(node, Plain)
                    ]
                    images = [
                        node for node in link_nodes
                        if isinstance(node, Image)
                    ]
                    for text in texts:
                        flat_nodes.append(Node(
                            name=sender_name,
                            uin=sender_id,
                            content=[text]
                        ))
                    if images:
                        flat_nodes.append(Node(
                            name=sender_name,
                            uin=sender_id,
                            content=images
                        ))
                else:
                    groups = _group_nodes(link_nodes)
                    for group in groups:
                        flat_nodes.append(Node(
                            name=sender_name,
                            uin=sender_id,
                            content=group
                        ))
                if link_idx < len(normal_link_nodes) - 1:
                    flat_nodes.append(Node(
                        name=sender_name,
                        uin=sender_id,
                        content=[Plain(separator)]
                    ))
            if flat_nodes:
                await event.send(event.chain_result([Nodes(flat_nodes)]))

        if large_media_link_nodes:
            await self.send_large_media_results(
                event,
                large_media_metadata,
                large_media_link_nodes,
                sender_name,
                sender_id,
                large_video_threshold_mb
            )

    async def send_large_media_results(
        self,
        event: AstrMessageEvent,
        metadata: list,
        link_nodes_list: list,
        sender_name: str,
        sender_id: Any,
        large_video_threshold_mb: float = 0.0
    ):
        """发送大媒体结果（单独发送）

        Args:
            event: 消息事件对象
            metadata: 元数据列表
            link_nodes_list: 链接节点列表
            sender_name: 发送者名称
            sender_id: 发送者ID
            large_video_threshold_mb: 大视频阈值(MB)
        """
        separator = "-------------------------------------"
        threshold_mb = (
            int(large_video_threshold_mb)
            if large_video_threshold_mb > 0
            else 50
        )
        notice_text = (
            f"⚠️ 链接中包含超过{threshold_mb}MB的视频时"
            f"将单独发送所有媒体"
        )
        await event.send(event.plain_result(notice_text))
        for link_idx, link_nodes in enumerate(link_nodes_list):
            for node in link_nodes:
                if node is not None:
                    try:
                        await event.send(event.chain_result([node]))
                    except Exception as e:
                        logger.warning(f"发送大媒体节点失败: {e}")
            if link_idx < len(link_nodes_list) - 1:
                try:
                    await event.send(event.plain_result(separator))
                except Exception as e:
                    logger.warning(f"发送分隔符失败: {e}")

    async def send_unpacked_results(
        self,
        event: AstrMessageEvent,
        all_link_nodes: list
    ):
        """发送非打包的结果（独立发送）

        Args:
            event: 消息事件对象
            all_link_nodes: 所有链接节点列表
        """
        separator = "-------------------------------------"
        for link_idx, link_nodes in enumerate(all_link_nodes):
            if is_pure_image_gallery(link_nodes):
                texts = [
                    node for node in link_nodes
                    if isinstance(node, Plain)
                ]
                images = [
                    node for node in link_nodes
                    if isinstance(node, Image)
                ]
                for text in texts:
                    await event.send(event.chain_result([text]))
                if images:
                    await event.send(event.chain_result(images))
            else:
                groups = _group_nodes(link_nodes)
                for group in groups:
                    try:
                        await event.send(event.chain_result(group))
                    except Exception as e:
                        logger.warning(f"发送节点失败: {e}")
            if link_idx < len(all_link_nodes) - 1:
                await event.send(event.plain_result(separator))

