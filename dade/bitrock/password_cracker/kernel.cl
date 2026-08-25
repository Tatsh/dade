// Password-verification kernel for encrypted InstallBuilder installers (CUDA and OpenCL).
//
// This is a straight port of bitrock.crypto.verify_password: SHA-256, the Twofish block cipher,
// CBC mode, and the InstallBuilder key-derivation loop. The Twofish byte permutations (QT, QSEQ)
// and matrices (MDS, RS), the reduction polynomials, and the buffer sizes are injected by
// bitrock.password_cracker from the constants in bitrock.crypto, so the device and CPU cannot
// diverge. The comment-style tokens below are placeholders replaced at build time.
//
// A single source targets both back ends: the prelude below defines macros that bridge the CUDA
// (nvrtc) and OpenCL dialects, and the kernel copies its inputs into private arrays so no generic
// address space is needed (OpenCL before 2.0 has none). CUDA tolerates the extra copies.

#ifdef __OPENCL_VERSION__
typedef uchar u8;
typedef uint u32;
typedef ulong u64;
#define DEVICE
#define KERNEL __kernel
#define CONSTANT __constant
#define CONSTPTR __constant
#define GLOBAL __global
#define GLOBAL_ID ((int)get_global_id(0))
#define FOUND volatile __global int
#define ATOMIC_CAS(p, cmp, val) atomic_cmpxchg((p), (cmp), (val))
#else
typedef unsigned char u8;
typedef unsigned int u32;
typedef unsigned long long u64;
#define DEVICE __device__
#define KERNEL extern "C" __global__
#define CONSTANT __device__ __constant__
#define CONSTPTR
#define GLOBAL
#define GLOBAL_ID (blockIdx.x * blockDim.x + threadIdx.x)
#define FOUND int
#define ATOMIC_CAS(p, cmp, val) atomicCAS((p), (cmp), (val))
#endif

/*TABLES*/

#define MDS_POLY     /*MDS_POLY*/
#define RS_POLY      /*RS_POLY*/
#define MAX_PASSWORD /*MAX_PASSWORD*/
#define MAX_IV_POOL  /*MAX_IV_POOL*/

DEVICE u32 rotr(u32 v, int n) {
    return (v >> n) | (v << (32 - n));
}
DEVICE u32 rotl(u32 v, int n) {
    return (v << n) | (v >> (32 - n));
}

/* ---- SHA-256 ---- */
CONSTANT u32 K256[64] = {
    0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u, 0x3956c25bu, 0x59f111f1u, 0x923f82a4u,
    0xab1c5ed5u, 0xd807aa98u, 0x12835b01u, 0x243185beu, 0x550c7dc3u, 0x72be5d74u, 0x80deb1feu,
    0x9bdc06a7u, 0xc19bf174u, 0xe49b69c1u, 0xefbe4786u, 0x0fc19dc6u, 0x240ca1ccu, 0x2de92c6fu,
    0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau, 0x983e5152u, 0xa831c66du, 0xb00327c8u, 0xbf597fc7u,
    0xc6e00bf3u, 0xd5a79147u, 0x06ca6351u, 0x14292967u, 0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu,
    0x53380d13u, 0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u, 0xa2bfe8a1u, 0xa81a664bu,
    0xc24b8b70u, 0xc76c51a3u, 0xd192e819u, 0xd6990624u, 0xf40e3585u, 0x106aa070u, 0x19a4c116u,
    0x1e376c08u, 0x2748774cu, 0x34b0bcb5u, 0x391c0cb3u, 0x4ed8aa4au, 0x5b9cca4fu, 0x682e6ff3u,
    0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u, 0x90befffau, 0xa4506cebu, 0xbef9a3f7u,
    0xc67178f2u};

