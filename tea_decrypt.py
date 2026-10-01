"""XXTEA 解密 Obra Dinn 存档 data 块
根据 TeaEncryptor 反编译源码:
- 算法: XXTEA (Corrected Block TEA), q = 6 + 52/n 轮, DELTA = 0x9E3779B9
- 密钥: "d080-esc" + "d090-fat" = "d080-escd090-fat" (16字节, UTF-8)
- 小端 uint32 数组 (ToLongs / ToBytes)
- 解密后 UTF-8 解码并 TrimEnd('\\0')
"""
import base64
import re
from pathlib import Path

SAVE = Path(__file__).parent / "ObraDinnSave-P2.txt"
KEY = b"d080-escd090-fat"  # 16 字节
DELTA = 0x9E3779B9
MASK = 0xFFFFFFFF


def to_longs(data: bytes):
    """小端字节 -> uint32 数组 (C# ToLongs)"""
    n = (len(data) + 3) // 4
    out = []
    for i in range(n):
        w = 0
        for j in range(4):
            idx = i * 4 + j
            if idx < len(data):
                w |= data[idx] << (8 * j)
        out.append(w)
    return out


def to_bytes(arr):
    """uint32 数组 -> 小端字节 (C# ToBytes)"""
    return b"".join(x.to_bytes(4, "little") for x in arr)


def xxtea_decrypt(v, k):
    """XXTEA 解密 (就地修改 v)
    注意: y 是运行中的值, 每轮更新为新的 v[p], 供下一轮 MX 使用
    """
    n = len(v)
    if n < 2:
        return v
    q = 6 + 52 // n
    y = v[0]
    summ = (q * DELTA) & MASK
    while summ != 0:
        e = (summ >> 2) & 3
        p = n - 1
        while p > 0:
            z = v[p - 1]
            mx = ((((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ ((summ ^ y) + (k[(p & 3) ^ e] ^ z))) & MASK
            y = v[p] = (v[p] - mx) & MASK
            p -= 1
        z = v[n - 1]
        mx = ((((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ ((summ ^ y) + (k[(0 & 3) ^ e] ^ z))) & MASK
        y = v[0] = (v[0] - mx) & MASK
        summ = (summ - DELTA) & MASK
    return v


def decrypt(encrypted_b64: str) -> bytes:
    data = base64.b64decode(encrypted_b64)
    print(f"[i] 密文长度: {len(data)} 字节 ({len(data)//4} 个 uint32)")
    if len(data) % 4 != 0:
        print("[!] 警告: 长度不是 4 的倍数")

    v = to_longs(data)
    k = to_longs(KEY)
    v = xxtea_decrypt(v, k)
    return to_bytes(v)


def main():
    text = SAVE.read_text(encoding="iso-8859-1")
    m = re.search(r"<data>(.*?)</data>", text, re.S)
    if not m:
        print("[-] 未找到 <data> 块")
        return
    b64 = m.group(1).strip()

    plain = decrypt(b64)
    # C# 端: _encoding.GetString(ToBytes(array)).TrimEnd('\0')
    xml_text = plain.decode("utf-8", errors="replace").rstrip("\x00")

    printable = sum(1 for b in plain if 32 <= b < 127 or b in (9, 10, 13))
    print(f"[i] 可打印字符占比: {printable/len(plain):.2%}")
    print(f"[i] 明文长度: {len(plain)} 字节")
    print("\n=== 明文前 500 字符 ===")
    print(xml_text[:500])

    out = Path(__file__).parent / "decrypted_data.xml"
    out.write_text(xml_text, encoding="utf-8")
    print(f"\n[+] 明文已保存: {out}")


if __name__ == "__main__":
    main()
