"""Mathematics generator — fully programmatic, never LLM-generated.

Every problem's answer is *computed* by the same code that creates the
problem, so the answer key is correct by construction. This is the
accuracy guarantee for the one field where a wrong answer key would
directly mis-teach a child.

Difficulty model:
  grade  -> which problem families are eligible (curriculum band)
  level  -> operand magnitude and step count within those families
  seed   -> full reproducibility; the uniqueness loop reseeds on collision
"""
import random
from fractions import Fraction

from .. import config
from .base import Problem, Sheet, Packet

# Level index 0..5 (Easy..EXTREME) scales operand ranges.
_LEVEL_SCALE = {lvl: i for i, lvl in enumerate(config.LEVELS)}


def _grade_band(grade: str) -> int:
    """Collapse grades into curriculum bands 0..6."""
    order = {g: i for i, g in enumerate(config.GRADES)}
    i = order[grade]
    if i <= 1:          # TK, K
        return 0
    if i <= 3:          # 1, 2
        return 1
    if i <= 5:          # 3, 4
        return 2
    if i <= 7:          # 5, 6
        return 3
    if i <= 9:          # 7, 8
        return 4
    if i <= 11:         # 9, 10
        return 5
    return 6            # 11, 12


# --- problem families --------------------------------------------------------

def _counting(rng: random.Random, lv: int) -> Problem:
    n = rng.randint(3, 5 + 2 * lv)
    item = rng.choice(["★", "●", "▲", "♦", "☂", "✿"])
    return Problem(prompt=f"Count the shapes and write the number:  {item * n}",
                   answer=str(n))

