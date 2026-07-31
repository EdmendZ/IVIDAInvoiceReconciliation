"""Prompt 内容寻址版本工具。"""

from hashlib import sha256


def prompt_version(*prompt_texts: str) -> str:
    """按长度分隔拼接内容并生成稳定短 SHA-256 指纹。

    长度前缀避免 ["ab", "c"] 与 ["a", "bc"] 这类简单拼接碰撞。
    """

    digest = sha256()
    for text in prompt_texts:
        encoded = text.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return f"sha256:{digest.hexdigest()[:16]}"
