import os
import logging
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Gather
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

twilio_client = Client(
    os.getenv("TWILIO_ACCOUNT_SID"),
    os.getenv("TWILIO_AUTH_TOKEN"),
)

TWILIO_PHONE = os.getenv("TWILIO_PHONE_NUMBER")
BASE_URL = os.getenv("BASE_URL", "").rstrip("/")

# Voice config
VOICE = "Polly.Joanna"
LANGUAGE = "en-US"
SPEECH_LANG = "en-IN"          # STT language (works for Indian-accented English)
SPEECH_TIMEOUT = "3"           # seconds of silence before Twilio cuts off
SPEECH_MODEL = "phone_call"    # Twilio enhanced model


def make_call(to_number: str, candidate_id: int) -> str:
    """Initiate outbound call. Returns call_sid."""
    number = str(to_number).strip().replace(" ", "")
    if not number.startswith("+"):
        number = "+91" + number

    call = twilio_client.calls.create(
        to=number,
        from_=TWILIO_PHONE,
        url=f"{BASE_URL}/webhook/call-start?candidate_id={candidate_id}",
        status_callback=f"{BASE_URL}/webhook/call-status",
        status_callback_method="POST",
        status_callback_event=["initiated", "ringing", "answered", "completed"],
        timeout=30,
        machine_detection="Enable",
        machine_detection_timeout=5,
    )
    logger.info(f"Call created: SID={call.sid} → {number}")
    return call.sid


def _gather(response: VoiceResponse, action_url: str) -> Gather:
    """Create a consistent Gather verb."""
    return Gather(
        input="speech",
        action=action_url,
        method="POST",
        timeout=int(SPEECH_TIMEOUT),
        speech_timeout="auto",
        language=SPEECH_LANG,
        enhanced=True,
    )


def build_greeting_twiml(greeting_text: str, candidate_id: int) -> str:
    """TwiML for the very first turn — speak greeting, listen for response."""
    response = VoiceResponse()
    action = f"{BASE_URL}/webhook/gather?candidate_id={candidate_id}"

    gather = _gather(response, action)
    gather.say(greeting_text, voice=VOICE, language=LANGUAGE)
    response.append(gather)

    # Fallback: no speech detected after greeting
    response.redirect(f"{BASE_URL}/webhook/no-input?candidate_id={candidate_id}&attempt=1")
    return str(response)


def build_agent_twiml(agent_text: str, candidate_id: int, is_final: bool = False) -> str:
    """TwiML for mid-conversation and final turns."""
    response = VoiceResponse()

    if is_final:
        response.say(agent_text, voice=VOICE, language=LANGUAGE)
        response.pause(length=1)
        response.hangup()
    else:
        action = f"{BASE_URL}/webhook/gather?candidate_id={candidate_id}"
        gather = _gather(response, action)
        gather.say(agent_text, voice=VOICE, language=LANGUAGE)
        response.append(gather)
        # Fallback if user goes silent mid-conversation
        response.redirect(f"{BASE_URL}/webhook/no-input?candidate_id={candidate_id}&attempt=1")

    return str(response)


def build_no_input_twiml(candidate_id: int, attempt: int) -> str:
    """Retry TwiML when no speech is detected."""
    response = VoiceResponse()
    action = f"{BASE_URL}/webhook/gather?candidate_id={candidate_id}"

    if attempt >= 2:
        response.say(
            "I'm sorry, I wasn't able to hear you. Thank you for your time. Goodbye!",
            voice=VOICE, language=LANGUAGE
        )
        response.hangup()
    else:
        gather = _gather(response, action)
        gather.say(
            "I'm sorry, I didn't catch that. Could you please repeat your answer?",
            voice=VOICE, language=LANGUAGE
        )
        response.append(gather)
        response.redirect(
            f"{BASE_URL}/webhook/no-input?candidate_id={candidate_id}&attempt={attempt + 1}"
        )

    return str(response)


def build_error_twiml() -> str:
    response = VoiceResponse()
    response.say(
        "We encountered a technical issue. We apologize for the inconvenience. Goodbye!",
        voice=VOICE, language=LANGUAGE
    )
    response.hangup()
    return str(response)