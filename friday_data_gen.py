"""FRIDAY's training data: every message labelled with one of four domains —
conversation, pa_domain, code_domain, research_needed.

The personal-assistant rows are EDITH's own synthetic sentences relabelled (so the two brains agree on
what counts as an assistant request), the code rows come from code_request_gen, and the rest are
templates for chat, questions that need current information, pasted links, and follow-ups that only
make sense with the previous turn as context ("[recent: ...]"). The four classes are balanced.

  python friday_data_gen.py      -> data/friday_train.jsonl
"""
import json
import random
from pathlib import Path

import data_gen
import code_request_gen

random.seed(42)


SKILL_TO_TRIAGE_LABEL = {
    "calendar_add": "pa_domain",
    "calendar_update": "pa_domain",
    "calendar_delete": "pa_domain",
    "reminder": "pa_domain",
    "weather": "pa_domain",
    "calculator": "pa_domain",
    "clarify": "pa_domain",
    "conversation": "conversation",
    "research_needed": "research_needed",
    "test_code": "code_domain",
    "explain_code": "code_domain",
    "write_code": "code_domain",
    "generate_code": "code_domain",
}


def _extract_skill_name(dsl_output: str) -> str:
    first_field = dsl_output.split(";")[0].strip()
    assert first_field.startswith("skill="), (
        f"malformed DSL output, expected 'skill=...': {dsl_output!r}"
    )
    return first_field[len("skill="):].strip()


def _relabel(examples: list[dict]) -> list[dict]:
    relabeled = []
    for ex in examples:
        skill_name = _extract_skill_name(ex["output"])
        if skill_name not in SKILL_TO_TRIAGE_LABEL:
            raise KeyError(
                f"Unmapped skill label '{skill_name}' — add it to "
                f"SKILL_TO_TRIAGE_LABEL explicitly rather than silently "
                f"miscategorizing it."
            )
        relabeled.append({
            "input": ex["input"],
            "output": SKILL_TO_TRIAGE_LABEL[skill_name],
        })
    return relabeled


def gen_clock_related(n: int) -> list[dict]:
    cities = ["Tokyo", "London", "Paris", "Sydney", "New York", "Berlin", "Toronto", "Cairo"]
    world_clock_templates = [
        "what time is it in {city}",
        "what time is it in {city} right now",
        "what's the current time in {city}",
        "what's the time over in {city}",
    ]
    stopwatch_phrases = [
        "start the stopwatch", "stop the stopwatch", "check the stopwatch",
        "how long has the stopwatch been running", "reset the stopwatch",
        "pause the stopwatch",
    ]
    timer_templates = [
        "set a timer for {n} minutes", "set a {n} minute timer",
        "cancel the timer", "how much time is left on the timer",
        "start a timer for {n} minutes",
    ]
    alarm_templates = [
        "set an alarm for {h}am", "set an alarm for {h}pm",
        "wake me up at {h}am", "cancel my alarm", "what's my next alarm",
    ]

    out = []
    for _ in range(n):
        roll = random.random()
        if roll < 0.35:
            utt = random.choice(world_clock_templates).format(city=random.choice(cities))
        elif roll < 0.55:
            utt = random.choice(stopwatch_phrases)
        elif roll < 0.8:
            utt = random.choice(timer_templates).format(n=random.randint(1, 60))
        else:
            utt = random.choice(alarm_templates).format(h=random.randint(1, 12))
        out.append({"input": utt, "output": "pa_domain"})
    return out


def gen_pasted_url(n: int) -> list[dict]:
    hosts = ["en.wikipedia.org/wiki/Photosynthesis", "www.nasa.gov/missions/",
             "www.bbc.com/news/science_and_environment", "www.imdb.com/chart/top/",
             "en.wikipedia.org/wiki/Computer_network", "www.nationalgeographic.com/animals/"]
    code_hosts = ["docs.python.org/3/library/json.html", "numpy.org/doc/stable/",
                  "stackoverflow.com/questions/394809/does-python-have-a-ternary-operator",
                  "pypi.org/project/requests/", "developer.mozilla.org/en-US/docs/Web/JavaScript"]

    event_hosts = ["example.edu/academics/calendar", "eventbrite.com/e/networking-night-tickets",
                   "meetup.com/city-python-group/events/100001"]
    schemes = ["https://", "http://", ""]
    generic = ["{url}", "{url} check this out", "have a look at {url}",
               "Make use of this link {url}", "read this: {url}",
               "what do you make of {url}", "{url} thoughts?",
               "can you go through {url}", "pull up {url}", "take a look at {url}"]
    code_q = ["{url} how do I use this in python", "does {url} explain how to parse this",
              "{url} can you write something that uses this api",
              "based on {url} how would I implement that"]
    pa_q = ["{url} add the dates from this to my calendar",
            "put the event on {url} in my schedule",
            "{url} remind me about this tomorrow"]
    out = []
    for _ in range(n):
        pool = random.random()
        if pool < 0.55:
            url_host, label = random.choice(hosts), "conversation"
        elif pool < 0.80:
            url_host, label = random.choice(code_hosts), "code_domain"
        else:
            url_host, label = random.choice(event_hosts), "pa_domain"
        url = random.choice(schemes) + url_host

        if label == "code_domain" and random.random() < 0.6:
            phrasing = random.choice(code_q)
        elif label == "pa_domain" and random.random() < 0.6:
            phrasing = random.choice(pa_q)
        else:
            phrasing = random.choice(generic)
        out.append({"input": phrasing.format(url=url), "output": label})
    return out