def _addition(rng: random.Random, lv: int, cap: int) -> Problem:
    hi = min(cap, 5 + lv * (cap // 6))
    a, b = rng.randint(1, hi), rng.randint(1, hi)
    return Problem(prompt=f"{a} + {b} = ____", answer=str(a + b))

def _subtraction(rng: random.Random, lv: int, cap: int) -> Problem:
    hi = min(cap, 5 + lv * (cap // 6))
    a = rng.randint(2, hi)
    b = rng.randint(1, a)          # never negative for young grades
    return Problem(prompt=f"{a} − {b} = ____", answer=str(a - b))

def _multiplication(rng: random.Random, lv: int) -> Problem:
    hi = 4 + 2 * lv
    a, b = rng.randint(2, hi), rng.randint(2, min(hi, 12))
    return Problem(prompt=f"{a} × {b} = ____", answer=str(a * b))

def _division(rng: random.Random, lv: int) -> Problem:
    b = rng.randint(2, 4 + 2 * lv)
    q = rng.randint(2, 6 + 2 * lv)
    return Problem(prompt=f"{b * q} ÷ {b} = ____", answer=str(q))

def _fraction_add(rng: random.Random, lv: int) -> Problem:
    d1 = rng.randint(2, 4 + lv)
    d2 = rng.randint(2, 4 + lv)
    f1 = Fraction(rng.randint(1, d1 - 1) if d1 > 1 else 1, d1)
    f2 = Fraction(rng.randint(1, d2 - 1) if d2 > 1 else 1, d2)
    s = f1 + f2
    return Problem(
        prompt=f"{f1.numerator}/{f1.denominator} + "
               f"{f2.numerator}/{f2.denominator} = ____ "
               f"(answer as a fraction in lowest terms)",
        answer=f"{s.numerator}/{s.denominator}")

def _decimal_mult(rng: random.Random, lv: int) -> Problem:
    a = rng.randint(11, 99) / 10
    b = rng.randint(2, 4 + lv)
    ans = a * b
    return Problem(prompt=f"{a} × {b} = ____",
                   answer=f"{ans:.1f}".rstrip("0").rstrip("."))

def _percent_of(rng: random.Random, lv: int) -> Problem:
    pct = rng.choice([10, 20, 25, 50, 75, 5, 15][: 3 + lv])
    base = rng.randint(2, 8 + 2 * lv) * 20
    ans = base * pct / 100
    ans_str = str(int(ans)) if ans == int(ans) else f"{ans:g}"
    return Problem(prompt=f"What is {pct}% of {base}?", answer=ans_str)

def _integer_ops(rng: random.Random, lv: int) -> Problem:
    a = rng.randint(-10 - 5 * lv, 10 + 5 * lv)
    b = rng.randint(-10 - 5 * lv, 10 + 5 * lv)
    op = rng.choice(["+", "−", "×"])
    val = a + b if op == "+" else a - b if op == "−" else a * b
    return Problem(prompt=f"({a}) {op} ({b}) = ____", answer=str(val))

def _linear_eq(rng: random.Random, lv: int) -> Problem:
    x = rng.randint(-5 - lv, 8 + 2 * lv)
    a = rng.randint(2, 4 + lv)
    b = rng.randint(-10, 15)
    c = a * x + b
    sign = "+" if b >= 0 else "−"
    return Problem(prompt=f"Solve for x:   {a}x {sign} {abs(b)} = {c}",
                   answer=f"x = {x}")

def _quadratic(rng: random.Random, lv: int) -> Problem:
    r1 = rng.randint(-4 - lv, 4 + lv)
    r2 = rng.randint(-4 - lv, 4 + lv)
    b, c = -(r1 + r2), r1 * r2
    bs = f"+ {b}x" if b > 0 else (f"− {abs(b)}x" if b < 0 else "")
    cs = f"+ {c}" if c > 0 else (f"− {abs(c)}" if c < 0 else "")
    roots = sorted({r1, r2})
    ans = " and ".join(f"x = {r}" for r in roots)
    return Problem(prompt=f"Solve:   x² {bs} {cs} = 0".replace("  ", " "),
                   answer=ans)

def _exponent(rng: random.Random, lv: int) -> Problem:
    base = rng.randint(2, 5 + lv)
    exp = rng.randint(2, 3 + lv // 2)
    return Problem(prompt=f"{base}^{exp} = ____", answer=str(base ** exp))

def _poly_eval(rng: random.Random, lv: int) -> Problem:
    a, b, c = (rng.randint(-3 - lv, 3 + lv) or 1,
               rng.randint(-5, 5), rng.randint(-9, 9))
    x = rng.randint(-3, 4)
    val = a * x * x + b * x + c
    return Problem(
        prompt=f"If f(x) = {a}x² + ({b})x + ({c}), find f({x}).",
        answer=str(val))

def _arith_sequence(rng: random.Random, lv: int) -> Problem:
    a0 = rng.randint(1, 10)
    d = rng.randint(2, 4 + lv)
    n = rng.randint(5, 8 + lv)
    seq = [a0 + i * d for i in range(4)]
    nth = a0 + (n - 1) * d
    return Problem(
        prompt=f"Sequence: {', '.join(map(str, seq))}, …  "
               f"What is term number {n}?",
        answer=str(nth))


# Eligible families per curriculum band (cumulative difficulty ladder).
_BANDS: list[list] = [
    # 0: TK/K
    [_counting, lambda r, l: _addition(r, l, 10)],
    # 1: grades 1-2
    [lambda r, l: _addition(r, l, 100), lambda r, l: _subtraction(r, l, 100),
     _counting],
    # 2: grades 3-4
    [_multiplication, _division,
     lambda r, l: _addition(r, l, 1000), lambda r, l: _subtraction(r, l, 1000)],
    # 3: grades 5-6
    [_fraction_add, _decimal_mult, _percent_of, _multiplication, _division],
    # 4: grades 7-8
    [_integer_ops, _linear_eq, _percent_of, _fraction_add],
    # 5: grades 9-10
    [_linear_eq, _quadratic, _exponent, _integer_ops],
    # 6: grades 11-12
    [_poly_eval, _quadratic, _arith_sequence, _exponent],
]

_BAND_TOPICS = [
    "Counting & early addition", "Addition & subtraction",
    "Multiplication & division", "Fractions, decimals & percents",
    "Integers & linear equations", "Algebra: equations & exponents",
    "Functions, polynomials & sequences",
]


def generate_math_packet(grade: str, level: str, seed: int,
                         sheets: int | None = None,
                         problems_per_sheet: int | None = None) -> Packet:
    if grade not in config.GRADES:
        raise ValueError(f"Unknown grade: {grade!r}")
    if level not in config.LEVELS:
        raise ValueError(f"Unknown level: {level!r}")
    sheets = sheets or config.SHEETS_PER_PACKET
    pps = problems_per_sheet or config.PROBLEMS_PER_SHEET

    rng = random.Random(seed)
    band = _grade_band(grade)
    lv = _LEVEL_SCALE[level]
    families = _BANDS[band]

    packet = Packet(kind="worksheet", field_name="Mathematics",
                    grade=grade, level=level, source="programmatic")
    for s in range(sheets):
        sheet = Sheet(
            title=f"Mathematics — Grade {grade} — {level} — Sheet {s + 1}",
            topic=_BAND_TOPICS[band],
            instructions="Solve each problem. Show your work in the space "
                         "provided.",
        )
        seen_prompts: set[str] = set()
        while len(sheet.problems) < pps:
            fam = rng.choice(families)
            p = fam(rng, lv)
            if p.prompt in seen_prompts:      # no repeats *within* a sheet
                continue
            seen_prompts.add(p.prompt)
            sheet.problems.append(p)
        packet.sheets.append(sheet)
    return packet


def generate_math_questions(grade: str, level: str, seed: int,
                            n: int) -> list[Problem]:
    """n standalone questions for the multi-field Test packet."""
    pkt = generate_math_packet(grade, level, seed, sheets=1,
                               problems_per_sheet=n)
    return pkt.sheets[0].problems
