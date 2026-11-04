"""纯标准库二维码：字节模式、纠错等级 M、版本 1–10、终端块码。

没有第三方依赖也没有 CDN：CLI 只把分享页 URL 编进二维码，URL 之外的内容
（尤其口令）根本不会进入这里。
"""
EC_M = 0  # 格式信息里的纠错等级编码（M = 00）
# 版本 -> (每块纠错码字数, ((块数, 每块数据码字数), ...))
BLOCKS = {
    1: (10, ((1, 16),)),
    2: (16, ((1, 28),)),
    3: (26, ((1, 44),)),
    4: (18, ((2, 32),)),
    5: (24, ((2, 43),)),
    6: (16, ((4, 27),)),
    7: (18, ((4, 31),)),
    8: (22, ((2, 38), (2, 39))),
    9: (22, ((3, 36), (2, 37))),
    10: (26, ((4, 43), (1, 44))),
}
ALIGN = {
    1: (), 2: (6, 18), 3: (6, 22), 4: (6, 26), 5: (6, 30), 6: (6, 34),
    7: (6, 22, 38), 8: (6, 24, 42), 9: (6, 26, 46), 10: (6, 28, 50),
}
_GF_EXP = [0] * 512
_GF_LOG = [0] * 256
_x = 1
for _i in range(255):
    _GF_EXP[_i] = _x
    _GF_LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11d
for _i in range(255, 512):
    _GF_EXP[_i] = _GF_EXP[_i - 255]


def encode(text, version=None):
    """把文本编成二维码矩阵（每行从左到右，1 = 深色）。"""
    data = text.encode("utf-8") if isinstance(text, str) else bytes(text)
    v = version or _pick_version(len(data))
    codewords = _codewords(data, v)
    return _matrix(v, codewords)


def render_terminal(matrix, quiet=4):
    """终端块码：每两行折成一个字符，四周留 4 个模块静区。"""
    n = len(matrix)
    lines = []
    for r in range(-quiet, n + quiet, 2):
        row = []
        for c in range(-quiet, n + quiet):
            top = _dark(matrix, r, c)
            bottom = _dark(matrix, r + 1, c)
            row.append("█" if top and bottom else
                       "▀" if top else "▄" if bottom else " ")
        lines.append("".join(row).rstrip())
    return "\n".join(lines)


def _dark(matrix, r, c):
    n = len(matrix)
    return 0 <= r < n and 0 <= c < n and matrix[r][c] == 1


def _pick_version(size):
    for v in range(1, 11):
        bits = 4 + (8 if v < 10 else 16) + 8 * size
        if bits <= _data_capacity(v) * 8:
            return v
    raise ValueError("内容过长，二维码版本 10 也放不下")


def _data_capacity(version):
    return sum(count * size for count, size in BLOCKS[version][1])


def _codewords(data, version):
    capacity = _data_capacity(version)
    count_bits = 8 if version < 10 else 16
    bits = [0, 1, 0, 0]
    bits += [(len(data) >> i) & 1 for i in range(count_bits - 1, -1, -1)]
    for byte in data:
        bits += [(byte >> i) & 1 for i in range(7, -1, -1)]
    total = capacity * 8
    bits += [0] * min(4, total - len(bits))
    while len(bits) % 8:
        bits.append(0)
    words = [int("".join(str(b) for b in bits[i:i + 8]), 2)
             for i in range(0, len(bits), 8)]
    pad = (0xEC, 0x11)
    pad_index = 0
    while len(words) < capacity:
        words.append(pad[pad_index % 2])
        pad_index += 1
    return _interleave(words, version)


def _interleave(words, version):
    ec_degree, groups = BLOCKS[version]
    blocks = []
    offset = 0
    for count, size in groups:
        for _ in range(count):
            chunk = words[offset:offset + size]
            offset += size
            blocks.append((chunk, _ec_bytes(chunk, ec_degree)))
    out = []
    for i in range(max(len(d) for d, _ in blocks)):
        for data, _ in blocks:
            if i < len(data):
                out.append(data[i])
    for i in range(ec_degree):
        for _, ec in blocks:
            out.append(ec[i])
    return out


def _poly_mul(p, q):
    result = [0] * (len(p) + len(q) - 1)
    for i, a in enumerate(p):
        if not a:
            continue
        for j, b in enumerate(q):
            if b:
                result[i + j] ^= _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]
    return result


def _generator(degree):
    poly = [1]
    for i in range(degree):
        poly = _poly_mul(poly, [1, _GF_EXP[i]])
    return poly


def _ec_bytes(data, degree):
    gen = _generator(degree)
    rem = list(data) + [0] * degree
    for i in range(len(data)):
        factor = rem[i]
        if not factor:
            continue
        for j, g in enumerate(gen):
            if g:
                rem[i + j] ^= _GF_EXP[_GF_LOG[factor] + _GF_LOG[g]]
    return rem[-degree:]


def _matrix(version, codewords):
    n = 17 + 4 * version
    base = _function_matrix(version, n)
    best_mask, best_score = 0, None
    for mask in range(8):
        # 与 qrcode.js 一致：择优时格式/版本信息区先按“全白”评估，
        # 选完掩码再写入真实格式信息（否则掩码得分会和内置实现分叉）。
        candidate = _place_data([row[:] for row in base], codewords, mask)
        score = _penalty(candidate)
        if best_score is None or score < best_score:
            best_mask, best_score = mask, score
    final = _place_data([row[:] for row in base], codewords, best_mask)
    _write_format(final, best_mask)
    if version >= 7:
        _write_version(final, version)
    final[n - 8][8] = 1
    return final


