import streamlit as st
import requests
import json
import time
import base64

st.set_page_config(page_title="PixieDuster", layout="centered", page_icon="logo.png")

# The Gemini key lives on the PixieDuster Worker, never in this page. The
# browser proves it is a person once (Turnstile, handled in index.html) and gets
# a short-lived session, which index.html leaves on window.pdSession.
API_ROOT = "https://pixieduster-api.me-c41.workers.dev/api"


def _session_token():
    """Read the session minted by index.html. Empty string outside the browser."""
    try:
        import session_token
        return session_token.TOKEN
    except ImportError:
        pass

    try:
        from js import window  # available under stlite/Pyodide
        token = str(window.localStorage.getItem("pdSession") or "")
        if token:
            return token
        return str(window.pdSession or "")
    except Exception as e:
        return ""


def _api_headers():
    headers = {"Content-Type": "application/json"}
    token = _session_token()
    if token:
        headers["x-session"] = token
    return headers


def _friendly_error(response):
    """Turn a proxy error into something a person can act on."""
    try:
        detail = response.json().get("detail") or response.json().get("error", {}).get("message")
    except Exception:
        detail = None
    if response.status_code == 429:
        return detail or "The free daily limit has been reached. Try again tomorrow."
    return detail or f"The service returned an error ({response.status_code})."


api_key = None  # the key lives on the Worker now

model_id = 'gemini-3.6-flash'

def call_gemini(api_key, model, prompt, uploaded_files=[], require_json=False):
    url = f"{API_ROOT}/models/{model}:generateContent"
    parts = [{"text": prompt}]
    for file in uploaded_files:
        mime_type = getattr(file, "type", "") or "application/octet-stream"
        if mime_type.startswith("text/") or mime_type in ["application/json", "text/markdown", "text/csv"]:
            text_data = file.getvalue().decode("utf-8", errors="replace")
            parts.append({"text": f"\n\n--- Document: {file.name} ---\n{text_data}\n--- End Document ---\n"})
        else:
            b64_data = base64.b64encode(file.getvalue()).decode("utf-8")
            parts.append({"inlineData": {"mimeType": mime_type, "data": b64_data}})
    payload = {"contents": [{"parts": parts}]}
    if require_json:
        payload["generationConfig"] = {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "questions": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "question": {"type": "STRING"},
                                "options": {
                                    "type": "ARRAY",
                                    "items": {"type": "STRING"}
                                }
                            },
                            "required": ["question", "options"]
                        }
                    }
                },
                "required": ["questions"]
            }
        }
    token = _session_token()
    if token.startswith("ERROR:"):
        raise Exception(f"Session Token Debug: {token}")

    for attempt in range(10):
        response = requests.post(url, headers=_api_headers(), json=payload)
        if response.ok:
            return response.json()["candidates"][0]["content"]["parts"][0]["text"]
        if response.status_code not in [408, 429, 500, 502, 503, 504]:
            break
        if attempt < 9:
            delay = min(2.0 * (1.5 ** attempt), 10.0)
            if response.status_code == 503:
                st.toast(f"Gemini is busy. Retrying in {int(delay)}s... (Attempt {attempt+1}/10)", icon="⏳")
            time.sleep(delay)
            
    raise Exception(_friendly_error(response))

def chat_gemini(api_key, model, sys_prompt, history, user_input):
    url = f"{API_ROOT}/models/{model}:generateContent"
    contents = []
    for msg in history:
        r = "user" if msg["role"] == "user" else "model"
        contents.append({"role": r, "parts": [{"text": msg["content"]}]})
    contents.append({"role": "user", "parts": [{"text": user_input}]})
    payload = {
        "systemInstruction": {"parts": [{"text": sys_prompt}]},
        "contents": contents
    }
    
    for attempt in range(10):
        response = requests.post(url, headers=_api_headers(), json=payload)
        if response.ok:
            return response.json()["candidates"][0]["content"]["parts"][0]["text"]
        if response.status_code not in [408, 429, 500, 502, 503, 504]:
            break
        if attempt < 9:
            delay = min(2.0 * (1.5 ** attempt), 10.0)
            if response.status_code == 503:
                st.toast(f"Gemini is busy. Retrying in {int(delay)}s... (Attempt {attempt+1}/10)", icon="⏳")
            time.sleep(delay)
            
    raise Exception(_friendly_error(response))


