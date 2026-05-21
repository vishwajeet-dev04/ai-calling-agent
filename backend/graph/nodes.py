import logging
from typing import Tuple
from groq import Groq
import os

logger = logging.getLogger(__name__)

_groq = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "llama-3.3-70b-versatile"

DEFAULT_SURVEY_QUESTIONS = [
    {"key": "overall_satisfaction", "question": "On a scale of 1 to 10, how satisfied are you with our product or service overall?"},
    {"key": "would_recommend", "question": "Would you recommend us to a friend or colleague? Please answer yes or no and feel free to share why."},
    {"key": "issues_faced", "question": "Have you faced any issues or challenges with our product or service recently?"},
    {"key": "suggestions", "question": "Finally, do you have any suggestions for how we can improve? Any feedback is truly welcome."},
]

BASE_SYSTEM = """You are a warm, professional AI survey agent making a phone call on behalf of a company.
Rules:
- Keep every response to 1-3 SHORT sentences. This is a live phone call.
- Be conversational and human, never robotic.
- Never ask two questions at once.
- Respond ONLY with what should be spoken aloud. No stage directions, no labels, no quotes."""

def _llm(system, user, history=None, max_tokens=150):
    messages = [{"role": "system", "content": system}]
    if history:
        messages.extend(history[-6:])
    messages.append({"role": "user", "content": user})
    resp = _groq.chat.completions.create(model=MODEL, messages=messages, max_tokens=max_tokens, temperature=0.65)
    return resp.choices[0].message.content.strip()

def greeting_node(candidate_name):
    prompt = (f"You are calling {candidate_name}. Introduce yourself as an AI survey agent calling on behalf of the company regarding their product experience. Ask to confirm you are speaking with them. Keep it to 2 sentences, warm and professional.")
    return _llm(BASE_SYSTEM, prompt)

def identity_node(session, user_input):
    name = session["candidate_name"]
    questions = session.get("questions", DEFAULT_SURVEY_QUESTIONS)
    low = user_input.lower().strip()
    confirmed_signals = ["yes", "yeah", "yep", "speaking", "this is", "that's me", "correct", "sure", "go ahead", "you can", "i am", "i'm"]
    denied_signals = ["no", "wrong", "not me", "nobody", "wrong number", "stop"]
    confirmed = any(s in low for s in confirmed_signals)
    denied = any(s in low for s in denied_signals)
    if confirmed:
        session["phase"] = "survey"
        session["question_index"] = 0
        first_q = questions[0]["question"]
        agent_text = _llm(BASE_SYSTEM, f"The person confirmed they are {name}. Thank them briefly and immediately ask this survey question: {first_q}")
    elif denied:
        session["phase"] = "ended"
        agent_text = _llm(BASE_SYSTEM, "The person said they are not the intended contact. Apologize politely and say goodbye. One sentence.")
    else:
        retry = session.get("identity_retry", 0)
        if retry >= 1:
            session["phase"] = "ended"
            agent_text = "I apologize for the confusion. Thank you for your time, and have a wonderful day. Goodbye!"
        else:
            session["identity_retry"] = retry + 1
            agent_text = _llm(BASE_SYSTEM, f"The person's response was unclear: '{user_input}'. Politely ask once more if you're speaking with {name}. One sentence.")
    session["conversation_history"].append({"role": "user", "content": user_input})
    session["conversation_history"].append({"role": "assistant", "content": agent_text})
    return agent_text, session

def survey_node(session, user_input):
    questions = session.get("questions", DEFAULT_SURVEY_QUESTIONS)
    q_index = session.get("question_index", 0)
    answers = session.get("answers", {})
    history = session.get("conversation_history", [])
    low = user_input.lower()
    exit_signals = ["stop", "end call", "hang up", "goodbye", "bye", "not interested", "no more", "that's all"]
    if any(s in low for s in exit_signals):
        session["phase"] = "closing"
        agent_text = _llm(BASE_SYSTEM, "The person wants to end the survey early. Thank them genuinely for the time they gave and say goodbye warmly.")
        session["conversation_history"].append({"role": "user", "content": user_input})
        session["conversation_history"].append({"role": "assistant", "content": agent_text})
        return agent_text, session
    current_q = questions[q_index]
    answers[current_q["key"]] = user_input
    session["answers"] = answers
    session["question_index"] = q_index + 1
    next_index = q_index + 1
    if next_index < len(questions):
        next_q = questions[next_index]
        prompt = (f"The person just answered '{current_q['question']}' with: '{user_input}'. Acknowledge their answer naturally in one short phrase. Then immediately ask: {next_q['question']}")
        agent_text = _llm(BASE_SYSTEM, prompt, history)
        session["phase"] = "survey"
    else:
        prompt = (f"The person just answered the final question '{current_q['question']}' with: '{user_input}'. Acknowledge and tell them the survey is complete. Thank them sincerely.")
        agent_text = _llm(BASE_SYSTEM, prompt, history)
        session["phase"] = "closing"
    session["conversation_history"].append({"role": "user", "content": user_input})
    session["conversation_history"].append({"role": "assistant", "content": agent_text})
    return agent_text, session

def closing_node(session):
    name = session.get("candidate_name", "")
    answered = len(session.get("answers", {}))
    total = len(session.get("questions", DEFAULT_SURVEY_QUESTIONS))
    prompt = (f"You have completed a survey call with {name}. They answered {answered} out of {total} questions. Give a warm, sincere thank-you closing. Wish them a great day. 2 sentences max.")
    return _llm(BASE_SYSTEM, prompt)

def route(session, user_input):
    phase = session.get("phase", "greeting")
    if not user_input.strip():
        retry = session.get("silence_retry", 0)
        session["silence_retry"] = retry + 1
        if retry >= 1:
            session["phase"] = "ended"
            return ("It seems this might not be a good time. Thank you so much, and have a wonderful day. Goodbye!", session)
        return ("I'm sorry, I didn't quite catch that. Could you please say that again?", session)
    session["silence_retry"] = 0
    if phase == "greeting":
        return identity_node(session, user_input)
    elif phase == "survey":
        return survey_node(session, user_input)
    elif phase == "closing":
        session["phase"] = "ended"
        text = closing_node(session)
        return text, session
    else:
        session["phase"] = "ended"
        return "Thank you for your time. Goodbye!", session
