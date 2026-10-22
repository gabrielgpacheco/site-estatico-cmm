# -*- coding: utf-8 -*-
"""Leitura de dumps MySQL (mysqldump) sem servidor MySQL."""
import gzip
import re

ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "Z": "\x1a", "b": "\b"}


def parse_values(s):
    """Converte o trecho apos VALUES em lista de linhas (listas de strings)."""
    rows = []
    i = 0
    n = len(s)
    while i < n:
        while i < n and s[i] in " ,\r\n\t":
            i += 1
        if i >= n or s[i] != "(":
            break
        i += 1
        vals = []
        cur = []
        isstr = False
        while i < n:
            c = s[i]
            if isstr:
                if c == "\\":
                    nxt = s[i + 1] if i + 1 < n else ""
                    cur.append(ESCAPES.get(nxt, nxt))
                    i += 2
                    continue
                if c == "'":
                    if i + 1 < n and s[i + 1] == "'":
                        cur.append("'")
                        i += 2
                        continue
                    isstr = False
                    i += 1
                    continue
                cur.append(c)
                i += 1
                continue
            if c == "'":
                isstr = True
                i += 1
                continue
            if c == ",":
                vals.append("".join(cur))
                cur = []
                i += 1
                continue
            if c == ")":
                vals.append("".join(cur))
                i += 1
                break
            cur.append(c)
            i += 1
        rows.append(vals)
    return rows


def insert_rows(line):
    k = line.find(" VALUES ")
    if k < 0:
        return []
    return parse_values(line[k + 8:])


def load_tables(path, tables, prefix="wp4LG7q9Gf_"):
    """Le o dump uma vez e devolve {tabela: [linhas]} apenas para `tables`."""
    wanted = {prefix + t: t for t in tables}
    out = {t: [] for t in tables}
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.startswith("INSERT INTO `"):
                continue
            end = line.find("`", 13)
            if end < 0:
                continue
            table = line[13:end]
            key = wanted.get(table)
            if key is None:
                continue
            rows = insert_rows(line)
            if rows:
                out[key].extend(rows)
    return out


def php_unserialize(data):
    """Unserialize minimo de PHP (a, s, i, d, b, N, O). Byte-safe."""
    if data is None:
        return None
    if isinstance(data, str):
        data = data.encode("utf-8")
    try:
        val, _ = _php_parse(data, 0)
        return val
    except Exception:
        return None


def _php_parse(b, i):
    t = b[i:i + 1]
    if t == b"N":
        return None, i + 2
    if t == b"b":
        j = b.index(b";", i)
        return b[i + 2:j] == b"1", j + 1
    if t == b"i":
        j = b.index(b";", i)
        return int(b[i + 2:j]), j + 1
    if t == b"d":
        j = b.index(b";", i)
        return float(b[i + 2:j]), j + 1
    if t == b"s":
        j = b.index(b":", i + 2)
        ln = int(b[i + 2:j])
        start = j + 2
        end = start + ln
        return b[start:end].decode("utf-8", "replace"), end + 2
    if t == b"a":
        j = b.index(b":", i + 2)
        count = int(b[i + 2:j])
        i = j + 2
        result = {}
        for _ in range(count):
            key, i = _php_parse(b, i)
            val, i = _php_parse(b, i)
            result[key] = val
        return result, i + 1
    if t == b"O":
        j = b.index(b":", i + 2)
        name_len = int(b[i + 2:j])
        start = j + 2
        name = b[start:start + name_len].decode("utf-8", "replace")
        i = start + name_len + 2
        j = b.index(b":", i)
        count = int(b[i:j])
        i = j + 2
        result = {"__class__": name}
        for _ in range(count):
            key, i = _php_parse(b, i)
            val, i = _php_parse(b, i)
            result[key] = val
        return result, i + 1
    raise ValueError("tipo PHP desconhecido: %r em %d" % (t, i))


def table_prefix(path):
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = re.match(r"INSERT INTO `([^`]+?)_options`", line)
            if m:
                return m.group(1) + "_"
    return "wp_"