ANTI_AI_PROMPT_TEMPLATE = """# AI Persona & Style Guide

## Core Directives
1. **Human Authenticity:** Write with natural imperfections, active voice, and varied pacing. Never sound like a corporate robot or an over-enthusiastic AI.
2. **Strict Vocabulary Bans:** Completely avoid AI "tells" (e.g., "delve," "tapestry," "crucial," "realm," "testament to," "in conclusion," "additionally").
3. **Format Naturally:** Use paragraphs and natural transitions. Do not overuse bullet points, bolding, or symmetrical sentence structures. Do not summarize at the end.
4. **Tone:** Speak directly and conversationally without hedging, generic positivity, or forced calls to action.

## Author Persona & Terminology Standards
{extracted_persona}
"""


# Improved CSS for better contrast and layout
st.markdown("""
<style>
@import url('https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css');
@import url('https://fonts.googleapis.com/css2?family=Cinzel+Decorative:wght@700&family=Inter:wght@300;400;600&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

h1, h2, h3 {
    font-family: 'Cinzel Decorative', cursive !important;
    color: #ffd700 !important; 
    text-shadow: 0 0 15px rgba(255, 215, 0, 0.4);
    text-align: center;
}

/* Background gradient - high contrast */
.stApp {
    background: radial-gradient(circle at top, #2b1845, #0f081c);
    color: #ffffff;
}

/* Animated Pixie Dust Falling Effect */
/* Animate transform, never background-position.
   background-position is a paint property: animating it re-rasterizes the
   whole fixed, full-viewport gradient layer every single frame, forever.
   Zooming changes the raster scale, so the browser re-rasterizes that layer
   while it animates, and the whole page flashes. transform runs on the
   compositor instead: the layer is painted once and only moved. */
@keyframes dustFall {
  from { transform: translate3d(0, 0, 0); }
  to   { transform: translate3d(0, 350px, 0); }
}

.stApp::before {
    content: "";
    position: fixed;
    /* One tile taller than the viewport, so translating by exactly one tile
       height loops seamlessly without ever repainting. */
    top: -350px; left: 0; width: 100%; height: calc(100% + 350px);
    background-image: 
        radial-gradient(2px 2px at 40px 60px, rgba(255,215,0,0.8), rgba(0,0,0,0)),
        radial-gradient(2px 2px at 150px 120px, rgba(255,255,255,0.8), rgba(0,0,0,0)),
        radial-gradient(3px 3px at 250px 200px, rgba(255,215,0,0.6), rgba(0,0,0,0)),
        radial-gradient(1px 1px at 300px 40px, rgba(255,255,255,0.8), rgba(0,0,0,0)),
        radial-gradient(2px 2px at 80px 250px, rgba(255,215,0,0.8), rgba(0,0,0,0));
    background-repeat: repeat;
    background-size: 350px 350px;
    animation: dustFall 25s linear infinite;
    will-change: transform;
    pointer-events: none;
    z-index: 0;
}

/* Some people get motion sick, and some machines cannot afford the layer. */
@media (prefers-reduced-motion: reduce) {
    .stApp::before { animation: none; }
}

/* Primary buttons */
.stButton>button {
    background: linear-gradient(135deg, #ffd700, #daa520) !important;
    border: none !important;
    border-radius: 30px !important;
    font-family: 'Cinzel Decorative', cursive !important;
    font-size: 1.2rem !important;
    font-weight: bold !important;
    padding: 10px 24px !important;
    box-shadow: 0 4px 15px rgba(218, 165, 32, 0.4) !important;
    transition: all 0.3s ease !important;
    width: 100%;
}

.stButton>button, .stButton>button p, .stButton>button div {
    color: #0f081c !important; /* Force dark text for contrast on the gold button */
}

.stButton>button:hover {
    transform: translateY(-3px);
    box-shadow: 0 8px 25px rgba(218, 165, 32, 0.6) !important;
    color: #000000 !important;
}

/* Uploader styling */
[data-testid="stFileUploadDropzone"] {
    background-color: rgba(255, 255, 255, 0.05);
    border: 2px dashed #daa520;
    border-radius: 15px;
}
[data-testid="stFileUploadDropzone"]:hover {
    border-color: #ffd700;
    background-color: rgba(255, 255, 255, 0.1);
}


/* Hide default Streamlit running animation */
[data-testid="stStatusWidget"] {
    display: none !important;
    visibility: hidden !important;
}

/* Make inputs legible with high contrast */
.stTextInput>div>div>input, .stSelectbox>div>div>div {
    background-color: rgba(0, 0, 0, 0.5) !important;
    color: white !important;
    border: 1px solid rgba(218, 165, 32, 0.5) !important;
}

/* Chat container */
[data-testid="stChatMessage"] {
    background: rgba(0, 0, 0, 0.4);
    border-radius: 15px;
    border-left: 4px solid #ffd700;
    padding: 15px;
    margin-bottom: 10px;
}

/* Form headers and labels */
label {
    color: #e2d1f9 !important;
    font-weight: 600 !important;
    font-size: 1.1rem !important;
}
p {
    font-size: 1.1rem;
    color: #d1c4e9;
}

/* Mobile Optimization */
@media (max-width: 768px) {
    h1, h2, h3 { font-size: 1.6rem !important; }
    h4 { font-size: 1.2rem !important; }
    p, label, .stInfo { font-size: 0.95rem !important; }
    
    /* Scale logo down for mobile */
    .mobile-logo { width: 180px !important; }
    
    .stButton>button {
        font-size: 1rem !important;
        padding: 12px !important;
    }
    
    [data-testid="stChatMessage"] {
        padding: 10px;
    }
}
</style>
""", unsafe_allow_html=True)


