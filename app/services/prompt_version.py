from hashlib import sha256


def prompt_version(*prompt_texts: str) -> str:
    digest = sha256()
    for text in prompt_texts:
        encoded = text.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return f"sha256:{digest.hexdigest()[:16]}"
