"""验证 XXTEA 实现: 用 C# Encrypt 逻辑加密 -> 用我的 Decrypt 解密, 应还原原文"""
import base64
from pathlib import Path

from tea_decrypt import to_longs, to_bytes, xxtea_decrypt, KEY, DELTA, MASK


def csharp_encrypt(plaintext: bytes, key: bytes) -> bytes:
    """严格按 C# TeaEncryptor.Encrypt 实现
    C# 变量: num2 = z, num3 = y
    """
    v = to_longs(plaintext)
    k = to_longs(key)
    n = len(v)
    z = v[n - 1]  # num2 = v[n-1]
    y = v[0]      # num3 = v[0]
    rounds = 6 + 52 // n
    summ = 0
    for _ in range(rounds):
        summ = (summ + DELTA) & MASK
        e = (summ >> 2) & 3
        for p in range(n - 1):
            y = v[p + 1]                      # num3 = v[p+1]
            mx = ((((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ ((summ ^ y) + (k[(p & 3) ^ e] ^ z))) & MASK
            v[p] = (v[p] + mx) & MASK
            z = v[p]                          # num2 = new v[p]
        y = v[0]                              # num3 = v[0]
        mx = ((((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ ((summ ^ y) + (k[((n - 1) & 3) ^ e] ^ z))) & MASK
        v[n - 1] = (v[n - 1] + mx) & MASK
        z = v[n - 1]                          # num2 = new v[n-1]
    return to_bytes(v)


def test_roundtrip():
    samples = [
        b"<data><general gameVersion='1.0'/></data>",
        "Hello, Obra Dinn! 测试中文内容 & <>&\"'".encode("utf-8"),
        bytes(range(256)) * 5,  # 所有字节值
    ]
    # 长度需为 4 的倍数
    for s in samples:
        if len(s) % 4:
            s += b"\x00" * (4 - len(s) % 4)
        ct = csharp_encrypt(s, KEY)
        v = to_longs(ct)
        k = to_longs(KEY)
        pt = to_bytes(xxtea_decrypt(v, k))
        ok = pt == s
        print(f"[{'OK' if ok else 'FAIL'}] len={len(s)}  roundtrip={'成功' if ok else '失败'}")
        if not ok:
            print(f"    原文: {s[:40]!r}")
            print(f"    解密: {pt[:40]!r}")
    print("\n[结论] 如果上面都是 OK, 说明算法实现正确; 若存档仍解不开则问题在别处(密钥/数据)")


if __name__ == "__main__":
    test_roundtrip()