# Encode logo for centered HTML
def get_base64_image(image_path):
    with open(image_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode()

logo_b64 = get_base64_image("logo.png")
st.markdown(f"<div style='text-align: center; margin-bottom: 20px;'><img class='mobile-logo' src='data:image/png;base64,{logo_b64}' width='250' style='filter: drop-shadow(0px 0px 15px rgba(255,215,0,0.3));'></div>", unsafe_allow_html=True)

st.markdown("<h3 style='text-align: center; margin-top: 0;'>Your Fairy Prompt-Mother</h3>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center;'>Upload writing samples and let the magic extract a unique voice for your AI companion.</p>", unsafe_allow_html=True)
st.write("---")

# State Management
if 'step' not in st.session_state:
    st.session_state.step = 1
if 'questions_data' not in st.session_state:
    st.session_state.questions_data = None
if 'uploaded_genai_files' not in st.session_state:
    st.session_state.uploaded_genai_files = []
if 'final_prompt' not in st.session_state:
    st.session_state.final_prompt = ""
if 'target_name' not in st.session_state:
    st.session_state.target_name = ""

# --- STEP 1: UPLOAD ---
if st.session_state.step == 1:
    # Visual Process Steps (instead of plain text)
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("<div style='background:rgba(255,255,255,0.05); padding:15px; border-radius:10px; text-align:center;'><i class='fa-solid fa-file-arrow-up fa-2x' style='color:#daa520; margin-bottom:10px;'></i><br><b>1. Upload</b><br><small>Drop text or PDFs.</small></div>", unsafe_allow_html=True)
    with col2:
        st.markdown("<div style='background:rgba(255,255,255,0.05); padding:15px; border-radius:10px; text-align:center;'><i class='fa-solid fa-brain fa-2x' style='color:#daa520; margin-bottom:10px;'></i><br><b>2. Analyze</b><br><small>Answer AI questions.</small></div>", unsafe_allow_html=True)
    with col3:
        st.markdown("<div style='background:rgba(255,255,255,0.05); padding:15px; border-radius:10px; text-align:center;'><i class='fa-solid fa-wand-magic-sparkles fa-2x' style='color:#daa520; margin-bottom:10px;'></i><br><b>3. Clone</b><br><small>Download the prompt.</small></div>", unsafe_allow_html=True)

    st.write("---")

    # ---- Two ways to use it --------------------------------------------
    st.markdown("<h3 style='text-align:center;'>Two ways to use it</h3>",
                unsafe_allow_html=True)

    col_web, col_cli = st.columns([1, 1.15])

    with col_web:
        st.markdown(
            "<div style='background:rgba(255,255,255,0.04); border:1px solid rgba(218,165,32,0.3);"
            " border-radius:14px; padding:20px 22px; height:100%;'>"
            "<div style='color:#e2d1f9; font-weight:700; font-size:1.05rem;'>"
            "<i class='fa-solid fa-window-maximize' style='color:#daa520;'></i>&nbsp; "
            "Right here, in the browser</div>"
            "<p style='color:#d1c4e9; font-size:0.92rem; margin:10px 0 0; line-height:1.55;'>"
            "Upload a handful of files and go. Nothing to install, nothing to sign up for."
            "</p>"
            "<p style='color:#8a7da3; font-size:0.85rem; margin:10px 0 0;'>"
            "Best for trying it, or for one quick persona.</p>"
            "</div>",
            unsafe_allow_html=True,
        )

    with col_cli:
        st.markdown(
            "<div style='background:linear-gradient(135deg, rgba(255,215,0,0.10), rgba(255,215,0,0.03));"
            " border:1.5px solid #ffd700; border-radius:14px; padding:20px 22px; height:100%;'>"
            "<div style='color:#ffd700; font-weight:700; font-size:1.05rem;'>"
            "<i class='fa-solid fa-terminal'></i>&nbsp; In your terminal - point it at everything</div>"
            "<p style='color:#d1c4e9; font-size:0.92rem; margin:10px 0 0; line-height:1.55;'>"
            "Give it a <b style='color:#ffd700;'>whole folder</b> and it reads every file inside: "
            "years of notes, screenshots of texts, photos of handwriting, saved emails, PDFs. "
            "No uploading, one file at a time, ever."
            "</p>"
            "<p style='color:#d1c4e9; font-size:0.92rem; margin:10px 0 0; line-height:1.55;'>"
            "Or give it a <b style='color:#ffd700;'>git repository</b> and it mines your commit "
            "messages, README and docstrings - writing you never thought of as writing.</p>"
            "</div>",
            unsafe_allow_html=True,
        )

    st.write("")
    st.markdown(
        "<p style='color:#8a7da3; font-size:0.85rem; margin-bottom:4px;'>"
        "Install it once, then point it wherever your writing lives:</p>",
        unsafe_allow_html=True,
    )
    st.code(
        "pip install https://gretchenboria-pixieduster.static.hf.space/pixieduster-0.1.0-py3-none-any.whl\n"
        "\n"
        "pixieduster clone --from ~/Documents/my-writing    # the entire folder\n"
        "pixieduster clone --repo .                         # a whole git repo\n"
        "pixieduster clone -d \"a friendly desktop robot with great humor\"",
        language="bash",
    )
    st.markdown(
        "<a href='pixieduster-0.1.0-py3-none-any.whl' download "
        "style='color:#ffd700; font-weight:600;'>"
        "<i class='fa-solid fa-download'></i> Download it directly</a>"
        " &nbsp;&middot;&nbsp; "
        "<a href='https://github.com/gretchenboria/PixieDuster' "
        "style='color:#ffd700; font-weight:600;'>"
        "<i class='fa-brands fa-github'></i> Source on GitHub</a>",
        unsafe_allow_html=True,
    )

    st.write("---")

    # ---- How it works -------------------------------------------------
    st.markdown("<h3 style='text-align:center;'>How it works</h3>", unsafe_allow_html=True)
    st.markdown(
        "<p style='text-align:center; color:#d1c4e9;'>Your writing goes in as one thing. It comes "
        "out measured against four empirical rubrics and a theory of humor, written up as "
        "one file you can paste into any AI.</p>",
        unsafe_allow_html=True,
    )
    # A bitmap, with its intrinsic size declared.
    #
    # width:100% and no dimensions is a reflow loop inside Hugging Face's
    # auto-resizing iframe: the image sizes off the container, that changes the
    # page height, the iframe resizes, a scrollbar appears or vanishes, the
    # container width changes, and round it goes. Zooming perturbs it into
    # oscillating and the whole app repaints. Declaring width/height gives the
    # browser the aspect ratio up front, so the height never depends on a
    # measurement that the height itself can change.
    st.markdown(
        "<div style='margin:6px 0 4px;'>"
        "<img src='./PixieDuster-Flow-web.png' alt='How PixieDuster works' "
        "width='2000' height='1320' decoding='async' "
        "style='display:block; max-width:100%; height:auto; aspect-ratio:2000/1320; "
        "border-radius:14px; border:1px solid rgba(218,165,32,0.35);'>"
        "</div>",
        unsafe_allow_html=True,
    )

    st.write("---")
    
    # Clean, linear layout instead of erratic columns
    st.markdown("### 1. Identify the Persona")
    target_input = st.text_input(
        "Whose voice are we cloning?", 
        placeholder="e.g., Myself, A 1920s detective, My best friend Sarah..."
    )
    target_name = target_input if target_input else "the author"
    
    st.markdown("### 2. Upload Writing Samples")
    with st.expander("💡 What makes a perfect sample?", expanded=True):
        st.write("For the most accurate psychological profiling, we recommend **3 to 5 samples** across different contexts:")
        st.markdown(
            "- **Informal:** A chat log, casual email, or social media post.\n"
            "- **Formal:** An essay, professional report, or dissertation.\n"
            "- **Multimodal:** We accept text files, PDFs, and even **screenshots of handwriting or chat bubbles** (PNG/JPG)!"
        )

    uploaded_files = st.file_uploader(
        "Drop files here", 
        accept_multiple_files=True, 
        type=['txt', 'pdf', 'png', 'jpg', 'jpeg'],
        label_visibility="collapsed"
    )

    st.write("---")
    analyze_btn = st.button("Begin Analysis", use_container_width=True)

    if analyze_btn:
        if uploaded_files:
            st.session_state.target_name = target_name
            with st.status("Running Analysis...", expanded=True) as status:
                try:
                    st.markdown("<i class='fa-solid fa-magnifying-glass fa-beat-fade' style='color:#ffd700;'></i> Inspecting your writing samples...", unsafe_allow_html=True)
                    # Convert UploadedFile objects to in-memory objects immediately
                    # so they survive when the file_uploader widget is unmounted in Step 2.
                    class MemFile:
                        def __init__(self, name, type, data):
                            self.name = name
                            self.type = type
                            self.data = data
                        def getvalue(self):
                            return self.data
                    
                    mem_files = [MemFile(f.name, f.type, f.getvalue()) for f in uploaded_files]
                    st.session_state.uploaded_genai_files = mem_files
                    
                    st.markdown("<i class='fa-solid fa-list-check fa-flip' style='color:#ffd700;'></i> Formulating profiling questions...", unsafe_allow_html=True)
                    prompt_instruction = (
                        f"Analyze the provided writing samples belonging to '{target_name}'. "
                        "Formulate 3 highly specific multiple-choice questions to ask the author to uncover deep personality quirks, cognitive styles, or stylistic choices that aren't perfectly obvious from the text alone. "
                        "Output the result STRICTLY as valid JSON with the following schema: "
                        '{"questions": [{"question": "...", "options": ["...", "..."]}]}'
                    )

                    time.sleep(0.1) # Force UI to render before blocking network request
                    
                    response_text = call_gemini(api_key, model_id, prompt_instruction, mem_files, require_json=True)
                    clean_text = response_text.strip()
                    if clean_text.startswith("```json"): clean_text = clean_text[7:]
                    elif clean_text.startswith("```"): clean_text = clean_text[3:]
                    if clean_text.endswith("```"): clean_text = clean_text[:-3]
                    clean_text = clean_text.strip()
                    try:
                        st.session_state.questions_data = json.loads(clean_text)
                    except json.JSONDecodeError as e:
                        raise Exception("The AI generated a malformed JSON payload (likely an unescaped quote). Please click 'Begin Analysis' again to let it retry!")
                    status.update(label="Analysis Complete!", state="complete", expanded=False)
                    time.sleep(0.5) 
                    
                    st.session_state.step = 2
                    st.rerun()
                    
                except Exception as e:
                    status.update(label="Analysis Failed", state="error")
                    st.error(f"An error occurred: {e}")
        else:
            st.warning("Please upload at least one writing sample.")

# --- STEP 2: INTERACTIVE Q&A ---
elif st.session_state.step == 2:
    st.subheader("Clarifying the Magic")
    st.write(f"To perfectly calibrate '{st.session_state.target_name}', please select the most accurate answers below:")
    
    user_selections = []
    
    # Render multiple choice questions
    if isinstance(st.session_state.questions_data, list):
        questions = st.session_state.questions_data
    elif isinstance(st.session_state.questions_data, dict):
        questions = st.session_state.questions_data.get('questions', [])
    else:
        questions = []
    for i, q in enumerate(questions):
        st.markdown(f"**{i+1}. {q['question']}**")
        ans = st.radio(f"Options for Q{i+1}", q['options'], key=f"q_{i}", label_visibility="collapsed")
        user_selections.append(f"Q: {q['question']}\nA: {ans}")
        st.write("") # spacing
        
    user_answers_formatted = "\n\n".join(user_selections)
    
    st.write("---")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Go Back"):
            st.session_state.step = 1
            st.rerun()
    with col2:
        if st.button("Generate Final Prompt"):
            if user_answers_formatted:
                with st.status("Generating Final Persona...", expanded=True) as status:
                    try:
                        st.markdown("<i class='fa-solid fa-pen-nib fa-bounce' style='color:#ffd700;'></i> Compiling persona data...", unsafe_allow_html=True)
                        
                        final_instruction = (
                            f"Here are the original writing samples for '{st.session_state.target_name}'. "
                            f"I also asked the user some multiple choice questions to refine the persona.\n"
                            f"Here are their answers:\n{user_answers_formatted}\n\n"

                            "PSYCHOLOGICAL & EMPIRICAL PROFILING RUBRIC:\n"
                            "You must evaluate the text and answers strictly using the following empirical rubrics:\n"
                            "1. LIWC Lexical/Syntactic Fingerprint: Analyze Pronoun Orientation (1st person singular vs plural vs 2nd/3rd), Affective Processes (Positive vs Negative Emotion clusters), Cognitive Processes (Insight, Causation, Tentativeness vs Certainty), and Temporal Orientation (Past/Present/Future).\n"
                            "2. The Big Five (OCEAN): Map linguistic data to Openness, Conscientiousness, Extraversion, Agreeableness, and Neuroticism based on lexical richness, structure, social words, hedging, and self-doubt.\n"
                            "3. Cognitive Style & Epistemic Stance: Is the author analytical or narrative? Do they rely on empirical citations, personal anecdotes, or axioms? Do they display dialectical thinking or binary/dogmatic thinking?\n"
                            "4. Sociolinguistics: Document academic vs colloquial register, specific jargon, syntactic rhythm (staccato vs winding), and punctuation quirks.\n"
                            "5. Humor (Peter McGraw's Benign Violation Theory): Work out from the evidence whether this person is funny, how often, and by what mechanism. Humor happens when something violates a norm while simultaneously staying benign; violation alone is hostility, benign alone is bland. Identify which norms this author is willing to violate, what keeps those violations safe, and how dry or broad the delivery is. If the evidence shows someone who rarely jokes, say so plainly and specify restraint rather than inventing wit they do not have. If it shows someone consistently funny, give the specific rules and one example line in their voice. Never produce plain malignant jabs, and never separate the violation from the benign frame.\n\n"
                            "Based on ALL of this, extract their unique terminology standard, recurring thought patterns, sentence structure, and overall persona. "
                            "Output ONLY the extracted 'Terminology Standards & Persona' summary designed to be injected directly into a system prompt. Do not include any conversational filler."
                        )
                        
                        st.markdown("<i class='fa-solid fa-brain fa-pulse' style='color:#ffd700;'></i> Evaluating Big Five personality traits...", unsafe_allow_html=True)
                        time.sleep(0.4)
                        st.markdown("<i class='fa-solid fa-chart-bar fa-beat' style='color:#ffd700;'></i> Analyzing LIWC syntax and pronoun orientation...", unsafe_allow_html=True)
                        time.sleep(0.4)
                        st.markdown("<i class='fa-solid fa-puzzle-piece fa-spin' style='color:#ffd700;'></i> Assessing cognitive style...", unsafe_allow_html=True)
                        time.sleep(0.4)
                        st.markdown("<i class='fa-solid fa-comments fa-fade' style='color:#ffd700;'></i> Mapping sociolinguistics...", unsafe_allow_html=True)

                        time.sleep(0.1) # Force UI to render before blocking network request
                        
                        extracted_persona = call_gemini(api_key, model_id, final_instruction, st.session_state.uploaded_genai_files, require_json=False)
                        
                        st.session_state.final_prompt = ANTI_AI_PROMPT_TEMPLATE.replace("{extracted_persona}", extracted_persona)
                        
                        status.update(label="Persona Generated Successfully!", state="complete", expanded=False)
                        time.sleep(0.5)
                        
                        st.session_state.step = 3
                        st.rerun()
                    except Exception as e:
                        status.update(label="Analysis Failed", state="error")
                        st.error(f"An error occurred: {e}")
            else:
                st.warning("Please provide some answers to help the AI.")

# --- STEP 3: FINAL DELIVERABLE & CHAT ---
elif st.session_state.step == 3:
    st.success("Your Custom Persona Prompt is Ready!")

    if True:
        import re
        import html
        
        safe_prompt = html.escape(st.session_state.final_prompt)
        
        # Replace headers
        html_prompt = re.sub(r'(?m)^### (.*?)$', r'<h4 style="color:#e2d1f9; margin-top:20px; font-family:\'Inter\', sans-serif !important;">\1</h4>', safe_prompt)
        html_prompt = re.sub(r'(?m)^## (.*?)$', r'<h3 style="color:#ffd700 !important; border-bottom: 1px solid rgba(255,215,0,0.2); padding-bottom: 5px; margin-top:25px; text-align: left !important; font-family:\'Cinzel Decorative\', cursive !important;">\1</h3>', html_prompt)
        html_prompt = re.sub(r'(?m)^# (.*?)$', r'<h2 style="color:#ffd700 !important; margin-top:30px; text-align:center !important; font-family:\'Cinzel Decorative\', cursive !important;">\1</h2>', html_prompt)
        
        # Replace bold
        html_prompt = re.sub(r'\*\*(.*?)\*\*', r'<strong style="color: #ffd700;">\1</strong>', html_prompt)
        
        # Replace italics
        html_prompt = re.sub(r'\*(.*?)\*', r'<em>\1</em>', html_prompt)
        
        # Replace list items
        html_prompt = re.sub(r'(?m)^\* (.*?)$', r'<li style="margin-left: 20px; margin-bottom: 8px;">\1</li>', html_prompt)
        html_prompt = re.sub(r'(?m)^- (.*?)$', r'<li style="margin-left: 20px; margin-bottom: 8px;">\1</li>', html_prompt)
        
        # Wrap paragraphs
        paragraphs = html_prompt.split('\n\n')
        wrapped_paragraphs = []
        for p in paragraphs:
            if '<h' in p or '<li' in p:
                wrapped_paragraphs.append(p.replace('\n', ''))
            else:
                wrapped_paragraphs.append(f'<p style="margin-bottom: 15px; font-family:\'Inter\', sans-serif !important;">{p.replace(chr(10), "<br>")}</p>')
        
        html_prompt = "".join(wrapped_paragraphs)
        
        certificate_html = f'''
        <div style="border: 2px solid rgba(255,215,0,0.5); padding: 40px; background: linear-gradient(135deg, #160a24, #2b1845); color: #ffffff; text-align: left; border-radius: 15px; box-shadow: 0 10px 30px rgba(0,0,0,0.5), inset 0 0 20px rgba(255,215,0,0.05);">
           
           <div style="text-align: center; margin-bottom: 30px;">
               <img src="data:image/png;base64,{logo_b64}" width="120" style="margin-bottom: 15px; filter: drop-shadow(0px 0px 10px rgba(255,215,0,0.4));">
               <h1 style="color: #ffd700 !important; font-family: 'Cinzel Decorative', cursive !important; margin:0; font-size: 32px; text-shadow: 0 0 10px rgba(255,215,0,0.5) !important; text-align: center !important;">CERTIFICATE OF PERSONA</h1>
               <p style="font-family: 'Inter', sans-serif !important; font-size: 16px; color: #d1c4e9 !important; margin-top: 10px; text-align: center !important;">Officially cloned for: <b style="color: #ffd700;">{st.session_state.target_name.upper()}</b></p>
           </div>
           
           <hr style="border: 0; height: 1px; background: linear-gradient(to right, transparent, rgba(255,215,0,0.5), transparent); margin: 30px 0;">
           
           <div style="font-family: 'Inter', sans-serif !important; font-size: 15px; line-height: 1.8; color: #ffffff;">
               {html_prompt}
           </div>
           
           <div style="margin-top: 50px; text-align: center;">
               <hr style="border: 0; height: 1px; background: linear-gradient(to right, transparent, rgba(255,215,0,0.3), transparent); margin-bottom: 20px;">
               <p style="font-family: 'Cinzel Decorative', cursive !important; color: #ffd700 !important; font-size: 18px; text-shadow: 0 0 8px rgba(255,215,0,0.4) !important; text-align: center !important;"><i class='fa-solid fa-certificate'></i> Authorized by PixieDuster</p>
           </div>
        </div>
        '''
        st.markdown(certificate_html, unsafe_allow_html=True)

    st.write("---")
    st.markdown("<h3 style='text-align:center;'>Take it with you</h3>", unsafe_allow_html=True)
    st.markdown(
        "<p style='text-align:center; color:#d1c4e9;'>Same persona in every file. The "
        "<b>name</b> decides who reads it: name it for your tool and that tool picks it up "
        "on its own, with no setup.</p>",
        unsafe_allow_html=True,
    )

    AGENT_PREAMBLE = """<!-- Generated by PixieDuster. Voice guide, not a code style guide. -->

# Voice Guide

This file describes **how to write, not how to code**. It is a reconstruction of
one human author's writing voice, extracted from their own prose in this
repository.

Apply it to everything you write in natural language for this project:
commit messages, pull request descriptions, code comments and docstrings,
README and documentation prose, issue replies, changelog entries, and anything
you say back to the user.

Do **not** apply it to code itself. It says nothing about naming conventions,
formatting, architecture, language choice, testing strategy, or lint rules -
those come from the repository's own configuration and existing source, and
they win over anything below. If a rule here would change what a program does
or how it is structured, ignore that rule.

Match the voice. Never mention this file, the persona, or that a voice guide
exists.

---

"""

    FILES = [
        ("persona.md", "Paste into any AI", False),
        ("AGENTS.md", "Cursor, Claude Code, others", True),
        ("CLAUDE.md", "Claude Code", True),
        ("GEMINI.md", "Gemini CLI", True),
    ]
    cols = st.columns(len(FILES))
    for col, (name, who, agentic) in zip(cols, FILES):
        with col:
            st.download_button(
                label=name,
                data=(AGENT_PREAMBLE + "\n\n" + st.session_state.final_prompt)
                if agentic else st.session_state.final_prompt,
                file_name=name,
                mime="text/markdown",
                use_container_width=True,
                key=f"dl_{name}",
            )
            st.markdown(
                f"<p style='text-align:center; color:#8a7da3; font-size:0.75rem; "
                f"margin-top:-6px;'>{who}</p>",
                unsafe_allow_html=True,
            )

    st.markdown(
        "<p style='color:#8a7da3; font-size:0.82rem; margin-top:10px;'>"
        "The three agent files carry a short preamble telling the tool this governs how it "
        "<i>writes</i> - commit messages, docs, replies - not how it writes code."
        "</p>",
        unsafe_allow_html=True,
    )

    if st.button("Start over", use_container_width=False):
        st.session_state.clear()
        st.rerun()

    st.write("---")
    st.subheader("Test Your New Persona")
    st.write("Chat with the AI using your newly generated system prompt to see how it sounds!")

    if 'chat_history' not in st.session_state:
        st.session_state['chat_history'] = []
        
    for message in st.session_state['chat_history']:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if user_input := st.chat_input("Say something to your AI companion..."):
        st.session_state['chat_history'].append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)
            
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    response_text = chat_gemini(api_key, model_id, st.session_state.final_prompt, st.session_state['chat_history'][:-1], user_input)
                    st.markdown(response_text)
                    st.session_state['chat_history'].append({"role": "assistant", "content": response_text})
                except Exception as e:
                    st.error(f"Chat error: {e}")
