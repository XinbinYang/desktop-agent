import re
from typing import List


DEFAULT_SEPARATORS = [
    # Markdown / 文档结构
    "\n## ",
    "\n### ",
    "\n#### ",
    "\n##### ",
    "\n###### ",
    # 代码块
    "\n```\n",
    "\n\n",
    "\n",
    # 句子边界（中英文）
    "。",
    "．",
    "！",
    "？",
    ". ",
    "! ",
    "? ",
    # 词边界
    " ",
    "",
]


def recursive_split_text(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    separators: List[str] | None = None,
) -> List[str]:
    """递归字符文本切分器。

    优先尝试大粒度的分隔符切分，若切分后的块仍大于 chunk_size，
    则递归使用更小的分隔符继续切分，直到满足大小限制。
    """
    if separators is None:
        separators = list(DEFAULT_SEPARATORS)

    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    if not separators:
        # 没有可用分隔符时，强制按字符切分
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunks.append(text[start:end])
            start = end - chunk_overlap if end < len(text) else end
        return [c.strip() for c in chunks if c.strip()]

    separator = separators[0]
    remaining_separators = separators[1:]

    if separator == "":
        # 最后一个分隔符：按字符切分
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunks.append(text[start:end])
            if end >= len(text):
                break
            start = end - chunk_overlap
        return [c.strip() for c in chunks if c.strip()]

    # 按当前分隔符切分
    parts = text.split(separator)
    # 保留分隔符（除空字符串外）
    if separator:
        reconstructed = []
        for i, part in enumerate(parts):
            if i > 0:
                reconstructed.append(separator + part)
            else:
                reconstructed.append(part)
        parts = reconstructed

    good_chunks = []
    current_chunk = ""

    for part in parts:
        if not part.strip():
            continue
        if len(current_chunk) + len(part) <= chunk_size:
            current_chunk += part
        else:
            if current_chunk.strip():
                good_chunks.append(current_chunk.strip())
            # 当前 part 太大，需要递归切分
            if len(part) > chunk_size:
                sub_chunks = recursive_split_text(
                    part, chunk_size, chunk_overlap, remaining_separators
                )
                good_chunks.extend(sub_chunks)
                current_chunk = ""
            else:
                current_chunk = part

    if current_chunk.strip():
        good_chunks.append(current_chunk.strip())

    # 合并重叠
    if not good_chunks:
        return []

    final_chunks = [good_chunks[0]]
    for chunk in good_chunks[1:]:
        prev = final_chunks[-1]
        if len(prev) < chunk_size - chunk_overlap:
            # 尝试合并
            combined = prev + "\n" + chunk
            if len(combined) <= chunk_size:
                final_chunks[-1] = combined
                continue
        final_chunks.append(chunk)

    return [c for c in final_chunks if c.strip()]


def split_document(text: str, source_path: str, chunk_size: int = 500, chunk_overlap: int = 50) -> List[dict]:
    """切分文档并返回带元数据的 chunk 列表。"""
    chunks = recursive_split_text(text, chunk_size, chunk_overlap)
    return [
        {
            "source_path": source_path,
            "content": chunk,
            "index": i,
        }
        for i, chunk in enumerate(chunks)
    ]
