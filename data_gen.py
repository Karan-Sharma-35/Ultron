"""EDITH's training data: templated, fully synthetic sentences for the personal-assistant skills
(calendar add/update/delete, reminders, weather, calculator), plus conversation, research and
"clarify" rows so she learns to ask instead of inventing a missing time, date or title.

  python data_gen.py      -> data/edith_train.jsonl
"""
from __future__ import annotations

import json
import random
from pathlib import Path

random.seed(1234)


_ORIGINAL_TASKS = [
    "go to the gym", "call mom", "check the oven", "submit the report",
    "pick up groceries", "water the plants", "review the PR", "pay rent",
    "take out the trash", "walk the dog", "renew the passport",
    "check this reminder", "stretch", "drink water", "back up the server",
]
TASK_VERBS = [
    "call", "email", "text", "meet with", "visit", "check on", "pick up",
    "drop off", "review", "finish", "submit", "renew", "pay", "book",
    "cancel", "confirm", "update", "clean", "fix", "buy", "return",
    "walk", "feed", "water", "charge", "back up", "restart", "install",
    "repair", "sign", "file", "print", "prep for", "organize", "pack",
]
TASK_OBJECTS = [
    "mom", "dad", "the dentist", "the client", "the report", "the car",
    "the passport", "the lease", "the flight", "the presentation",
    "the garden", "the dog", "the cat", "the laptop", "the router",
    "the resume", "the invoice", "the taxes", "the insurance",
    "the subscription", "the gym membership", "the doctor", "the bank",
    "the landlord", "the team", "the project", "groceries", "the mail",
    "the trash", "the laundry", "the interview", "the meeting",
    "the plumber", "the electrician", "the accountant", "the vet",
    "the kids", "the neighbors", "the contract", "the budget", "the oven",
    "the plants", "the passport renewal", "the flight tickets",
]


def _random_task() -> str:
    if random.random() < 0.05:
        return random.choice(_ORIGINAL_TASKS)
    return f"{random.choice(TASK_VERBS)} {random.choice(TASK_OBJECTS)}"
NAMES = [
    "John", "Daniel", "Sarah", "the team", "my manager", "Priya", "the client",
    "David", "Mei", "Ahmed", "Lisa", "the landlord", "my sister", "my brother",
    "the recruiter", "Jake", "Fatima", "the professor", "my roommate",
    "the contractor", "Emma", "Raj", "my coworker", "the vendor", "Alex",
]
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
RELATIVE_DAYS = ["today", "tomorrow"]
HOURS_12 = list(range(1, 13))
AMPM = ["am", "pm"]
SPECIAL_TIMES = ["noon", "midnight"]


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
CITIES = ["London", "Paris", "New York", "Tokyo", "Toronto", "my area"]


def _time_str(hour, ampm, spelled=False, minute=None):
    h = number_to_words(hour) if spelled else str(hour)
    joined = not spelled and random.random() < 0.7
    sep = "" if joined else " "
    if minute:
        return f"{h}:{minute:02d}{sep}{ampm}" if not spelled else f"{h} {minute} {ampm}"
    return f"{h}{sep}{ampm}"


def _day_choice():
    return random.choice(WEEKDAYS + RELATIVE_DAYS)


def _fmt_time_field(hour, ampm, minute=0):
    h24 = hour % 12
    if ampm == "pm":
        h24 += 12
    return f"{h24:02d}:{minute:02d}"


def gen_calendar_add(n: int) -> list[dict]:
    out = []
    add_verbs = ["add an event", "set up an event", "schedule an event", "put an event on my calendar",
                 "can you set an event", "could you please add an event", "make an event"]

    alt_structures = [
        "block off {day} {period} at {time} for {task}",
        "I need to {task} {day} at {time}",
        "put {task} on the calendar for {day} at {time}",
        "can we schedule {task} for {day} at {time}",
        "{task} is happening {day} at {time}",
        "don't forget {task} on {day} at {time}",
        "I've got to {task} {day} at {time}",
        "penciling in {task} for {day} at {time}",
    ]
    periods = ["morning", "afternoon", "evening", "night"]
    for _ in range(n):
        task = _random_task()
        day = _day_choice()
        hour = random.choice(HOURS_12)
        ampm = random.choice(AMPM)
        spelled = random.random() < 0.15
        time_field = _fmt_time_field(hour, ampm)
        time_str = _time_str(hour, ampm, spelled)

        if random.random() < 0.5:
            verb = random.choice(add_verbs)
            utt = f"{verb} for {day} at {time_str} to {task}"
        else:
            structure = random.choice(alt_structures)
            utt = structure.format(day=day, time=time_str, task=task, period=random.choice(periods))

        out.append({
            "input": utt,
            "output": f"skill=calendar_add; title={task}; day={day}; time={time_field}",
        })

        if random.random() < 0.3:
            lead = random.choice([
                "I have a meeting", "there's an appointment", "I've got a call",
                "there's a meeting", "I have an appointment", "there's a call",
                "I've got an appointment", "I have a call",
            ])
            utt2 = f"{lead} {day} at {_time_str(hour, ampm)}"
            out.append({
                "input": utt2,
                "output": "skill=clarify; question=what's it about, or who's it with?",
            })
        else:
            name = random.choice(NAMES)
            utt3 = f"I have a meeting with {name} {day} at {_time_str(hour, ampm)}"
            out.append({
                "input": utt3,
                "output": f"skill=calendar_add; title=meeting with {name}; day={day}; time={time_field}",
            })
    return out