def _function_matrix(version, n):
    m = [[None] * n for _ in range(n)]

    def put(r, c, value):
        if 0 <= r < n and 0 <= c < n:
            m[r][c] = value

    def finder(top, left):
        for r in range(-1, 8):
            for c in range(-1, 8):
                dark = (0 <= r <= 6 and (c in (0, 6))
                        or 0 <= c <= 6 and (r in (0, 6))
                        or 2 <= r <= 4 and 2 <= c <= 4)
                put(top + r, left + c, 1 if dark else 0)

    finder(0, 0)
    finder(0, n - 7)
    finder(n - 7, 0)
    for r in ALIGN[version]:
        for c in ALIGN[version]:
            if m[r][c] is not None:
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    edge = max(abs(dr), abs(dc))
                    m[r + dr][c + dc] = 1 if edge in (0, 2) else 0
    for i in range(8, n - 8):
        m[i][6] = 1 if i % 2 == 0 else 0
        m[6][i] = 1 if i % 2 == 0 else 0
    # 格式/版本信息区先占位（全白），数据位才不会落进去
    for r, c in _format_cells(n):
        m[r][c] = 0
    m[n - 8][8] = 0
    if version >= 7:
        for r, c in _version_cells(n):
            m[r][c] = 0
    return m


def _place_data(m, codewords, mask):
    n = len(m)
    row, inc, byte, bit = n - 1, -1, 0, 7
    col = n - 1
    while col > 0:
        if col == 6:
            col -= 1
        while True:
            for c in (0, 1):
                if m[row][col - c] is None:
                    dark = ((codewords[byte] >> bit) & 1
                            if byte < len(codewords) else 0)
                    if _mask_bit(mask, row, col - c):
                        dark ^= 1
                    m[row][col - c] = dark
                    bit -= 1
                    if bit < 0:
                        byte += 1
                        bit = 7
            row += inc
            if row < 0 or row >= n:
                row -= inc
                inc = -inc
                break
        col -= 2
    return m


def _mask_bit(mask, r, c):
    if mask == 0:
        return (r + c) % 2 == 0
    if mask == 1:
        return r % 2 == 0
    if mask == 2:
        return c % 3 == 0
    if mask == 3:
        return (r + c) % 3 == 0
    if mask == 4:
        return (r // 2 + c // 3) % 2 == 0
    if mask == 5:
        return (r * c) % 2 + (r * c) % 3 == 0
    if mask == 6:
        return ((r * c) % 2 + (r * c) % 3) % 2 == 0
    return ((r + c) % 2 + (r * c) % 3) % 2 == 0


def _format_cells(n):
    for i in range(15):
        if i < 6:
            yield i, 8
        elif i < 8:
            yield i + 1, 8
        else:
            yield n - 15 + i, 8
    for i in range(15):
        if i < 8:
            yield 8, n - i - 1
        elif i < 9:
            yield 8, 7
        else:
            yield 8, 15 - i - 1


def _version_cells(n):
    for i in range(18):
        yield i // 3, i % 3 + n - 11
        yield i % 3 + n - 11, i // 3


def _write_format(m, mask):
    bits = _bch_format((EC_M << 3) | mask)
    for i, (r, c) in enumerate(_format_cells(len(m))):
        m[r][c] = (bits >> (i % 15)) & 1


def _write_version(m, version):
    bits = _bch_version(version)
    for i, (r, c) in enumerate(_version_cells(len(m))):
        m[r][c] = (bits >> (i // 2)) & 1


def _bit_length(value):
    return value.bit_length()


def _bch_format(data):
    value = data << 10
    while _bit_length(value) >= _bit_length(0x537):
        value ^= 0x537 << (_bit_length(value) - 11)
    return ((data << 10) | value) ^ 0x5412


def _bch_version(version):
    value = version << 12
    while _bit_length(value) >= _bit_length(0x1f25):
        value ^= 0x1f25 << (_bit_length(value) - 13)
    return (version << 12) | value


def _penalty(m):
    """掩码择优罚分，与内置 ui/vendor/qrcode.js 同款，保证 CLI 和控制台
    生成的二维码矩阵一致（控制台分享图用的就是那份实现）。"""
    n = len(m)
    score = 0
    for r in range(n):
        for c in range(n):
            same = 0
            dark = m[r][c]
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == dc == 0:
                        continue
                    rr, cc = r + dr, c + dc
                    if 0 <= rr < n and 0 <= cc < n and m[rr][cc] == dark:
                        same += 1
            if same > 5:
                score += 3 + same - 5
    for r in range(n - 1):
        for c in range(n - 1):
            if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                score += 3
    pattern = [1, 0, 1, 1, 1, 0, 1]
    for line in list(m) + [list(col) for col in zip(*m)]:
        for i in range(n - 6):
            if line[i:i + 7] == pattern:
                score += 40
    dark = sum(sum(row) for row in m)
    score += abs(100 * dark / (n * n) - 50) * 2
    return score
