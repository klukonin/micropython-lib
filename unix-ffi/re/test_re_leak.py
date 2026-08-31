# Regression test for the memory that PCRE2 allocates behind this module: the
# match data of every match, and every pattern compiled by the module level
# functions, have to be freed again.  Otherwise each call leaks a few
# kilobytes.
#
# A pattern returned by re.compile() and kept by the caller is not covered
# here.  MicroPython does not run __del__ on instances of Python classes, so
# such a pattern can only be released explicitly.

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