def gen_notes_and_scoped_clear(n: int) -> list[dict]:
    note_subjects = ["groceries", "ideas", "the meeting", "shopping", "packing",
                     "the reading list", "book recommendations", "gift ideas"]
    show_templates = [
        "show me my notes", "what notes do I have", "pull up my notes",
        "read me my last note", "open my notes", "list my notes",
        "what was in my {subject} note", "show me the {subject} note",
    ]
    make_templates = [
        "make a note called {subject}", "create a note about {subject}",
        "start a {subject} note", "take a note about {subject}",
        "jot down a note for {subject}", "new note called {subject}",
    ]

    negate_templates = [
        "dont create a note", "don't create the note", "actually dont make that note",
        "it's ok dont create the note", "scrap that note", "never mind the note",
        "forget the note", "cancel that note",
    ]

    clear_templates = [
        "clear my day", "clear my calendar", "clear my schedule",
        "clear my week", "clear today", "clear my morning",
        "clear my {subject} event for today", "wipe my calendar for today",
        "clear everything on friday", "clear my afternoon",
    ]
    clear_subjects = ["lunch", "dentist", "gym", "meeting", "dinner", "call"]

    out = []
    for _ in range(n):
        roll = random.random()
        if roll < 0.25:
            utt = random.choice(show_templates).format(subject=random.choice(note_subjects))
        elif roll < 0.50:
            utt = random.choice(make_templates).format(subject=random.choice(note_subjects))
        elif roll < 0.70:
            utt = random.choice(negate_templates)
        else:
            utt = random.choice(clear_templates).format(subject=random.choice(clear_subjects))
        out.append({"input": utt, "output": "pa_domain"})
    return out


_RESEARCH_TOPICS = [
    "the next Formula 1 race", "the latest chess championship",
    "when the new movie comes out", "the current stock price of that company",
    "who won the game last night", "the newest phone release date",
]
_CALENDAR_CONTEXT_TASKS = [
    "dentist", "team meeting", "haircut", "doctor's appointment", "gym session",
]
_CODE_CONTEXT_SUBJECTS = [
    "a function to parse CSV files", "a script to scrape a webpage",
    "a REST API endpoint", "a sorting algorithm", "a login form validator",
]
_WEATHER_FOLLOWUPS = ["what about tomorrow", "and this weekend", "what about next week"]
_CONVERSATION_TOPICS = [
    "chatting about weekend plans", "talking about a movie",
    "joking around about work", "discussing what to have for dinner",
]
_CONVERSATION_FOLLOWUPS = ["yeah that sounds fun", "haha same", "for real though", "honestly agreed"]


def gen_context_dependent_triage(n: int) -> list[dict]:
    out = []
    for _ in range(n):
        roll = random.random()
        if roll < 0.25:
            topic = random.choice(_RESEARCH_TOPICS)
            context = f"[recent: asked about {topic}]"
            phrasing = random.choice([
                "no, I mean the exact date", "no what I'm trying to ask is when",
                "sorry I meant specifically when", "but when exactly",
            ])
            out.append({"input": f"{context} {phrasing}", "output": "research_needed"})
        elif roll < 0.5:
            if random.random() < 0.5:
                task = random.choice(_CALENDAR_CONTEXT_TASKS)
                day = data_gen._day_choice()
                hour = random.choice(data_gen.HOURS_12)
                ampm = random.choice(data_gen.AMPM)
                context = f"[recent: added '{task}' event {day} at {data_gen._time_str(hour, ampm)}]"
                phrasing = random.choice(["can you move it to 4pm instead", "actually make that an hour later", "change that to friday"])
            else:
                context = "[recent: asked about the weather today]"
                phrasing = random.choice(_WEATHER_FOLLOWUPS)
            out.append({"input": f"{context} {phrasing}", "output": "pa_domain"})
        elif roll < 0.75:
            subject = random.choice(_CODE_CONTEXT_SUBJECTS)
            context = f"[recent: wrote {subject}]"
            phrasing = random.choice([
                "now add error handling to it", "can you also add tests for that",
                "add a docstring to it", "make it handle edge cases too",
            ])
            out.append({"input": f"{context} {phrasing}", "output": "code_domain"})
        else:
            topic = random.choice(_CONVERSATION_TOPICS)
            context = f"[recent: {topic}]"
            phrasing = random.choice(_CONVERSATION_FOLLOWUPS)
            out.append({"input": f"{context} {phrasing}", "output": "conversation"})
    return out