def gen_calendar_update(n: int) -> list[dict]:
    out = []
    for _ in range(n):
        task = _random_task()
        day = _day_choice()
        hour = random.choice(HOURS_12)
        ampm = random.choice(AMPM)
        new_hour = (hour % 12) + 1
        context = f"[recent: added '{task}' event {day} at {_time_str(hour, ampm)}]"
        phrasing = random.choice([
            "put that meeting we talked about earlier back an hour",
            "move it forward an hour",
            f"change the timing for my {task} thing to be {_time_str(new_hour, ampm)} instead of {_time_str(hour, ampm)}",
            f"can you move the {task} event to {_time_str(new_hour, ampm)}",
        ])
        out.append({
            "input": f"{context} {phrasing}",
            "output": (f"skill=calendar_update; title={task}; "
                       f"new_time={_fmt_time_field(new_hour, ampm)}; day={day}"),
        })
    return out


def gen_calendar_delete(n: int) -> list[dict]:
    out = []
    for _ in range(n):
        task = _random_task()
        day = _day_choice()

        hour = random.choice(HOURS_12)
        ampm = random.choice(AMPM)
        context = f"[recent: added '{task}' event {day} at {_time_str(hour, ampm)}]"

        phrasing = random.choice(["cancel that", "delete it", "remove that event", f"cancel the {task} event"])
        out.append({
            "input": f"{context} {phrasing}",
            "output": f"skill=calendar_delete; title={task}; day={day}",
        })

        out.append({
            "input": random.choice(["cancel that", "delete it", "remove this"]),
            "output": "skill=clarify; question=what does that refer to?",
        })
    return out


def gen_reminder(n: int) -> list[dict]:
    out = []
    slangy = [
        "yo lowkey remind me deadass at {t} {d} to {task} fr",
        "remind me at {t} {d} to {task}",
        "set a reminder for {t} {d} to {task}",
        "dont let me forget to {task} at {t} {d}",
        "ping me {d} at {t} to {task}",
        "give me a heads up {d} at {t} to {task}",
        "make sure I {task} {d} at {t}",
        "nudge me at {t} {d}, need to {task}",
    ]
    for _ in range(n):
        task = _random_task()
        day = random.choice(RELATIVE_DAYS + WEEKDAYS)
        hour = random.choice(HOURS_12)
        ampm = random.choice(AMPM)
        tmpl = random.choice(slangy)
        utt = tmpl.format(t=_time_str(hour, ampm), d=day, task=task)
        out.append({
            "input": utt,
            "output": f"skill=reminder; task={task}; day={day}; time={_fmt_time_field(hour, ampm)}",
        })

        bare_hour = random.choice(HOURS_12)
        utt2 = f"remind me at {bare_hour} {day} to {task}"
        out.append({
            "input": utt2,
            "output": f"skill=clarify; question=did you mean {bare_hour} AM or {bare_hour} PM?",
        })
    return out


def gen_weather(n: int) -> list[dict]:
    out = []
    phrasings = [
        "should I bring an umbrella {d}", "is it going to be cold out {d}",
        "what's it like outside {d}", "do I need a jacket {d}",
        "will it rain {d}", "how hot is it going to be {d}",
        "is it sunny {d}", "what's the temperature going to be {d}",
        "should I wear a coat {d}", "is it gonna be nice out {d}",
    ]
    for _ in range(n):
        d = random.choice(RELATIVE_DAYS)
        city = random.choice(CITIES)
        utt = random.choice(phrasings).format(d=d)
        if random.random() < 0.4:
            utt += f" in {city}"
            out.append({"input": utt, "output": f"skill=weather; day={d}; location={city}"})
        else:
            out.append({"input": utt, "output": f"skill=weather; day={d}; location=unspecified"})
    return out