DEVICE void sha256_block(u32 h[8], const u8 *block) {
    u32 w[64];
    for (int i = 0; i < 16; ++i) {
        w[i] = (block[i * 4] << 24) | (block[i * 4 + 1] << 16) | (block[i * 4 + 2] << 8) |
               block[i * 4 + 3];
    }
    for (int i = 16; i < 64; ++i) {
        u32 s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
        u32 s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    u32 a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
    for (int i = 0; i < 64; ++i) {
        u32 S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
        u32 ch = (e & f) ^ ((~e) & g);
        u32 t1 = hh + S1 + ch + K256[i] + w[i];
        u32 S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
        u32 maj = (a & b) ^ (a & c) ^ (b & c);
        u32 t2 = S0 + maj;
        hh = g;
        g = f;
        f = e;
        e = d + t1;
        d = c;
        c = b;
        b = a;
        a = t1 + t2;
    }
    h[0] += a;
    h[1] += b;
    h[2] += c;
    h[3] += d;
    h[4] += e;
    h[5] += f;
    h[6] += g;
    h[7] += hh;
}

DEVICE void sha256(const u8 *msg, int len, u8 out[32]) {
    u32 h[8] = {0x6a09e667u,
                0xbb67ae85u,
                0x3c6ef372u,
                0xa54ff53au,
                0x510e527fu,
                0x9b05688cu,
                0x1f83d9abu,
                0x5be0cd19u};
    int full = len / 64;
    for (int b = 0; b < full; ++b) {
        sha256_block(h, msg + b * 64);
    }
    u8 tail[128];
    int rem = len - full * 64;
    for (int i = 0; i < rem; ++i) {
        tail[i] = msg[full * 64 + i];
    }
    tail[rem] = 0x80;
    int total = (rem < 56) ? 64 : 128;
    for (int i = rem + 1; i < total - 8; ++i) {
        tail[i] = 0;
    }
    u64 bits = (u64)len * 8;
    for (int i = 0; i < 8; ++i) {
        tail[total - 1 - i] = (u8)(bits >> (i * 8));
    }
    sha256_block(h, tail);
    if (total == 128) {
        sha256_block(h, tail + 64);
    }
    for (int i = 0; i < 8; ++i) {
        out[i * 4] = (u8)(h[i] >> 24);
        out[i * 4 + 1] = (u8)(h[i] >> 16);
        out[i * 4 + 2] = (u8)(h[i] >> 8);
        out[i * 4 + 3] = (u8)h[i];
    }
}

/* ---- Twofish ---- */
DEVICE u8 gf_mul(u8 a, u8 b, int mod) {
    u8 r = 0;
    for (int i = 0; i < 8; ++i) {
        if (b & 1) {
            r ^= a;
        }
        b >>= 1;
        u8 hi = a & 0x80;
        a = (u8)(a << 1);
        if (hi) {
            a ^= (u8)(mod & 0xFF);
        }
    }
    return r;
}
DEVICE u32 mat_mul(CONSTPTR u8 *m, int rows, int cols, const u8 *v, int mod) {
    u32 out = 0;
    for (int i = 0; i < rows; ++i) {
        u8 acc = 0;
        for (int j = 0; j < cols; ++j) {
            acc ^= gf_mul(m[i * cols + j], v[j], mod);
        }
        out |= ((u32)acc) << (8 * i);
    }
    return out;
}

typedef struct {
    int k;
    u32 sbox[4];
    u32 subkeys[40];
} Twofish;

/* q permutation for byte `position`; QSEQ picks Q0/Q1 per stage, injected from crypto.py. */
DEVICE u8 tf_permute(int position, u8 byte_, const u32 *kw, int k) {
    int base = position * 5;
    int shift = 8 * position;
    u8 r = byte_;
    if (k == 4) {
        r = QT[QSEQ[base + 0] * 256 + r] ^ (u8)(kw[3] >> shift);
    }
    if (k >= 3) {
        r = QT[QSEQ[base + 1] * 256 + r] ^ (u8)(kw[2] >> shift);
    }
    r = QT[QSEQ[base + 2] * 256 + r] ^ (u8)(kw[1] >> shift);
    r = QT[QSEQ[base + 3] * 256 + r] ^ (u8)(kw[0] >> shift);
    return QT[QSEQ[base + 4] * 256 + r];
}

DEVICE u32 tf_h(u32 word, const u32 *kw, int k) {
    u8 y[4];
    for (int i = 0; i < 4; ++i) {
        y[i] = tf_permute(i, (u8)(word >> (8 * i)), kw, k);
    }
    return mat_mul(MDS, 4, 4, y, MDS_POLY);
}

DEVICE void tf_init(Twofish *t, const u8 *key, int keylen) {
    int k = keylen / 8;
    t->k = k;
    u32 me[4], mo[4];
    for (int i = 0; i < 2 * k; ++i) {
        u32 w = key[4 * i] | (key[4 * i + 1] << 8) | (key[4 * i + 2] << 16) |
                ((u32)key[4 * i + 3] << 24);
        if (i & 1) {
            mo[i / 2] = w;
        } else {
            me[i / 2] = w;
        }
    }
    for (int i = 0; i < k; ++i) {
        u8 chunk[8];
        for (int j = 0; j < 8; ++j) {
            chunk[j] = key[8 * (k - 1 - i) + j];
        }
        t->sbox[i] = mat_mul(RS, 4, 8, chunk, RS_POLY);
    }
    const u32 RHO = 0x01010101u;
    for (int i = 0; i < 20; ++i) {
        u32 a = tf_h((2 * i) * RHO, me, k);
        u32 b = rotl(tf_h((2 * i + 1) * RHO, mo, k), 8);
        t->subkeys[2 * i] = a + b;
        t->subkeys[2 * i + 1] = rotl(a + 2 * b, 9);
    }
}

DEVICE u32 tf_g(const Twofish *t, u32 word) {
    u8 y[4];
    for (int i = 0; i < 4; ++i) {
        y[i] = tf_permute(i, (u8)(word >> (8 * i)), t->sbox, t->k);
    }
    return mat_mul(MDS, 4, 4, y, MDS_POLY);
}

DEVICE void tf_encrypt(const Twofish *t, const u8 in[16], u8 out[16]) {
    u32 r[4];
    for (int i = 0; i < 4; ++i) {
        r[i] = (in[4 * i] | (in[4 * i + 1] << 8) | (in[4 * i + 2] << 16) |
                ((u32)in[4 * i + 3] << 24)) ^
               t->subkeys[i];
    }
    for (int rnd = 0; rnd < 16; ++rnd) {
        u32 t0 = tf_g(t, r[0]);
        u32 t1 = tf_g(t, rotl(r[1], 8));
        u32 f0 = t0 + t1 + t->subkeys[2 * rnd + 8];
        u32 f1 = t0 + 2 * t1 + t->subkeys[2 * rnd + 9];
        u32 n0 = rotr(r[2] ^ f0, 1);
        u32 n1 = rotl(r[3], 1) ^ f1;
        r[2] = r[0];
        r[3] = r[1];
        r[0] = n0;
        r[1] = n1;
    }
    u32 out_w[4] = {r[2], r[3], r[0], r[1]};
    for (int i = 0; i < 4; ++i) {
        u32 v = out_w[i] ^ t->subkeys[i + 4];
        out[4 * i] = (u8)v;
        out[4 * i + 1] = (u8)(v >> 8);
        out[4 * i + 2] = (u8)(v >> 16);
        out[4 * i + 3] = (u8)(v >> 24);
    }
}

DEVICE void tf_decrypt(const Twofish *t, const u8 in[16], u8 out[16]) {
    u32 r[4];
    for (int i = 0; i < 4; ++i) {
        r[i] = (in[4 * i] | (in[4 * i + 1] << 8) | (in[4 * i + 2] << 16) |
                ((u32)in[4 * i + 3] << 24)) ^
               t->subkeys[i + 4];
    }
    u32 tmp0 = r[2], tmp1 = r[3];
    r[2] = r[0];
    r[3] = r[1];
    r[0] = tmp0;
    r[1] = tmp1;
    for (int rnd = 15; rnd >= 0; --rnd) {
        u32 t0 = tf_g(t, r[2]);
        u32 t1 = tf_g(t, rotl(r[3], 8));
        u32 f0 = t0 + t1 + t->subkeys[2 * rnd + 8];
        u32 f1 = t0 + 2 * t1 + t->subkeys[2 * rnd + 9];
        u32 n2 = rotl(r[0], 1) ^ f0;
        u32 n3 = rotr(r[1] ^ f1, 1);
        r[0] = r[2];
        r[1] = r[3];
        r[2] = n2;
        r[3] = n3;
    }
    for (int i = 0; i < 4; ++i) {
        u32 v = r[i] ^ t->subkeys[i];
        out[4 * i] = (u8)v;
        out[4 * i + 1] = (u8)(v >> 8);
        out[4 * i + 2] = (u8)(v >> 16);
        out[4 * i + 3] = (u8)(v >> 24);
    }
}

DEVICE void cbc_encrypt(const Twofish *t, const u8 *iv, u8 *buf, int len) {
    u8 prev[16];
    for (int i = 0; i < 16; ++i) {
        prev[i] = iv[i];
    }
    for (int off = 0; off < len; off += 16) {
        u8 blk[16];
        for (int i = 0; i < 16; ++i) {
            blk[i] = buf[off + i] ^ prev[i];
        }
        tf_encrypt(t, blk, prev);
        for (int i = 0; i < 16; ++i) {
            buf[off + i] = prev[i];
        }
    }
}

DEVICE void cbc_decrypt(const Twofish *t, const u8 *iv, u8 *buf, int len) {
    u8 prev[16], cur[16], out[16];
    for (int i = 0; i < 16; ++i) {
        prev[i] = iv[i];
    }
    for (int off = 0; off < len; off += 16) {
        for (int i = 0; i < 16; ++i) {
            cur[i] = buf[off + i];
        }
        tf_decrypt(t, cur, out);
        for (int i = 0; i < 16; ++i) {
            buf[off + i] = out[i] ^ prev[i];
            prev[i] = cur[i];
        }
    }
}

KERNEL void crack_kernel(GLOBAL const u8 *passwords,
                         GLOBAL const int *lengths,
                         int count,
                         GLOBAL const u8 *password_key,
                         GLOBAL const u8 *iv,
                         int times,
                         GLOBAL const u8 *encrypted_key,
                         GLOBAL const u8 *ivs_hash,
                         GLOBAL const u8 *encrypted_ivs,
                         int ivs_len,
                         FOUND *found_index) {
    int idx = GLOBAL_ID;
    if (idx >= count || *found_index >= 0) {
        return;
    }
    u8 pw[MAX_PASSWORD];
    int pwlen = lengths[idx];
    for (int i = 0; i < pwlen; ++i) {
        pw[i] = passwords[(size_t)idx * MAX_PASSWORD + i];
    }
    u8 pk_key[32];
    for (int i = 0; i < 32; ++i) {
        pk_key[i] = password_key[i];
    }
    u8 digest[32];
    sha256(pw, pwlen, digest);
    Twofish pk;
    tf_init(&pk, pk_key, 32);
    u8 cur_iv[16];
    for (int i = 0; i < 16; ++i) {
        cur_iv[i] = iv[i];
    }
    for (int it = 0; it < times; ++it) {
        cbc_encrypt(&pk, cur_iv, digest, 32);
        for (int i = 0; i < 16; ++i) {
            cur_iv[i] = digest[16 + i];
        }
    }
    u8 derived_key[32];
    sha256(digest, 32, derived_key);
    Twofish derived;
    tf_init(&derived, derived_key, 32);
    u8 key_blob[64];
    for (int i = 0; i < 64; ++i) {
        key_blob[i] = encrypted_key[i];
    }
    u8 zero_iv[16];
    for (int i = 0; i < 16; ++i) {
        zero_iv[i] = 0;
    }
    cbc_decrypt(&derived, zero_iv, key_blob, 64);
    u8 payload_key[32];
    for (int i = 0; i < 32; ++i) {
        payload_key[i] = key_blob[32 + i];
    }
    Twofish pkey;
    tf_init(&pkey, payload_key, 32);
    u8 buffer[MAX_IV_POOL];
    for (int i = 0; i < ivs_len; ++i) {
        buffer[i] = encrypted_ivs[i];
    }
    for (int it = 0; it < times; it += 64) {
        cbc_decrypt(&pkey, zero_iv, buffer, ivs_len);
    }
    u8 check[32];
    sha256(buffer + 32, ivs_len - 32, check);
    bool match = true;
    for (int i = 0; i < 32; ++i) {
        if (check[i] != ivs_hash[i]) {
            match = false;
            break;
        }
    }
    if (match) {
        ATOMIC_CAS(found_index, -1, idx);
    }
}