_RW_MEDIA = [
    "the new Pixar movie", "the next James Bond film", "the new Star Wars series",
    "the Jurassic World sequel", "the new season of that detective show", "the next Paddington film",
    "the documentary about the ocean", "the new animated series", "the space movie", "the mystery sequel",
]
_RW_GAMING = [
    "the chess world championship", "the Premier League", "the NBA finals", "the World Cup",
    "the Formula 1 season", "the next Zelda game", "the Olympics", "the Tour de France",
    "the next Minecraft update", "Wimbledon", "the Super Bowl", "the cricket world cup",
]
_RW_TECH = [
    "laptop prices", "the new iPhone", "smartwatches", "the next Pixel phone", "Bitcoin",
    "gold prices", "electric cars", "the new MacBook", "game console prices", "TV prices",
]
_RW_WORLD = [
    "the election", "the interest rate decision", "the euro exchange rate",
    "flights to Europe", "the weather warning", "the transit strike",
]

_RW_WHEN = [
    "when is {s} coming out", "when does {s} release", "when is {s} being released",
    "what's the release date for {s}", "is {s} out yet", "has {s} released yet",
    "when is {s} scheduled", "do we know when {s} drops",
]
_RW_SCORE = [
    "what's the rotten tomatoes score for {s}", "what are the reviews for {s} like",
    "how did {s} review", "is {s} any good", "what did critics say about {s}",
    "what's the metacritic on {s}",
]
_RW_STATUS = [
    "what's the latest news for {s}", "any news on {s}", "what's happening with {s}",
    "how is {s} doing right now", "what's the current status of {s}",
    "give me an update on {s}", "anything new about {s}",
]
_RW_PRICE = [
    "how much is {s} right now", "what's the current price of {s}",
    "have {s} gone up", "are {s} cheaper now", "what is {s} trading at",
    "how much does {s} cost these days",
]
_RW_STANDING = [
    "how is {s} doing in the standings", "did {s} win", "who did {s} lose to",
    "what's {s}'s record this stage", "is {s} still in it", "how far did {s} get",
]
_RW_VERIFY = [
    "is that still true", "is that still the case these days", "has that changed",
    "is that up to date", "what's the current situation with that",
    "did that actually happen", "can you check if that's still right",
]


def gen_research_wide(n: int) -> list[dict]:
    out = []
    families = [
        (_RW_MEDIA, _RW_WHEN + _RW_SCORE + _RW_STATUS),
        (_RW_GAMING, _RW_WHEN + _RW_STATUS + _RW_STANDING),
        (_RW_TECH, _RW_PRICE + _RW_STATUS),
        (_RW_WORLD, _RW_STATUS + _RW_WHEN),
    ]
    for _ in range(n):
        if random.random() < 0.08:
            out.append({"input": random.choice(_RW_VERIFY), "output": "research_needed"})
            continue
        subjects, templates = random.choice(families)
        utt = random.choice(templates).format(s=random.choice(subjects))
        if random.random() < 0.25:
            utt = utt + "?"
        if random.random() < 0.15:
            utt = random.choice(["hey ", "ultron ", "quick one — "]) + utt
        out.append({"input": utt, "output": "research_needed"})
    return out


