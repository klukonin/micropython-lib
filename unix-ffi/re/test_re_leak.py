# Regression test for the memory that PCRE2 allocates behind this module: the
# match data of every match, and every pattern compiled by the module level
# functions, have to be freed again.  Otherwise each call leaks a few
# kilobytes.
#
# A pattern returned by re.compile() and kept by the caller is not covered
# here.  MicroPython does not run __del__ on instances of Python classes, so
# such a pattern can only be released explicitly.
#
# The bounded cache that the module level functions keep is covered: it must
# not grow past its limit, and the patterns that do not fit into it must be
# freed again.

import gc
import re


def rss():
    # Resident set size in KiB, from the second field of /proc/self/statm.
    with open("/proc/self/statm") as f:
        return int(f.read().split()[1]) * 4096 // 1024


try:
    rss()
except OSError:
    # No /proc, so memory use cannot be measured here.
    print("SKIP")
    raise SystemExit


N = 4000
LIMIT = 256  # KiB


def check_no_leak(name, fn):
    # Run the calls once to let the MicroPython heap grow to its steady state,
    # so that only the memory allocated by PCRE2 is measured afterwards.
    for _ in range(N):
        fn()
    gc.collect()
    before = rss()
    for _ in range(N):
        fn()
    gc.collect()
    growth = rss() - before
    assert growth < LIMIT, "%s leaks %d KiB per %d calls (%d bytes per call)" % (
        name,
        growth,
        N,
        growth * 1024 // N,
    )


text = "He was carefully disguised but captured quickly by police."
p = re.compile("a(b)c")

# Matching with a compiled pattern.
check_no_leak("Pattern.search() with a match", lambda: p.search("xxabcxx"))
check_no_leak("Pattern.search() without a match", lambda: p.search("xxxxxxx"))
check_no_leak("Pattern.match()", lambda: p.match("abcxx"))
check_no_leak("Pattern.sub()", lambda: p.sub("z", "xxabcxx"))
check_no_leak("Pattern.split()", lambda: p.split("xxabcxx"))
check_no_leak("Pattern.findall()", lambda: p.findall("xxabcxx abc"))

# The module level functions, which compile a pattern of their own.
check_no_leak("re.search()", lambda: re.search("a(b)c", "xxabcxx"))
check_no_leak("re.match()", lambda: re.match("a(b)c", "abcxx"))
check_no_leak("re.sub()", lambda: re.sub("a", "z", "caaab"))
check_no_leak("re.split()", lambda: re.split(r"\W+", "Words, words, words."))
check_no_leak("re.findall()", lambda: re.findall(r"(\w+)ly", text))


# Compiling, including the path that does not produce a usable pattern.
def compile_and_free():
    re.compile("a(b)c")._free()


def free_twice():
    r = re.compile("a(b)c")
    r._free()
    r._free()


def failed_compile():
    try:
        re.compile("(")
    except AssertionError:
        pass


check_no_leak("re.compile() and _free()", compile_and_free)
check_no_leak("_free() called twice", free_twice)
check_no_leak("re.compile() of a bad pattern", failed_compile)


# A pattern with several groups needs a larger match data block.
def many_groups():
    r = re.compile(r"(\w+)(\s+)(\w+)(\s+)(\w+)")
    assert r.search("one two three").groups() == ("one", " ", "two", " ", "three")
    r._free()


check_no_leak("pattern with several groups", many_groups)


# compile() returns the cached pattern, the way CPython does, so compiling the
# same pattern again does not allocate.
assert re.compile("a(b)c") is re.compile("a(b)c")
check_no_leak("re.compile() with the same pattern", lambda: re.compile("a(b)c"))

# _free() drops the pattern from the cache, so that nothing afterwards hands
# out a pointer to memory that has been released.
r = re.compile("zz(y)")
r._free()
assert re.search("zz(y)", "xxzzyxx").group(0) == "zzy"


# The module level functions cache the patterns they compile.  That cache must
# stay bounded, and a pattern that does not fit into it has to be freed again.
counter = [0]


def distinct_patterns():
    counter[0] += 1
    re.search("a%dc" % counter[0], "xxabcxx")


# Push far more distinct patterns through the cache than it can hold: it has
# to stop growing.
for _ in range(re._MAXCACHE * 4):
    distinct_patterns()
assert len(re._cache) <= re._MAXCACHE, len(re._cache)

check_no_leak("re.search() with distinct patterns", distinct_patterns)
assert len(re._cache) <= re._MAXCACHE, len(re._cache)


# A replacement callback runs while sub() is still using its own pattern, and
# may push further patterns through the cache.  The pattern that is in use must
# survive that.
def reentrant_repl(m):
    counter[0] += 1
    re.search("z%dz" % counter[0], "nothing here")
    return "z"


check_no_leak("re.sub() with a reentrant callback", lambda: re.sub("a", reentrant_repl, "caaab"))
assert len(re._cache) <= re._MAXCACHE, len(re._cache)