def gen_calculator(n: int) -> list[dict]:
    out = []
    ops = [("times", "*"), ("plus", "+"), ("minus", "-"), ("divided by", "/")]
    for _ in range(n):
        a = random.randint(1, 20)
        b = random.randint(1, 20)
        op_word, op_sym = random.choice(ops)
        spelled = random.random() < 0.5
        a_str = number_to_words(a) if spelled else str(a)
        b_str = number_to_words(b) if spelled else str(b)
        utt = random.choice([
            f"what is {a_str} {op_word} {b_str}", f"what's {a_str} {op_word} {b_str}",
            f"calculate {a_str} {op_word} {b_str}",
        ])
        out.append({"input": utt, "output": f"skill=calculator; expression={a}{op_sym}{b}"})
    return out


def gen_conversation(n: int) -> list[dict]:
    domain_flavored = [
        "I love my calendar", "my calendar's a mess lately", "thanks for the help",
        "you're pretty good at this", "what do you think about that",
        "that reminder feature is neat", "I had a great meeting today, it went well",
        "remind me why I even set all this up", "calendars are so old-fashioned honestly",
        "my calendar is way too full this month", "reminders are such a good feature",
        "I really need to get better at managing my calendar",
        "my schedule this week is insane", "meetings are the worst part of my job",
        "I'm terrible at remembering appointments without help",
        "weather forecasts are never actually accurate anyway",
        "I hate doing math in my head", "calculators feel like cheating sometimes",
        "my reminders app used to be so buggy", "I used to use sticky notes for everything",
        "scheduling is honestly my least favorite part of the day",
        "I wish I was better with numbers", "the weather's been so weird lately",
        "I've been meaning to clean up my calendar for weeks",
        "reminders always seem to go off at the worst time",
        "I don't trust weather apps at all", "math was never my strong subject",
        "my calendar sync has been acting up", "you're better at scheduling than I am",
        "that was a good meeting today", "I appreciate you keeping me organized",
        "I should really set more reminders for myself",
        "the forecast said rain but it's sunny", "quick math like this is fun actually",
        "my calendar app crashed again yesterday", "I have too many recurring meetings",
        "note to self, get better at planning ahead",
        "I like how organized things have gotten lately",
        "yesterday's weather was rough", "I never check my reminders honestly",
    ]

    off_topic = [
        "how's your day going", "what's your favorite color",
        "tell me a joke", "do you ever get tired", "what's for dinner tonight",
        "I'm bored right now", "what's a good movie to watch this weekend",
        "my back hurts today", "I can't sleep lately", "traffic was insane this morning",
        "I'm thinking about learning guitar", "what's your opinion on pineapple on pizza",
        "I miss my old apartment", "my friend said something funny today",
        "I'm not sure what to make for lunch", "today's been a long day honestly",
        "what do you know about ancient Rome", "I just adopted a cat",
        "do you have a favorite season", "I'm nervous about a call tomorrow",
        "that book I started was actually really good",
        "my internet has been so slow lately", "I finally beat that game I've been stuck on",
        "I think I'm getting sick", "my plants are actually doing well for once",
        "I tried a new recipe last night and it turned out great",
        "I've been meaning to start running again", "my neighbor's dog won't stop barking",
        "I got into an argument with my sibling today", "I really need a haircut",
        "coffee just doesn't hit the same anymore", "I've been rewatching an old show lately",
        "my car's making a weird noise", "I think I'm burnt out from work",
        "I finally cleaned my room after weeks", "my favorite band is releasing new music",
        "I've been really into painting lately", "gas prices are getting ridiculous",
        "I can't decide what to be for halloween", "my phone battery is dying so fast lately",
        "I just got back from a really long walk", "I think I need new running shoes",
        "my roommate never does the dishes", "I've been trying to eat healthier",
        "that new restaurant downtown was actually amazing", "I hate mornings honestly",
        "I've been playing a lot of chess lately", "my sleep schedule is completely wrecked",
        "I think my wifi router needs to be replaced", "I just want to nap all day today",
        "video games have gotten so expensive", "I've been meaning to learn to cook more",
        "my desk is such a mess right now", "I really don't like public speaking",
        "I think I overcommitted myself this week", "camping this summer sounds fun",
        "I've been drinking way too much coffee", "my favorite hobby is honestly just reading",
        "I think I need a vacation badly", "board games are so underrated",
        "I just want to talk through something random", "what's something interesting you know",
        "do you like music", "what's a good book you'd recommend",
        "I'm just killing time right now", "not much going on, just chatting",
    ]

    negation = [
        "don't do anything to my calendar", "don't touch my reminders",
        "I don't want you to set anything right now", "don't change my schedule",
        "don't add anything, I'm just thinking out loud",
        "no need to remind me about this", "don't bother with my calendar today",
        "I'm not asking you to do anything, just venting",
    ]

    reasoning_shaped = [
        "should I take this job offer", "help me think through a decision I'm stuck on",
        "what would you do in my situation", "I don't know whether to say yes to this",
        "can you help me weigh the pros and cons of something",
        "I'm torn between two options and need to talk it out",
        "what's your honest opinion on this idea",
    ]

    research_needed = [
        "who is the current CEO of that company", "what's the latest version of that software",
        "who won the game last night", "what's the score of the match right now",
        "is that still the current president", "what's the stock price today",
        "what's the exchange rate right now", "is that show still airing",
        "what's the latest news on that", "did they release the new phone yet",
        "what's the current price of that", "who holds that record right now",
        "is that restaurant still open", "what's happening in the news today",
        "has that been announced yet", "what's trending right now",
        "is that still true these days", "what's the weather forecast for next week look like overall",
        "who's leading in the standings", "did that get released yet",
        "when does the new season come out", "what time does the store close tonight",
        "what time does the grocery store close tonight", "what time does the pharmacy close tonight",
        "is there a delay on the subway right now", "what are people saying about the new update",
        "is the flight on time",
        "what's the current interest rate", "any updates on the recall",
        "did the team win their game today", "has the package shipped yet",
        "what's the current unemployment rate", "is the new movie out yet",
        "what's the traffic like on the highway right now", "did they announce the winner",
        "is the concert still happening tonight", "what's the latest on the investigation",
    ]
    lines = domain_flavored + off_topic + negation + reasoning_shaped
    out = []
    for _ in range(n):
        out.append({"input": random.choice(lines), "output": "skill=conversation"})
    for _ in range(n // 3):
        out.append({"input": random.choice(research_needed), "output": "skill=research_needed"})
    return out


def gen_special_times(n: int) -> list[dict]:
    out = []
    for _ in range(n):
        task = _random_task()
        day = random.choice(RELATIVE_DAYS + WEEKDAYS)
        special = random.choice(SPECIAL_TIMES)
        time_field = "12:00" if special == "noon" else "00:00"
        kind = random.choice(["add", "reminder"])
        if kind == "add":
            out.append({
                "input": f"add an event for {day} at {special} to {task}",
                "output": f"skill=calendar_add; title={task}; day={day}; time={time_field}",
            })
        else:
            out.append({
                "input": f"remind me at {special} {day} to {task}",
                "output": f"skill=reminder; task={task}; day={day}; time={time_field}",
            })
    return out


def gen_vague_event_clarify(n: int) -> list[dict]:
    out = []
    vague_existence = [
        "I've got something going on {day}",
        "there's a thing {day} I need to remember",
        "I have something happening {day}",
        "something's going on {day} I don't want to forget",
        "there's a thing coming up {day}",
        "I've got stuff going on {day}",
        "I need to remember something for {day}",
    ]
    vague_generic_event = [
        "put an event on my calendar for {vague_time}",
        "add something to my calendar for {vague_time}",
        "I need to schedule something {vague_time}",
        "can you put an event in for {vague_time}",
        "block something off on my calendar {vague_time}",
    ]
    vague_times = ["next week", "sometime soon", "later this month", "at some point", "sometime this week"]
    day_periods = ["morning", "afternoon", "evening", "night"]

    for _ in range(n):
        if random.random() < 0.6:
            day = random.choice(WEEKDAYS + RELATIVE_DAYS)
            if random.random() < 0.4:
                day = f"{day} {random.choice(day_periods)}"
            utt = random.choice(vague_existence).format(day=day)
        else:
            utt = random.choice(vague_generic_event).format(vague_time=random.choice(vague_times))
        out.append({
            "input": utt,
            "output": "skill=clarify; question=what's the event, and when exactly?",
        })
    return out


def build_dataset(per_category: int = 900) -> list[dict]:
    data = (
        gen_calendar_add(per_category)
        + gen_calendar_update(per_category)
        + gen_calendar_delete(per_category)
        + gen_reminder(per_category)
        + gen_weather(per_category)
        + gen_calculator(per_category)

        + gen_conversation(per_category * 2)
        + gen_special_times(per_category // 4)
        + gen_vague_event_clarify(per_category // 6)
    )
    random.shuffle(data)
    return data


if __name__ == "__main__":
    data = build_dataset(per_category=900)
    print(f"Generated {len(data)} examples")
    for ex in random.sample(data, 8):
        print(" IN :", ex["input"])
        print(" OUT:", ex["output"])
        print()
    out_path = Path(__file__).parent / "data" / "edith_train.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for ex in data:
            f.write(json.dumps(ex) + "\n")
    print(f"Wrote {out_path}")
