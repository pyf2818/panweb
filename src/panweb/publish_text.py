"""分享页标题/说明的校验：控制字符与长度上限只在这里定义一次。"""
from .errors import PanwebError

TITLE_MAX = 80
DESC_MAX = 300


def normalize_text(value, limit, label):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if any(ord(ch) < 0x20 or ord(ch) == 0x7f for ch in text):
        raise PanwebError(2, "invalid_argument",
                          "%s不能包含换行或控制字符" % label)
    if len(text) > limit:
        raise PanwebError(2, "invalid_argument",
                          "%s过长（最多 %d 个字符）" % (label, limit))
    return text


def normalize_title(value):
    return normalize_text(value, TITLE_MAX, "标题")


def normalize_desc(value):
    return normalize_text(value, DESC_MAX, "说明")
