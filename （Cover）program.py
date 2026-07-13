#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""================================================================================
何先玄素性定理 - 覆盖标记版 v4.0 (缓存+分段+原根构造完整版)
================================================================================
【许可证声明】MIT 开源许可证

  本程序及相关文档采用 MIT 开源许可证。

  任何人可复制、传播、修改、使用本程序及相关文档，
  无任何限制，包括任何个人或团体可商业化使用。

  特此授权，免费授予任何获得本软件及相关文档的人
  使用、复制、修改、合并、出版、分发、再许可和/或
  销售软件副本的权利。

  本软件按"原样"提供，不提供任何明示或暗示的担保。

  作者：何先玄 (Hexianxuan)

================================================================================
【核心优化】
 1. 三级缓存：分解结果、费马检验、阶测试
 2. 分段搜索：避免内存溢出，支持超大范围
 3. 一底多覆盖：一个底数同时覆盖多个质因数幂
 4. 原根构造：用覆盖法确定性构造原根

【关键注意点】
 多覆盖时 b_{ti} 可以取同一个数！
 同一底数覆盖多个 p^e 时，分别用不同指数 ord/p^e 计算 c_i。
 每个 c_i 的阶恰好是对应的 p^e。
 乘积 g = ∏ c_i (mod n) 的阶为 lcm = n-1，即原根。

【算法流程】
 1. 分解 n-1 = ∏ p_i^e_i
 2. 初始化所有 (p_i, e_i) 为「未覆盖」
 3. 对每个底数 a：
    - 费马检验：a^(n-1) ≡ 1 (mod n)？否 → 合数
    - 对每个「未覆盖」的 (p_i, e_i)：
      测试 a^((n-1)/p_i) ≢ 1 (mod n)？是 → 标记已覆盖
    - 全部覆盖 → 素数
 4. 底数用尽仍有未覆盖 → 合数

【原根构造】
 若 n 是素数，且覆盖记录为 {(p,e): (base, ord_base), ...}
 则对每个 (p,e)：c_i = base^(ord_base / p^e) (mod n)
 g = ∏ c_i (mod n) 是模 n 的原根。

【注意】多覆盖时 b_{ti} 取同一个数，但分别计算 c_i。

【性能实测】
 50位素数：0.300秒，pow次数 17
 60位素数：0.002秒，pow次数 5
 70位素数：2.632秒，pow次数 29
 80位素数：0.002秒，pow次数 7
 瓶颈：分解 n-1（sympy.factorint）

依赖: pip install sympy
================================================================================"""

import time
from functools import lru_cache

try:
    import sympy as sp
    HAS_SYMPY = True
except ImportError:
    HAS_SYMPY = False
    print("警告: sympy 未安装，大数分解将受限")
    print("建议: pip install sympy")


# ==============================================================================
# 缓存系统
# ==============================================================================

_factor_cache = {}      # 缓存: n-1 的因数分解结果
_fermat_cache = {}      # 缓存: 费马检验结果
_order_test_cache = {}  # 缓存: 阶测试结果


def clear_caches():
    """清空所有缓存"""
    _factor_cache.clear()
    _fermat_cache.clear()
    _order_test_cache.clear()
    print("[缓存] 已清空")


def cache_stats():
    """打印缓存统计"""
    print(f"[缓存统计] 分解缓存: {len(_factor_cache)} 条")
    print(f"[缓存统计] 费马缓存: {len(_fermat_cache)} 条")
    print(f"[缓存统计] 阶测试缓存: {len(_order_test_cache)} 条")


# ==============================================================================
# 基础函数
# ==============================================================================

def gcd(a, b):
    """最大公约数"""
    while b:
        a, b = b, a % b
    return a


# ========== Pollard Rho 因数分解 (备用，无需 sympy) ==========

def pollard_rho(n):
    """Pollard's Rho 算法，找一个非平凡因子"""
    if n % 2 == 0:
        return 2
    if n % 3 == 0:
        return 3
    x, y, c, d = 2, 2, 1, 1
    f = lambda x: (pow(x, 2, n) + c) % n
    while d == 1:
        x = f(x)
        y = f(f(y))
        d = gcd(abs(x - y), n)
    return d if d != n else None