_CV_OPENERS = ["good morning", "good afternoon", "good evening", "hey", "hello", "hi", "yo", "morning", "evening"]
_CV_SMALL = [
    "how are things going", "how are we doing today", "how's it going",
    "you good", "everything running okay", "how are you holding up",
    "what have you been up to", "busy day for you",
]
_CV_META = [
    "take a rest ultron", "that's all for now", "never mind", "forget it",
    "thanks", "thank you", "appreciate it", "nice one", "good work",
    "that's fine", "no worries", "sounds good", "okay cool", "alright",
    "you can stop", "we're done for now", "that'll do",
]
_CV_OPINION = [
    "what do you think about that", "do you have an opinion on it",
    "what's your take", "would you agree", "does that seem right to you",
    "what would you do", "curious what you think",
]
_CV_TOPICS = [
    "that trailer", "the new season", "this patch", "that match", "the finals",
    "my project", "this build", "the weather lately", "that movie", "the update",
]
_CV_ABOUT_TOPIC = [
    "what did you think of {t}", "{t} was something else", "not sure how I feel about {t}",
    "{t} is growing on me", "honestly {t} was underwhelming", "{t} looks promising",
    "everyone's talking about {t}", "I'm still thinking about {t}",
]
_CV_BANTER = [
    "you're getting better at this", "that was quick", "took you long enough",
    "I'll give you that one", "not bad", "we'll get there", "one step at a time",
    "long day", "I'm tired", "back at it", "let's keep going", "where were we",
]
_CV_ABOUT_ULTRON = [
    "what can you do", "what are you good at", "how do you work",
    "are you learning from this", "do you remember our last conversation",
    "which brain is running right now", "how much memory are you using",
]


def gen_conversation_wide(n: int) -> list[dict]:
    out = []
    for _ in range(n):
        r = random.random()
        if r < 0.30:
            utt = random.choice(_CV_OPENERS)
            if random.random() < 0.5:
                utt += " ultron"
            if random.random() < 0.25:
                utt += ", " + random.choice(_CV_SMALL)
        elif r < 0.50:
            utt = random.choice(_CV_SMALL)
        elif r < 0.72:
            utt = random.choice(_CV_META)
        elif r < 0.80:
            utt = random.choice(_CV_OPINION)
        elif r < 0.90:
            utt = random.choice(_CV_ABOUT_TOPIC).format(t=random.choice(_CV_TOPICS))
        elif r < 0.96:
            utt = random.choice(_CV_BANTER)
        else:
            utt = random.choice(_CV_ABOUT_ULTRON)
        if random.random() < 0.2:
            utt = utt.capitalize()
        out.append({"input": utt, "output": "conversation"})
    return out


_CX_RESEARCH_PRIOR = [
    "when is the next Formula 1 race", "what's the rotten tomatoes score for the new Pixar movie",
    "how is the home team doing in the league", "what's the latest on the World Cup",
    "how much is a new laptop right now", "when does the Jurassic World sequel come out",
]
_CX_PA_PRIOR = [
    "what's my schedule", "add lunch with Sam at 12:30",
    "remind me to check the oven in 20 minutes", "when is my team meeting",
    "clear today", "move my dentist appointment to 4pm",
]
_CX_CODE_PRIOR = [
    "write a script that reverses a string", "run this python snippet",
    "why is my loop not terminating", "learn C++",
]
_CX_CORRECTIONS = [
    "no I meant {alt}", "I mean {alt}", "not that, {alt}", "sorry, {alt}",
    "no, {alt}", "I said {alt}", "that's wrong — {alt}", "actually {alt}",
]
_CX_ALT_RESEARCH = ["the 2026 one", "this season not last", "the new one", "from the trailer",
                    "the current price", "this stage of the tournament"]
_CX_ALT_PA = ["tomorrow not today", "at 3pm", "the school one", "the one for today",
              "12:30 not 12", "next week"]
_CX_ALT_CODE = ["in python", "the other file", "with the base as 4", "the compiled one"]
_CX_PUSHBACK = [
    "that's not right", "I think you hallucinated that", "that's not what I asked",
    "you're confusing two things", "that doesn't match what I said",
    "try again", "check that again", "are you sure about that",
]


def gen_context_corrections(n: int) -> list[dict]:
    out = []
    for _ in range(n):
        r = random.random()
        if r < 0.38:
            prior, alts, label = random.choice(_CX_RESEARCH_PRIOR), _CX_ALT_RESEARCH, "research_needed"
        elif r < 0.76:
            prior, alts, label = random.choice(_CX_PA_PRIOR), _CX_ALT_PA, "pa_domain"
        else:
            prior, alts, label = random.choice(_CX_CODE_PRIOR), _CX_ALT_CODE, "code_domain"
        if random.random() < 0.72:
            follow = random.choice(_CX_CORRECTIONS).format(alt=random.choice(alts))
        else:
            follow = random.choice(_CX_PUSHBACK)
        out.append({"input": f"[recent: {prior}] {follow}", "output": label})
    return out


