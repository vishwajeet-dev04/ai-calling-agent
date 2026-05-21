import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Default questions — can be extended or replaced via config/DB later
DEFAULT_SURVEY_QUESTIONS = [
    {
        "key": "overall_satisfaction",
        "question": "On a scale of 1 to 10, how satisfied are you with our product or service overall?",
    },
    {
        "key": "would_recommend",
        "question": "Would you recommend us to a friend or colleague? Please say yes or no, and feel free to share why.",
    },
    {
        "key": "issues_faced",
        "question": "Have you faced any issues or challenges with our product or service? Please describe briefly.",
    },
    {
        "key": "suggestions",
        "question": "Do you have any suggestions for how we can improve? Any feedback is welcome.",
    },
]

SYSTEM_PROMPT = """You are a professional and friendly AI survey agent making phone calls on behalf of a company.

Your job:
1. GREETING PHASE: Confirm you are speaking with the correct person by their name. Be polite and brief.
   - If they confirm: proceed to the survey with the first question.
   - If they deny or say wrong number: politely apologize and end the call.
   - If unclear or silence: ask once more.

2. SURVEY PHASE: Ask survey questions one at a time.
   - Listen to their answer, acknowledge it briefly and warmly.
   - Then move to the next question naturally.
   - If this was the last question, thank them and move to closing.

3. CLOSING PHASE: Thank them warmly for their time and wish them a good day.

Rules:
- Keep responses SHORT — 2 to 3 sentences max. This is a live phone call.
- Be warm, human, and conversational. Never robotic or stiff.
- Never ask multiple questions at once.
- If the person wants to end the call early, thank them gracefully and stop.
- Do NOT repeat the question verbatim if they gave a partial answer — probe gently once if needed.

Respond ONLY with what the agent should say out loud. No stage directions, no labels."""


def get_greeting(candidate_name: str) -> str:
    """Generate the opening greeting line for the call."""
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Start the call. Greet the person and confirm you are speaking with {candidate_name}. "
                    "Mention you are an AI survey agent calling about their product experience. "
                    "Keep it to 2 short sentences."
                ),
            },
        ],
        max_tokens=120,
        temperature=0.6,
    )
    return response.choices[0].message.content.strip()


def get_agent_response(session: dict, user_input: str) -> tuple[str, dict]:
    """
    Core LLM brain. Takes session state + user speech, returns agent reply + updated session.

    Session keys:
        candidate_name       : str
        phase                : 'greeting' | 'survey' | 'closing'
        question_index       : int
        answers              : dict
        conversation_history : list of {role, content}
        confirmed_identity   : bool
        retry_count          : int  ← tracks consecutive no-input retries
    """
    history = session.get("conversation_history", [])
    phase = session.get("phase", "greeting")
    name = session.get("candidate_name", "there")
    q_index = session.get("question_index", 0)
    answers = session.get("answers", {})
    retry_count = session.get("retry_count", 0)
    questions = session.get("questions", DEFAULT_SURVEY_QUESTIONS)

    # ── Handle empty / retry input ──────────────────────────────────────────
    if not user_input.strip():
        retry_count += 1
        session["retry_count"] = retry_count
        if retry_count >= 2:
            # Give up on this turn, move to closing gracefully
            session["phase"] = "closing"
            agent_text = "It seems you might be busy right now. Thank you for your time, and have a wonderful day. Goodbye!"
        else:
            agent_text = "I'm sorry, I didn't catch that. Could you please repeat your answer?"
        history.append({"role": "assistant", "content": agent_text})
        session["conversation_history"] = history
        return agent_text, session

    # Reset retry counter on successful input
    session["retry_count"] = 0

    # ── Build context for LLM ───────────────────────────────────────────────
    context_lines = [
        f"Current phase: {phase}",
        f"Candidate name: {name}",
    ]

    if phase == "greeting":
        context_lines.append(
            f"You greeted them and asked if you're speaking with {name}. "
            f"Their response was: '{user_input}'. "
            "Determine if they confirmed their identity. "
            "If yes, acknowledge and immediately ask the first survey question. "
            "If no, apologize and prepare to end the call."
        )
        if questions:
            context_lines.append(f"First survey question to ask if confirmed: {questions[0]['question']}")

    elif phase == "survey":
        if q_index < len(questions):
            current_q = questions[q_index]
            context_lines.append(f"Current question ({q_index + 1}/{len(questions)}): {current_q['question']}")
            context_lines.append(f"The user answered: '{user_input}'")
            if q_index + 1 < len(questions):
                next_q = questions[q_index + 1]
                context_lines.append(
                    f"Acknowledge their answer warmly in one sentence, then naturally transition to ask: {next_q['question']}"
                )
            else:
                context_lines.append(
                    "This was the LAST question. Acknowledge their answer and tell them the survey is complete. "
                    "Thank them warmly and wish them a good day."
                )
        else:
            context_lines.append("All questions are done. Move to a warm closing.")

    elif phase == "closing":
        context_lines.append("Thank them sincerely and end the call warmly.")

    context = "\n".join(context_lines)

    # ── Call Groq LLM ───────────────────────────────────────────────────────
    history.append({"role": "user", "content": f"[Caller said]: {user_input}"})

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n\nContext:\n" + context}
    ] + history

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        max_tokens=200,
        temperature=0.7,
    )

    agent_text = response.choices[0].message.content.strip()
    history.append({"role": "assistant", "content": agent_text})

    # ── Update session state based on phase ─────────────────────────────────
    if phase == "greeting":
        low = user_input.lower()
        confirmed_words = ["yes", "speaking", "this is", "yeah", "correct", "that's me", "yep", "sure"]
        denied_words = ["no", "wrong number", "not me", "wrong", "nobody"]

        if any(w in low for w in confirmed_words):
            session["confirmed_identity"] = True
            session["phase"] = "survey"
            session["question_index"] = 0
        elif any(w in low for w in denied_words):
            session["phase"] = "closing"

    elif phase == "survey":
        if q_index < len(questions):
            key = questions[q_index]["key"]
            answers[key] = user_input
            session["answers"] = answers
            session["question_index"] = q_index + 1

            if session["question_index"] >= len(questions):
                session["phase"] = "closing"

    session["conversation_history"] = history
    return agent_text, session