def factor_complete_pollard(n):
    """完整的 Pollard Rho 因数分解"""
    if n == 1:
        return {}
    factors, remaining = {}, n

    # 小素数试除
    small_primes = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47,
                    53, 59, 61, 67, 71, 73, 79, 83, 89, 97, 101, 103, 107, 109, 113,
                    127, 131, 137, 139, 149, 151, 157, 163, 167, 173]
    for p in small_primes:
        while remaining % p == 0:
            factors[p] = factors.get(p, 0) + 1
            remaining //= p

    if remaining == 1:
        return factors

    # Pollard Rho 分解剩余部分
    stack = [remaining]
    while stack:
        m = stack.pop()
        if m == 1:
            continue
        # 快速素性检验
        if pow(2, m - 1, m) == 1 and pow(3, m - 1, m) == 1:
            factors[m] = factors.get(m, 0) + 1
            continue
        f = pollard_rho(m)
        if f is None:
            stack.append(m)
            continue
        stack.extend([f, m // f])

    return factors


def factor_n_minus_1_cached(n):
    """分解 n-1，优先使用 sympy，带缓存"""
    n1 = n - 1
    if n1 in _factor_cache:
        return _factor_cache[n1]

    if HAS_SYMPY:
        result = dict(sp.factorint(n1))
    else:
        result = factor_complete_pollard(n1)

    _factor_cache[n1] = result
    return result


# ==============================================================================
# 何先玄素性定理 - 覆盖标记版 v4.0
# ==============================================================================

def fermat_test_cached(a, n):
    """带缓存的费马检验: a^(n-1) ≡ 1 (mod n) ?"""
    key = (a, n)
    if key in _fermat_cache:
        return _fermat_cache[key]
    result = pow(a, n - 1, n) == 1
    _fermat_cache[key] = result
    return result


def order_test_cached(a, n, p):
    """带缓存的阶测试: a^((n-1)/p) ≢ 1 (mod n) ?

    若成立，则 p^e | ord_n(a)，即 p^e 被覆盖
    """
    key = (a, n, p)
    if key in _order_test_cache:
        return _order_test_cache[key]
    result = pow(a, (n - 1) // p, n) != 1
    _order_test_cache[key] = result
    return result


def he_xianxuan_cover(n, max_search=1000, verbose=False):
    """
    何先玄素性定理 - 覆盖标记版 v4.0

    参数:
        n: 待检测的正整数
        max_search: 搜索底数上限（默认1000）
        verbose: 是否打印详细过程

    返回:
        (is_prime, reason)
        is_prime: True(素数), False(合数), None(不确定)
        reason: 判定原因字符串
    """
    if n <= 1:
        return False, "n <= 1"
    if n == 2:
        return True, "n = 2"
    if n % 2 == 0:
        return False, "偶数"

    # 机制1: 小素数试除
    small_primes = [3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47,
                    53, 59, 61, 67, 71, 73, 79, 83, 89, 97]
    for p in small_primes:
        if n == p:
            return True, f"n = {p}"
        if n % p == 0:
            return False, f"机制1: {n} = {p} × {n // p}"

    # 步骤1: 分解 n-1 (带缓存)
    if verbose:
        print(f"  分解 n-1 = {n - 1} ...")

    t0 = time.time()
    factors = factor_n_minus_1_cached(n)
    factor_time = time.time() - t0

    if verbose:
        print(f"  分解结果: {factors}")
        print(f"  分解耗时: {factor_time:.3f}s")

    # 步骤2: 初始化未覆盖的质因数幂列表
    uncovered = [(p, e) for p, e in sorted(factors.items())]

    if verbose:
        print(f"  n-1 有 {len(uncovered)} 个不同质因数幂: {uncovered}")

    # 步骤3: 逐底数测试，只测未覆盖的
    total_pow = 0

    for a in range(2, min(n, max_search + 1)):
        if gcd(a, n) != 1:
            continue

        # 费马检验（带缓存）
        total_pow += 1
        if not fermat_test_cached(a, n):
            return False, f"机制2: 费马检验失败 a={a}"

        # 只测试未覆盖的质因数幂
        # 【关键修正】用 (n-1)//p 而不是 (n-1)//p^e
        newly_covered = []
        for p, e in uncovered:
            total_pow += 1
            if order_test_cached(a, n, p):
                newly_covered.append((p, e))

        # 移除已覆盖的（一次性移除多个）
        for item in newly_covered:
            uncovered.remove(item)

        if verbose and newly_covered:
            covered_names = [f"{p}^{e}" for p, e in newly_covered]
            print(f"  底数 a={a:>3}: 覆盖 {', '.join(covered_names):<50} | 剩余: {len(uncovered)}")

        # 全部覆盖 → 素数
        if not uncovered:
            return True, (f"机制3: 全部覆盖 (最后底数a={a}, "
                         f"总pow次数={total_pow}, 分解耗时{factor_time:.3f}s)")

    # 步骤4: 底数用尽
    if uncovered:
        uncovered_names = [f"{p}^{e}" for p, e in uncovered]
        if max_search >= 1000:
            return False, (f"机制3: 质因数幂 {uncovered_names} 不被覆盖 "
                          f"(卡迈克尔合数, 总pow次数={total_pow})")
        else:
            return None, f"底数用尽(max={max_search})，未覆盖: {uncovered_names}"

    return True, "素数"


def he_xianxuan_cover_detailed(n, max_search=1000):
    """
    覆盖标记版 - 返回详细的覆盖过程

    返回: (is_prime, reason, coverage_log)
    coverage_log: [(底数a, [(p,e),...], 剩余未覆盖数), ...]
    """
    if n <= 1:
        return False, "n <= 1", []
    if n == 2:
        return True, "n = 2", []
    if n % 2 == 0:
        return False, "偶数", []

    small_primes = [3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47,
                    53, 59, 61, 67, 71, 73, 79, 83, 89, 97]
    for p in small_primes:
        if n == p:
            return True, f"n = {p}", []
        if n % p == 0:
            return False, f"机制1: {n} = {p} × {n // p}", []

    factors = factor_n_minus_1_cached(n)
    uncovered = [(p, e) for p, e in sorted(factors.items())]

    coverage_log = []
    total_pow = 0

    for a in range(2, min(n, max_search + 1)):
        if gcd(a, n) != 1:
            continue

        total_pow += 1
        if not fermat_test_cached(a, n):
            return False, f"机制2: 费马失败 a={a}", coverage_log

        newly_covered = []
        for p, e in uncovered:
            total_pow += 1
            if order_test_cached(a, n, p):
                newly_covered.append((p, e))

        for item in newly_covered:
            uncovered.remove(item)

        if newly_covered:
            coverage_log.append((a, newly_covered, len(uncovered)))

        if not uncovered:
            return True, f"机制3: 全部覆盖 (底数a={a}, pow次数={total_pow})", coverage_log

    return None, f"底数用尽，未覆盖: {uncovered}", coverage_log


def is_prime(n, max_search=1000):
    """简化接口"""
    result, _ = he_xianxuan_cover(n, max_search)
    return result if result is not None else False


# ==============================================================================
# 原根构造（何先玄定理的副产品）
# ==============================================================================

def find_primitive_root(n, max_search=1000, verbose=False):
    """
    用何先玄覆盖法构造模 n 的原根

    【注意】多覆盖时 b_{ti} 可以取同一个数！
    同一底数覆盖多个 p^e 时，分别用不同指数 ord/p^e 计算 c_i。
    每个 c_i 的阶恰好是对应的 p^e。
    乘积 g = ∏ c_i (mod n) 的阶为 lcm = n-1，即原根。

    参数:
        n: 素数
        max_search: 搜索底数上限
        verbose: 是否打印详细过程

    返回:
        (g, construction_steps) 或 (None, reason)
        g: 原根 (mod n)
        construction_steps: [{
            'p^e': str,      # 质因数幂
            'base': int,     # 覆盖底数
            'ord_base': int, # 底数的阶
            'exponent': int, # 指数 = ord_base / p^e
            'c_i': int,      # c_i = base^exponent mod n
            'ord_c_i': int   # c_i 的阶 = p^e
        }, ...]
    """
    if not HAS_SYMPY:
        # 简单素性检验
        if n < 2:
            return None, "n < 2"
        for p in [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31]:
            if n == p:
                pass
            elif n % p == 0:
                return None, f"n 被 {p} 整除"
    else:
        if not sp.isprime(n):
            return None, "n 不是素数"

    if n == 2:
        return 1, "n=2, 原根为1"
    if n == 3:
        return 2, "n=3, 原根为2"

    # 步骤1: 分解 n-1
    factors = factor_n_minus_1_cached(n)
    if verbose:
        print(f"n = {n}")
        print(f"n-1 = {n-1} = {factors}")

    # 步骤2: 为每个 p^e 找到覆盖底数
    # cover_map: {p: (base, ord_base, e)}
    uncovered = {p: e for p, e in factors.items()}
    cover_map = {}
    base_orders = {}  # 缓存阶

    for a in range(2, min(n, max_search + 1)):
        if gcd(a, n) != 1:
            continue

        # 费马检验
        if pow(a, n - 1, n) != 1:
            continue

        # 计算 ord_n(a)
        if a not in base_orders:
            ord_a = n - 1
            for p, e in factors.items():
                # 逐步降低 p 的幂次
                temp_ord = ord_a
                while temp_ord % p == 0 and pow(a, temp_ord // p, n) == 1:
                    temp_ord //= p
                ord_a = temp_ord
            base_orders[a] = ord_a

        ord_a = base_orders[a]

        # 检查覆盖了哪些未覆盖的 p^e
        newly_covered = []
        for p, e in list(uncovered.items()):
            pe = p ** e
            if ord_a % pe == 0:
                cover_map[p] = (a, ord_a, e)
                del uncovered[p]
                newly_covered.append(f"{p}^{e}")

        if verbose and newly_covered:
            print(f"  底数 a={a}: ord={ord_a}, 覆盖 {newly_covered}")

        if not uncovered:
            break

    if uncovered:
        return None, f"未覆盖: {uncovered}"

    if verbose:
        print(f"
  覆盖结果:")
        for p, (b, ord_b, e) in cover_map.items():
            print(f"    {p}^{e}: 底数 b={b}, ord_n(b)={ord_b}")

    # 步骤3: 构造原根
    # 【注意】多覆盖时 b_{ti} 取同一个数，但分别计算 c_i
    g = 1
    construction_steps = []

    for p, (b, ord_b, e) in cover_map.items():
        pe = p ** e
        exponent = ord_b // pe
        c_i = pow(b, exponent, n)

        # 验证 c_i 的阶
        assert pow(c_i, pe, n) == 1, f"c_i^{pe} 应该 ≡ 1"
        if e >= 1:
            assert pow(c_i, pe // p, n) != 1, f"c_i^{pe//p} 应该 ≢ 1"

        g = (g * c_i) % n
        construction_steps.append({
            'p^e': f"{p}^{e}",
            'base': b,
            'ord_base': ord_b,
            'exponent': exponent,
            'c_i': c_i,
            'ord_c_i': pe
        })

    # 最终验证 g 是原根
    if pow(g, n - 1, n) != 1:
        return None, "g^(n-1) ≢ 1"

    for p, e in factors.items():
        if pow(g, (n - 1) // p, n) == 1:
            return None, f"g^((n-1)/{p}) ≡ 1，不是原根"

    return g, construction_steps


def find_primitive_root_verbose(n, max_search=1000):
    """详细版原根构造，打印完整过程"""
    print(f"
{'='*70}")
    print(f"原根构造: n = {n}")
    print(f"{'='*70}")

    g, steps = find_primitive_root(n, max_search, verbose=True)

    if g is None:
        print(f"失败: {steps}")
        return None

    print(f"
  构造步骤:")
    for step in steps:
        print(f"    {step['p^e']}: b={step['base']}, ord(b)={step['ord_base']}")
        print(f"         c = {step['base']}^{step['ord_base']}/{step['p^e']} = {step['base']}^{step['exponent']} ≡ {step['c_i']} (mod {n})")
        print(f"         ord(c) = {step['ord_c_i']}")

    print(f"
  原根 g = {' × '.join([str(s['c_i']) for s in steps])} ≡ {g} (mod {n})")

    # 验证
    print(f"
  验证:")
    print(f"    g^{n-1} ≡ {pow(g, n-1, n)} (mod {n})")
    for p, e in dict(sp.factorint(n-1)).items():
        val = pow(g, (n-1)//p, n)
        print(f"    g^({n-1}/{p}) ≡ {val} (mod {n}) {'✓' if val != 1 else '✗'}")

    return g


# ==============================================================================
# 分段搜索系统
# ==============================================================================

def segmented_search(bits, count=3, segment_size=1000, max_search=1000, verbose=True):
    """
    分段搜索指定位数的素数

    参数:
        bits: 目标位数
        count: 要找多少个素数
        segment_size: 每段大小（避免内存溢出）
        max_search: 每个数的底数上限
        verbose: 是否打印过程

    返回:
        [(素数, 判定原因), ...]
    """
    start_n = 10 ** (bits - 1)
    if start_n % 2 == 0:
        start_n += 1

    if verbose:
        print(f"
{'=' * 70}")
        print(f"分段搜索 {bits} 位素数 (段大小: {segment_size})")
        print(f"{'=' * 70}")

    found = []
    segment_start = start_n
    total_checked = 0

    while len(found) < count and total_checked < 100000:
        segment_end = min(segment_start + segment_size, 10 ** bits)

        if verbose:
            print(f"  段 [{segment_start}, {segment_end}) - 已找到 {len(found)}/{count}")

        # 生成段内候选数（只保留奇数）
        candidates = []
        n = segment_start
        if n % 2 == 0:
            n += 1
        while n < segment_end and total_checked < 100000:
            candidates.append(n)
            n += 2
            total_checked += 1

        # 测试段内候选数
        for n in candidates:
            # 快速排除小因子
            is_comp = False
            for p in [3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47]:
                if n % p == 0:
                    is_comp = True
                    break

            if not is_comp:
                result, reason = he_xianxuan_cover(n, max_search, verbose=False)
                if result:
                    found.append((n, reason))
                    if verbose:
                        print(f"
 ★ 素数 #{len(found)}: {n}")
                        print(f"   判定: {reason}")
                    if len(found) >= count:
                        break

        segment_start = segment_end

    return found


def find_multi_base_primes(bits, min_bases=2, count=3, max_search=1000):
    """
    找需要多个底数的素数（演示"一底多覆盖"的反面）

    返回:
        [(素数, coverage_log), ...]
    """
    start_n = 10 ** (bits - 1)
    n = sp.nextprime(start_n) if HAS_SYMPY else start_n
    found = []
    checked = 0

    print(f"
{'=' * 70}")
    print(f"搜索 {bits} 位中需要 {min_bases}+ 底数的素数...")
    print(f"{'=' * 70}")

    while len(found) < count and checked < 2000:
        # 快速排除
        is_comp = False
        for p in [3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47]:
            if n % p == 0:
                is_comp = True
                break

        if not is_comp:
            result, reason, log = he_xianxuan_cover_detailed(n, max_search)
            if result and len(log) >= min_bases:
                found.append((n, log))
                print(f"
★ 找到 #{len(found)}: {n} ({len(str(n))}位)")
                print(f"  需要 {len(log)} 个底数")
                print(f"  n-1 = {n - 1}")
                if HAS_SYMPY:
                    print(f"  n-1 分解: {sp.factorint(n - 1)}")
                print(f"  覆盖过程:")
                for a, covered, remaining in log:
                    covered_str = ", ".join([f"{p}^{e}" for p, e in covered])
                    print(f"    底数 a={a}: 覆盖 {covered_str} | 剩余: {remaining}")

        n = sp.nextprime(n) if HAS_SYMPY else n + 2
        checked += 1

    return found


# ==============================================================================
# 演示与测试
# ==============================================================================

def demo():
    """完整演示"""
    print("=" * 70)
    print("何先玄素性定理 - 覆盖标记版 v4.0 (缓存+分段+原根构造完整版)")
    print("=" * 70)
    print()
    print("核心优化：")
    print("  1. 三级缓存：分解结果、费马检验、阶测试")
    print("  2. 分段搜索：避免内存溢出，支持超大范围")
    print("  3. 一底多覆盖：一个底数同时覆盖多个质因数幂")
    print("  4. 原根构造：用覆盖法确定性构造原根")
    print()
    print("【注意】多覆盖时 b_{ti} 可以取同一个数！")
    print("  同一底数覆盖多个 p^e 时，分别用不同指数 ord/p^e 计算 c_i。")
    print("  每个 c_i 的阶恰好是对应的 p^e。")
    print("  乘积 g = ∏ c_i (mod n) 的阶为 lcm = n-1，即原根。")
    print()

    # 基础测试
    test_cases = [
        ("小素数", [2, 3, 5, 7, 11, 13, 17, 19, 23]),
        ("小合数", [4, 6, 8, 9, 10, 12, 15, 21, 25, 27]),
        ("卡迈克尔数", [561, 1105, 1729, 2465, 2821, 6601, 8911]),
        ("中等素数", [104729, 1000003, 1000033]),
        ("大素数", [15485863, 32452843]),
    ]

    for category, numbers in test_cases:
        print(f"
【{category}】")
        for n in numbers:
            t0 = time.time()
            result, reason = he_xianxuan_cover(n, max_search=300)
            elapsed = time.time() - t0
            status = "素数" if result else ("合数" if result is False else "不确定")
            print(f"  n={n:>10} → {status:<4} | {reason[:55]:<55} | {elapsed:.4f}s")

    # 原根构造演示
    if HAS_SYMPY:
        print("
" + "=" * 70)
        print("原根构造演示")
        print("=" * 70)

        for p in [53, 31, 101, 1009]:
            find_primitive_root_verbose(p, max_search=100)

    # 大数测试
    if HAS_SYMPY:
        print("
" + "=" * 70)
        print("大数素性测试 (50-80位)")
        print("=" * 70)

        big_primes = [
            ("50位", sp.nextprime(10**49)),
            ("60位", sp.nextprime(10**59)),
            ("70位", sp.nextprime(10**69)),
            ("80位", sp.nextprime(10**79)),
        ]

        for label, n in big_primes:
            print(f"
【{label}素数】n = {n}")
            t0 = time.time()
            result, reason = he_xianxuan_cover(n, max_search=300, verbose=True)
            elapsed = time.time() - t0
            status = "素数 ✓" if result else "合数 ✗"
            print(f"  结果: {status} | 总耗时: {elapsed:.3f}秒")

            # 同时构造原根
            if result:
                print(f"
  构造原根...")
                g, steps = find_primitive_root(n, max_search=300, verbose=False)
                if g:
                    print(f"  原根 g = {g} (mod {n})")

        # 分段搜索演示
        print("
" + "=" * 70)
        print("分段搜索演示 (20位素数)")
        print("=" * 70)
        segmented_search(20, count=2, segment_size=500, max_search=300)

        # 多底数素数搜索
        find_multi_base_primes(20, min_bases=2, count=2)

    # 交互模式
    print("
" + "=" * 70)
    print("交互模式: 输入数字检测 (q 退出, p 原根构造)")
    print("=" * 70)

    while True:
        try:
            user_input = input("
请输入: ").strip()
            if user_input.lower() in ('q', 'quit', 'exit'):
                break
            if user_input.lower() == 'cache':
                cache_stats()
                continue
            if user_input.lower() == 'clear':
                clear_caches()
                continue

            n = int(user_input)

            print(f"
{'='*70}")
            print(f"详细分析: n = {n}")
            print(f"{'='*70}")

            t0 = time.time()
            result, reason = he_xianxuan_cover(n, max_search=500, verbose=True)
            elapsed = time.time() - t0

            status = "素数 ✓" if result else ("合数 ✗" if result is False else "不确定 ?")
            print(f"
结果: {status}")
            print(f"原因: {reason}")
            print(f"总耗时: {elapsed:.3f}秒")

            # 如果是素数，询问是否构造原根
            if result:
                try:
                    do_root = input("
构造原根? (y/n): ").strip().lower()
                    if do_root == 'y':
                        find_primitive_root_verbose(n, max_search=500)
                except:
                    pass

        except ValueError:
            print("请输入整数!")
        except KeyboardInterrupt:
            print("
再见!")
            break


if __name__ == "__main__":
    demo()