def generate_triage_dataset(target_per_triage_category: int = 2000) -> list[dict]:
    pool_size = max(target_per_triage_category // 2, 300)
    pa_pool = []
    pa_pool += _relabel(data_gen.gen_calendar_add(pool_size))
    pa_pool += _relabel(data_gen.gen_calendar_update(pool_size))
    pa_pool += _relabel(data_gen.gen_calendar_delete(pool_size))
    pa_pool += _relabel(data_gen.gen_reminder(pool_size))
    pa_pool += _relabel(data_gen.gen_weather(pool_size))
    pa_pool += _relabel(data_gen.gen_calculator(pool_size))
    pa_pool += _relabel(data_gen.gen_special_times(pool_size // 4))
    pa_pool += gen_clock_related(pool_size // 4)

    pa_pool += gen_notes_and_scoped_clear(pool_size // 4)

    pa_pool += _relabel(data_gen.gen_vague_event_clarify(pool_size // 4))

    url_pool = gen_pasted_url(pool_size // 3)
    context_pool = gen_context_dependent_triage(pool_size)
    context_pool += url_pool

    context_pool += gen_context_corrections(pool_size)
    pa_pool += [e for e in context_pool if e["output"] == "pa_domain"]
    random.shuffle(pa_pool)
    pa_domain_examples = pa_pool[:target_per_triage_category]

    conv_and_research_pool = _relabel(data_gen.gen_conversation(target_per_triage_category * 3))
    conv_and_research_pool += [e for e in context_pool if e["output"] in ("research_needed", "conversation")]

    conv_and_research_pool += gen_research_wide(target_per_triage_category * 2)
    conv_and_research_pool += gen_conversation_wide(target_per_triage_category * 2)

    random.shuffle(conv_and_research_pool)
    conversation_examples = [e for e in conv_and_research_pool if e["output"] == "conversation"][:target_per_triage_category]
    research_examples = [e for e in conv_and_research_pool if e["output"] == "research_needed"][:target_per_triage_category]

    code_pool = _relabel(code_request_gen.gen_coding(target_per_triage_category * 2))
    code_pool += [e for e in context_pool if e["output"] == "code_domain"]
    random.shuffle(code_pool)
    code_domain_examples = code_pool[:target_per_triage_category]

    examples = pa_domain_examples + conversation_examples + research_examples + code_domain_examples
    random.shuffle(examples)
    return examples


def test_gen_context_dependent_triage_produces_all_four_categories():
    examples = gen_context_dependent_triage(200)
    labels = {e["output"] for e in examples}
    assert labels == {"research_needed", "pa_domain", "code_domain", "conversation"}, (
        f"expected all four categories to appear, got: {labels}"
    )


def test_gen_context_dependent_triage_stays_evenly_balanced_across_categories():
    from collections import Counter
    examples = gen_context_dependent_triage(4000)
    counts = Counter(e["output"] for e in examples)
    total = len(examples)
    for label, count in counts.items():
        share = count / total
        assert 0.18 <= share <= 0.32, (
            f"{label} is {share:.1%} of the context-dependent pool — "
            f"must stay close to an even 25% per category, not drift "
            f"toward any single one"
        )


def test_gen_context_dependent_triage_examples_carry_real_context_prefix():
    examples = gen_context_dependent_triage(50)
    assert all(e["input"].startswith("[recent:") for e in examples)


def test_gen_context_dependent_triage_research_example_carries_a_correction():
    random.seed(1)
    examples = gen_context_dependent_triage(500)
    research_examples = [e for e in examples if e["output"] == "research_needed"]
    assert research_examples, "must produce at least some research_needed context examples"
    assert any("no" in e["input"].lower() for e in research_examples)


def test_generate_triage_dataset_still_runs_and_stays_balanced():
    from collections import Counter
    dataset = generate_triage_dataset(target_per_triage_category=100)
    counts = Counter(ex["output"] for ex in dataset)
    assert set(counts.keys()) == {"conversation", "pa_domain", "code_domain", "research_needed"}
    for label, count in counts.items():
        assert count <= 100, f"{label} exceeded its target — balancing broke: {count}"


def main():
    dataset = generate_triage_dataset()

    from collections import Counter
    counts = Counter(ex["output"] for ex in dataset)
    print(f"Generated {len(dataset)} triage examples:")
    for label, count in counts.most_common():
        pct = 100 * count / len(dataset)
        print(f"  {label}: {count} ({pct:.1f}%)")

    out_path = Path(__file__).parent / "data" / "friday_train.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for ex in dataset:
            f.write(json.dumps(ex) + "\n")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
