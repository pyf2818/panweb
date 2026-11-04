"""读取公网代理的请求体：支持 chunked，拒绝不认识的传输编码。

以前只认 Content-Length，``Transfer-Encoding: chunked`` 会被当成空 body 转发，
后端拿到的是一份被悄悄截断的请求。这里明确解码或明确拒绝，不再静默置空。
"""


class BodyError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def read_request_body(headers, rfile, limit):
    """返回 bytes 或 None；越界/畸形抛 BodyError（带 HTTP 状态）。"""
    encoding = headers.get("Transfer-Encoding")
    if encoding:
        tokens = [t.strip().lower() for t in encoding.split(",") if t.strip()]
        if not tokens or tokens[-1] != "chunked":
            raise BodyError(411, "不支持的 Transfer-Encoding，请用 chunked 或 Content-Length")
        return _read_chunked(rfile, limit)
    raw_length = headers.get("Content-Length")
    if raw_length is None:
        return None
    try:
        length = int(raw_length)
    except ValueError:
        raise BodyError(400, "Content-Length 不合法")
    if length < 0:
        raise BodyError(400, "Content-Length 不合法")
    if length > limit:
        raise BodyError(413, "请求体超过 %d MB 上限" % (limit // (1024 * 1024)))
    if length == 0:
        return None
    data = rfile.read(length)
    if len(data) != length:
        raise BodyError(400, "请求体不完整")
    return data


def _read_chunked(rfile, limit):
    chunks = []
    total = 0
    while True:
        line = rfile.readline(65537)
        if not line:
            raise BodyError(400, "chunked 请求体提前结束")
        size_text = line.split(b";", 1)[0].strip()
        try:
            size = int(size_text, 16)
        except ValueError:
            raise BodyError(400, "chunked 块大小不合法")
        if size == 0:
            _read_trailers(rfile)
            return b"".join(chunks)
        total += size
        if total > limit:
            raise BodyError(413, "请求体超过 %d MB 上限"
                            % (limit // (1024 * 1024)))
        data = rfile.read(size)
        if len(data) != size:
            raise BodyError(400, "chunked 数据不完整")
        chunks.append(data)
        if rfile.readline(65537) not in (b"\r\n", b"\n"):
            raise BodyError(400, "chunked 块分隔符不合法")


def _read_trailers(rfile):
    while True:
        line = rfile.readline(65537)
        if not line or line in (b"\r\n", b"\n"):
            return
