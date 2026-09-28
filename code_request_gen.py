"""Synthetic code-request sentences for FRIDAY's code_domain class: run this snippet, explain this,
write something that does X, and implicit debugging ("my loop isn't terminating").
"""
import json
import random
from pathlib import Path

random.seed(11)


_ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
         "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
         "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def number_to_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _TENS[tens] + (f"-{_ONES[ones]}" if ones else "")
    hundreds, rest = divmod(n, 100)
    if rest == 0:
        return f"{_ONES[hundreds]} hundred"
    return f"{_ONES[hundreds]} hundred and {number_to_words(rest)}"


def _num_str(n: int, spelled: bool) -> str:
    return number_to_words(n) if spelled else str(n)


_OPS = [
    ("plus", "+"), ("add", "+"), ("added to", "+"),
    ("minus", "-"), ("subtract", "-"), ("take away", "-"),
    ("times", "*"), ("multiplied by", "*"), ("x", "*"),
    ("divided by", "/"), ("over", "/"),
]

_MATH_PHRASINGS = [
    "what is {a} {op} {b}", "what's {a} {op} {b}", "calculate {a} {op} {b}",
    "work out {a} {op} {b}", "{a} {op} {b} equals what", "can you do {a} {op} {b}",
    "quick maths: {a} {op} {b}", "solve {a} {op} {b}",
]


def gen_math(n: int) -> list[dict]:
    out = []
    for _ in range(n):
        a, b = random.randint(0, 200), random.randint(0, 200)
        op_word, op_sym = random.choice(_OPS)

        spelled = random.random() < 0.55 and a != 0 and b != 0
        a_str, b_str = _num_str(a, spelled), _num_str(b, spelled)

        if op_word == "subtract" and random.random() < 0.5:
            utt = f"subtract {a_str} from {b_str}"
            expr = f"{b}-{a}"
        else:
            utt = random.choice(_MATH_PHRASINGS).format(a=a_str, op=op_word, b=b_str)
            expr = f"{a}{op_sym}{b}"
        out.append({"input": utt, "output": f"skill=calculator; expression={expr}"})
    return out


_FAKE_SNIPPETS = [
    "def add(a, b):\n    return a + b",
    "print('hello world')",
    "for i in range(10):\n    print(i)",
    "x = [1, 2, 3]\nprint(sum(x))",
    "class Dog:\n    def bark(self):\n        return 'woof'",
    "import random\nprint(random.randint(1, 6))",
]

_RUN_PHRASINGS = [
    "run this code:\n```python\n{code}\n```",
    "test this:\n```python\n{code}\n```",
    "does this work:\n```python\n{code}\n```",
    "execute this snippet:\n```python\n{code}\n```",
    "can you run this function:\n```python\n{code}\n```",
]
_EXPLAIN_PHRASINGS = [
    "what does this do:\n```python\n{code}\n```",
    "explain this code:\n```python\n{code}\n```",
    "can you walk me through this:\n```python\n{code}\n```",
]


_GENERATE_PHRASINGS = [
    "write a function that {task}",
    "write me a script that {task}",
    "generate a function that {task}",
    "generate me a script that {task}",
    "create a program that {task}",
    "make a script that {task}",
    "build me a function that {task}",
    "can you code something that {task}",
    "can you write something that {task}",
    "can you generate something that {task}",
]
_WRITE_TASKS = [
    "reverses a string", "checks if a number is prime", "sorts a list",
    "finds the largest number in a list", "converts celsius to fahrenheit",
    "counts vowels in a word",
]


_IMPLICIT_DEBUG_PHRASINGS = [
    "why is my {thing} not {problem}",
    "this {thing} keeps {gerund_problem}, any idea why", "this {thing} keeps {gerund_problem}, any ideas why",
    "why does this keep {gerund_problem}",
    "my {thing} isn't {gerund_problem} right",
    "can you make this {thing} run faster",
    "is there a cleaner way to write this {thing}",
    "can you explain the difference between these two approaches",
    "what's the time complexity of this",
    "what does this error actually mean",
    "can you refactor this {thing}",
    "help me write a test for this {thing}",
    "is there a bug in this logic somewhere",
    "what's wrong with my code, it's throwing an error",
]
_IMPLICIT_DEBUG_THINGS = ["function", "script", "loop", "class", "query", "API call"]
_IMPLICIT_DEBUG_PROBLEMS = ["terminating", "working", "returning the right thing", "compiling"]
_IMPLICIT_DEBUG_GERUNDS = [
    "crashing", "timing out", "throwing an error", "running forever",
    "returning the wrong thing", "hanging",
]


def gen_coding(n: int) -> list[dict]:
    out = []
    for _ in range(n):
        kind = random.random()
        if kind < 0.35:
            phr = random.choice(_RUN_PHRASINGS)
            utt = phr.format(code=random.choice(_FAKE_SNIPPETS))
            output = "skill=test_code; language=python"
        elif kind < 0.6:
            phr = random.choice(_EXPLAIN_PHRASINGS)
            utt = phr.format(code=random.choice(_FAKE_SNIPPETS))
            output = "skill=explain_code; language=python"
        elif kind < 0.8:
            phr = random.choice(_GENERATE_PHRASINGS)
            utt = phr.format(task=random.choice(_WRITE_TASKS))
            output = "skill=generate_code; language=python"
        else:
            phr = random.choice(_IMPLICIT_DEBUG_PHRASINGS)
            utt = phr.format(
                thing=random.choice(_IMPLICIT_DEBUG_THINGS),
                problem=random.choice(_IMPLICIT_DEBUG_PROBLEMS),
                gerund_problem=random.choice(_IMPLICIT_DEBUG_GERUNDS),
            ) if "{" in phr else phr
            output = "skill=test_code; language=python"
        out.append({"input": utt, "output": output})
    return out
